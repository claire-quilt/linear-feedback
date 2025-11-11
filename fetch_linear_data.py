#!/usr/bin/env python3
"""
Linear Feature Requests Dashboard Generator
Fetches data from Linear API and generates analysis + dashboard
Updated to support Project → Epic → Issue hierarchy
"""

import os
import json
import requests
from datetime import datetime
import csv

# Configuration
LINEAR_API_KEY = os.environ.get('LINEAR_API_KEY')
LINEAR_API_URL = 'https://api.linear.app/graphql'
FEATURE_REQUESTS_TEAM_ID = 'fb28fcfd-dce3-42ce-87d3-57d084be9e97'

# GraphQL query to fetch projects
PROJECTS_QUERY = """
query($teamId: String!) {
  team(id: $teamId) {
    projects(first: 50) {
      nodes {
        id
        name
        description
        icon
      }
    }
  }
}
"""

# GraphQL query to fetch all tickets from Feature Requests team
ISSUES_QUERY = """
query($teamId: String!) {
  team(id: $teamId) {
    id
    name
    issues(first: 250, filter: { state: { type: { nin: ["canceled"] } } }) {
      nodes {
        id
        identifier
        title
        description
        state {
          name
          type
        }
        priority
        priorityLabel
        project {
          id
          name
        }
        parent {
          id
          identifier
          title
        }
        createdAt
        updatedAt
        creator {
          name
          email
        }
        labels {
          nodes {
            name
          }
        }
      }
    }
  }
}
"""

def fetch_projects():
    """Fetch projects from Linear API"""
    print("📦 Fetching projects from Linear API...")
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': LINEAR_API_KEY
    }
    
    payload = {
        'query': PROJECTS_QUERY,
        'variables': {
            'teamId': FEATURE_REQUESTS_TEAM_ID
        }
    }
    
    response = requests.post(LINEAR_API_URL, json=payload, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"API request failed with status {response.status_code}: {response.text}")
    
    data = response.json()
    
    if 'errors' in data:
        raise Exception(f"GraphQL errors: {data['errors']}")
    
    projects = data['data']['team']['projects']['nodes']
    print(f"✅ Found {len(projects)} projects")
    return projects

def fetch_linear_issues():
    """Fetch issues from Linear API"""
    print("🔍 Fetching issues from Linear API...")
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': LINEAR_API_KEY
    }
    
    payload = {
        'query': ISSUES_QUERY,
        'variables': {
            'teamId': FEATURE_REQUESTS_TEAM_ID
        }
    }
    
    response = requests.post(LINEAR_API_URL, json=payload, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"API request failed with status {response.status_code}: {response.text}")
    
    data = response.json()
    
    if 'errors' in data:
        raise Exception(f"GraphQL errors: {data['errors']}")
    
    issues = data['data']['team']['issues']['nodes']
    
    # Filter out issues that were converted to projects
    filtered_issues = [
        issue for issue in issues
        if not ('converted to project' in issue['title'].lower() or
                (issue.get('description') and 'converted to project' in issue['description'].lower()))
    ]
    
    print(f"✅ Found {len(issues)} issues ({len(issues) - len(filtered_issues)} converted epics filtered out)")
    return filtered_issues

def parse_ticket(ticket, all_issues):
    """Parse a Linear ticket to extract structured customer feedback"""
    import re
    
    description = ticket.get('description') or ''
    
    # Extract structured fields using regex
    customer_match = re.search(r'\*\*Customer:\*\*\s*([^\n]+)', description)
    quote_match = re.search(r'\*\*Quote:\*\*\s*[""""]([^""""]*)[""""]', description)
    if not quote_match:
        quote_match = re.search(r'\*\*Quote:\*\*\s*(.+?)(?=\n\n|\*\*|$)', description, re.DOTALL)
    wave_match = re.search(r'\*\*Survey Wave:\*\*\s*(Wave\s*)?(\d+)', description)
    source_match = re.search(r'\*\*Source:\*\*\s*([^\n]+)', description)
    
    # Extract customer name, removing email/markdown
    customer = None
    if customer_match:
        customer = customer_match.group(1).strip()
        # Remove email if present
        customer = re.sub(r'\s*\([^)]*@[^)]*\)', '', customer)
        # Remove mailto links
        customer = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', customer)
        customer = customer.strip()
    
    quote = quote_match.group(1).strip() if quote_match else ''
    wave = f"Wave {wave_match.group(2)}" if wave_match else None
    source = source_match.group(1).strip() if source_match else None
    
    # Determine source type
    source_type = "Unknown"
    if source:
        if any(keyword in source for keyword in ['CSAT', 'Wave']):
            source_type = 'CSAT Survey'
        elif any(keyword in source for keyword in ['Usage', 'Satisfaction']):
            source_type = 'Usage Survey'
        elif 'Early Adopter' in source or 'Qualitative Research' in source:
            source_type = 'Early Adopter Research'
        elif 'Beta' in source:
            source_type = 'Beta Testing'
        elif any(keyword in source for keyword in ['Support', 'Email']):
            source_type = 'Direct Support'
        elif 'Internal' in source:
            source_type = 'Internal'
    
    # Get project information
    project_name = None
    if ticket.get('project'):
        project_name = ticket['project']['name']
    
    # Get parent/epic information
    parent_id = None
    parent_title = None
    parent_identifier = None
    if ticket.get('parent'):
        parent_id = ticket['parent']['id']
        parent_identifier = ticket['parent']['identifier']
        parent_title = ticket['parent']['title']
    
    # Determine feature area from project or parent
    feature_area = project_name or "Unknown"
    
    # More specific categorization based on parent if available
    if parent_title:
        parent_lower = parent_title.lower()
        if 'smart home' in parent_lower or 'homekit' in parent_lower or 'integration' in parent_lower:
            feature_area = 'Smart Home Integrations'
        elif 'thermal' in parent_lower or 'comfort' in parent_lower or 'thermware' in parent_lower:
            feature_area = 'Thermals & Comfort [Thermware]'
        elif 'schedule' in parent_lower:
            feature_area = 'Schedules'
        elif 'app' in parent_lower and 'ux' in parent_lower:
            feature_area = 'All Things App (UX)'
        elif 'hardware' in parent_lower:
            feature_area = 'Hardware Requests'
        elif 'dial' in parent_lower:
            feature_area = 'All things Dial'
        elif 'energy' in parent_lower or 'usage' in parent_lower:
            feature_area = 'Energy + Usage'
        elif 'auto-away' in parent_lower or 'away' in parent_lower:
            feature_area = 'Auto-Away'
        elif 'mode' in parent_lower or 'control' in parent_lower:
            feature_area = 'Modes & Controls'
        elif 'lighting' in parent_lower or 'light' in parent_lower:
            feature_area = 'Lighting'
        elif 'device' in parent_lower or 'pairing' in parent_lower:
            feature_area = 'Device management & operation'
        elif 'partner' in parent_lower or 'tooling' in parent_lower:
            feature_area = 'Partner Tooling'
    
    return {
        'ticket_id': ticket['identifier'],
        'title': ticket['title'],
        'project': project_name or 'No Project',
        'epic': f"{parent_identifier}: {parent_title}" if parent_identifier and parent_title else 'No Epic',
        'epic_id': parent_identifier or '',
        'parent_id': parent_id,
        'feature_area': feature_area,
        'customer': customer,
        'wave': wave,
        'source_type': source_type,
        'source_detail': source,
        'priority': ticket.get('priorityLabel', 'No Priority'),
        'quote': quote[:500] if quote else '',  # Truncate long quotes
        'status': ticket['state']['name'],
        'created_at': ticket['createdAt'],
        'updated_at': ticket['updatedAt'],
        'has_customer_feedback': customer is not None,
        'url': f"https://linear.app/quiltair/issue/{ticket['identifier']}"
    }

def generate_csv(tickets, output_file='data/customer_feedback.csv'):
    """Generate CSV file with parsed ticket data"""
    print(f"📊 Generating CSV with {len(tickets)} tickets...")
    
    os.makedirs('data', exist_ok=True)
    
    # Filter to only tickets with customer feedback
    customer_tickets = [t for t in tickets if t['has_customer_feedback']]
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'ticket_id', 'title', 'project', 'epic', 'epic_id', 'feature_area', 
            'customer', 'wave', 'source_type', 'source_detail', 'priority', 
            'quote', 'status', 'created_at', 'updated_at', 'url'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for ticket in customer_tickets:
            # Remove fields not needed in CSV
            csv_ticket = {k: v for k, v in ticket.items() 
                         if k != 'has_customer_feedback' and k != 'parent_id'}
            writer.writerow(csv_ticket)
    
    print(f"✅ CSV saved to {output_file}")
    return customer_tickets

def generate_json(tickets, projects, output_file='data.json'):
    """Generate JSON file for dashboard consumption"""
    print(f"📋 Generating JSON data file...")
    
    data = {
        'lastUpdated': datetime.now().isoformat(),
        'projects': [
            {
                'id': p['id'],
                'name': p['name'],
                'description': p.get('description', ''),
                'icon': p.get('icon', '')
            }
            for p in projects
        ],
        'issues': [
            {
                'id': t['ticket_id'],
                'title': t['title'],
                'description': '',  # Not included to reduce file size
                'url': t['url'],
                'createdAt': t['created_at'],
                'updatedAt': t['updated_at'],
                'customer': t['customer'],
                'wave': t['wave'],
                'project': t['project'],
                'projectId': None,  # Could be added if needed
                'parentId': t['parent_id'],
                'state': t['status'],
                'labels': []  # Could be populated if needed
            }
            for t in tickets
        ]
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ JSON data saved to {output_file}")

def generate_statistics(tickets):
    """Generate statistics for the dashboard"""
    print("📈 Calculating statistics...")
    
    from collections import Counter
    
    stats = {
        'total_tickets': len(tickets),
        'unique_customers': len(set(t['customer'] for t in tickets if t['customer'])),
        'by_project': dict(Counter(t['project'] for t in tickets)),
        'by_feature_area': dict(Counter(t['feature_area'] for t in tickets)),
        'by_epic': dict(Counter(t['epic'] for t in tickets)),
        'by_wave': dict(Counter(t['wave'] for t in tickets if t['wave'])),
        'by_source_type': dict(Counter(t['source_type'] for t in tickets)),
        'by_priority': dict(Counter(t['priority'] for t in tickets)),
        'last_updated': datetime.now().isoformat()
    }
    
    # Sort by count
    stats['by_project'] = dict(sorted(stats['by_project'].items(), 
                                     key=lambda x: x[1], reverse=True))
    stats['by_feature_area'] = dict(sorted(stats['by_feature_area'].items(), 
                                           key=lambda x: x[1], reverse=True))
    stats['by_epic'] = dict(sorted(stats['by_epic'].items(), 
                                   key=lambda x: x[1], reverse=True))
    
    # Save statistics
    os.makedirs('data', exist_ok=True)
    with open('data/statistics.json', 'w') as f:
        json.dump(stats, f, indent=2)
    
    print("✅ Statistics saved to data/statistics.json")
    return stats

def generate_html_dashboard(tickets, stats):
    """Generate HTML dashboard with project-first hierarchy"""
    print("🎨 Generating HTML dashboard...")
    
    # Sort tickets by creation date (newest first)
    recent_tickets = sorted(tickets, key=lambda x: x['created_at'], reverse=True)[:20]
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Linear Feature Requests Dashboard - Quilt</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body class="bg-gray-50">
    <div class="min-h-screen p-6">
        <div class="max-w-7xl mx-auto">
            <!-- Header -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h1 class="text-3xl font-bold text-gray-900 mb-2">
                    Linear Feature Requests Dashboard
                </h1>
                <p class="text-gray-600">
                    Automated customer feedback analysis from Feature Requests team
                </p>
                <p class="text-sm text-gray-500 mt-2">
                    Last updated: {datetime.fromisoformat(stats['last_updated'].replace('Z', '+00:00')).strftime('%B %d, %Y at %I:%M %p UTC')}
                </p>
            </div>
            
            <!-- Summary Stats -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <div class="text-sm font-medium text-gray-600 mb-1">Total Tickets</div>
                    <div class="text-3xl font-bold text-gray-900">{stats['total_tickets']}</div>
                </div>
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <div class="text-sm font-medium text-gray-600 mb-1">Unique Customers</div>
                    <div class="text-3xl font-bold text-gray-900">{stats['unique_customers']}</div>
                </div>
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <div class="text-sm font-medium text-gray-600 mb-1">Projects</div>
                    <div class="text-3xl font-bold text-gray-900">{len(stats['by_project'])}</div>
                </div>
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <div class="text-sm font-medium text-gray-600 mb-1">Epics</div>
                    <div class="text-3xl font-bold text-gray-900">{len(stats['by_epic'])}</div>
                </div>
            </div>
            
            <!-- Charts Row -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <!-- Projects Chart -->
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <h2 class="text-lg font-semibold text-gray-900 mb-4">
                        Tickets by Project
                    </h2>
                    <canvas id="projectChart"></canvas>
                </div>
                
                <!-- Feature Area Chart -->
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <h2 class="text-lg font-semibold text-gray-900 mb-4">
                        Tickets by Feature Area
                    </h2>
                    <canvas id="featureAreaChart"></canvas>
                </div>
            </div>
            
            <!-- Top Projects & Epics Tables -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <!-- Top Projects -->
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <h2 class="text-lg font-semibold text-gray-900 mb-4">
                        Top Projects by Ticket Count
                    </h2>
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead>
                                <tr>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rank</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Project</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Count</th>
                                </tr>
                            </thead>
                            <tbody class="bg-white divide-y divide-gray-200">
"""
    
    # Add top projects
    top_projects = dict(list(stats['by_project'].items())[:10])
    for rank, (project, count) in enumerate(top_projects.items(), 1):
        html += f"""
                                <tr class="hover:bg-gray-50">
                                    <td class="px-4 py-3 text-sm font-medium text-gray-900">{rank}</td>
                                    <td class="px-4 py-3 text-sm text-gray-900">{project}</td>
                                    <td class="px-4 py-3 text-sm font-bold text-blue-600">{count}</td>
                                </tr>
"""
    
    html += """
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <!-- Top Epics -->
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <h2 class="text-lg font-semibold text-gray-900 mb-4">
                        Top Epics by Ticket Count
                    </h2>
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead>
                                <tr>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rank</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Epic</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Count</th>
                                </tr>
                            </thead>
                            <tbody class="bg-white divide-y divide-gray-200">
"""
    
    # Add top 10 epics
    top_epics = dict(list(stats['by_epic'].items())[:10])
    for rank, (epic, count) in enumerate(top_epics.items(), 1):
        html += f"""
                                <tr class="hover:bg-gray-50">
                                    <td class="px-4 py-3 text-sm font-medium text-gray-900">{rank}</td>
                                    <td class="px-4 py-3 text-sm text-gray-900 truncate max-w-xs">{epic}</td>
                                    <td class="px-4 py-3 text-sm font-bold text-blue-600">{count}</td>
                                </tr>
"""
    
    html += """
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <!-- Recent Tickets Table -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-900 mb-4">
                    Recent Tickets (Last 20)
                </h2>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead>
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Ticket</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Project</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Wave</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
"""
    
    for ticket in recent_tickets:
        created_date = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00')).strftime('%b %d, %Y')
        wave_badge = ''
        if ticket['wave']:
            wave_class = 'bg-blue-100 text-blue-800' if '1' in ticket['wave'] else 'bg-green-100 text-green-800'
            wave_badge = f'<span class="px-2 py-1 text-xs font-medium rounded {wave_class}">{ticket["wave"]}</span>'
        
        html += f"""
                            <tr class="hover:bg-gray-50">
                                <td class="px-4 py-3">
                                    <a href="{ticket['url']}" target="_blank" class="text-sm font-medium text-blue-600 hover:underline">
                                        {ticket['ticket_id']}
                                    </a>
                                    <div class="text-sm text-gray-500 truncate max-w-xs">{ticket['title']}</div>
                                </td>
                                <td class="px-4 py-3 text-sm text-gray-900">{ticket['customer'] or '—'}</td>
                                <td class="px-4 py-3 text-sm text-gray-900">{ticket['project']}</td>
                                <td class="px-4 py-3 text-sm">{wave_badge or '—'}</td>
                                <td class="px-4 py-3 text-sm text-gray-500">{created_date}</td>
                            </tr>
"""
    
    # Prepare chart data
    projects = list(stats['by_project'].keys())[:10]  # Top 10
    project_counts = list(stats['by_project'].values())[:10]
    
    feature_areas = list(stats['by_feature_area'].keys())[:10]  # Top 10
    feature_counts = list(stats['by_feature_area'].values())[:10]
    
    html += f"""
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- Download Section -->
            <div class="bg-white rounded-lg shadow-sm p-6">
                <h2 class="text-lg font-semibold text-gray-900 mb-4">
                    Download Data
                </h2>
                <div class="space-y-3">
                    <a href="data/customer_feedback.csv" 
                       download
                       class="inline-block px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition">
                        📥 Download CSV (Customer Feedback)
                    </a>
                    <a href="data/statistics.json" 
                       download
                       class="inline-block ml-4 px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium transition">
                        📊 Download Statistics (JSON)
                    </a>
                    <a href="data.json" 
                       download
                       class="inline-block ml-4 px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium transition">
                        🗂️ Download Full Data (JSON)
                    </a>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Project Chart
        const projectCtx = document.getElementById('projectChart').getContext('2d');
        new Chart(projectCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(projects)},
                datasets: [{{
                    label: 'Ticket Count',
                    data: {json.dumps(project_counts)},
                    backgroundColor: '#3b82f6'
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{ display: false }}
                }},
                scales: {{
                    y: {{ beginAtZero: true }}
                }}
            }}
        }});
        
        // Feature Area Chart
        const featureCtx = document.getElementById('featureAreaChart').getContext('2d');
        new Chart(featureCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(feature_areas)},
                datasets: [{{
                    label: 'Ticket Count',
                    data: {json.dumps(feature_counts)},
                    backgroundColor: '#10b981'
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{ display: false }}
                }},
                scales: {{
                    y: {{ beginAtZero: true }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    print("✅ Dashboard saved to index.html")

def main():
    """Main execution"""
    print("🚀 Starting Linear Feature Requests Dashboard Generator")
    print("=" * 60)
    
    if not LINEAR_API_KEY:
        raise Exception("LINEAR_API_KEY environment variable not set")
    
    # Fetch data
    projects = fetch_projects()
    raw_issues = fetch_linear_issues()
    print(f"✅ Fetched {len(raw_issues)} issues from Linear")
    
    # Parse tickets
    parsed_tickets = [parse_ticket(t, raw_issues) for t in raw_issues]
    
    # Filter to only tickets with customer feedback
    customer_tickets = [t for t in parsed_tickets if t['has_customer_feedback']]
    print(f"✅ Found {len(customer_tickets)} tickets with customer feedback")
    
    # Generate outputs
    generate_csv(customer_tickets)
    generate_json(parsed_tickets, projects)  # Include all tickets in JSON
    stats = generate_statistics(customer_tickets)
    generate_html_dashboard(customer_tickets, stats)
    
    print("=" * 60)
    print("✨ Dashboard generation complete!")
    print(f"📊 Total tickets analyzed: {stats['total_tickets']}")
    print(f"👥 Unique customers: {stats['unique_customers']}")
    print(f"📦 Projects: {len(stats['by_project'])}")
    print(f"📁 Feature areas: {len(stats['by_feature_area'])}")

if __name__ == '__main__':
    main()
