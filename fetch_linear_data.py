#!/usr/bin/env python3
"""
Linear Feature Requests Dashboard Generator
Fetches data from Linear API and generates analysis + dashboard
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

# GraphQL query to fetch all tickets from Feature Requests team
QUERY = """
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

def fetch_linear_data():
    """Fetch data from Linear API"""
    print("🔍 Fetching data from Linear API...")
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': LINEAR_API_KEY
    }
    
    payload = {
        'query': QUERY,
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
    
    return data['data']['team']['issues']['nodes']

def parse_ticket(ticket):
    """Parse a Linear ticket to extract structured customer feedback"""
    import re
    
    description = ticket.get('description', '')
    
    # Extract structured fields using regex
    customer_match = re.search(r'\*\*Customer:\*\*\s*([^\n]+)', description)
    quote_match = re.search(r'\*\*Quote:\*\*\s*[""""]([^""""]*)[""""]', description)
    if not quote_match:
        quote_match = re.search(r'\*\*Quote:\*\*\s*(.+?)(?=\n\n|\*\*|$)', description, re.DOTALL)
    wave_match = re.search(r'\*\*Survey Wave:\*\*\s*(\d+)', description)
    source_match = re.search(r'\*\*Source:\*\*\s*([^\n]+)', description)
    
    customer = customer_match.group(1).strip() if customer_match else None
    quote = quote_match.group(1).strip() if quote_match else ''
    wave = f"Wave {wave_match.group(1)}" if wave_match else "Unknown"
    source = source_match.group(1).strip() if source_match else "Unknown"
    
    # Determine source type
    source_type = "Unknown"
    if source and any(keyword in source for keyword in ['CSAT', 'Wave']):
        source_type = 'CSAT Survey'
    elif source and any(keyword in source for keyword in ['Usage', 'Satisfaction']):
        source_type = 'Usage Survey'
    elif source and 'Beta' in source:
        source_type = 'Beta Testing'
    elif source and any(keyword in source for keyword in ['Support', 'Email']):
        source_type = 'Direct Support'
    
    # Determine feature area from parent
    feature_area = "Unknown"
    if ticket.get('parent'):
        parent_title = ticket['parent']['title'].lower()
        if 'smart home' in parent_title:
            feature_area = 'Smart Home Integration'
        elif 'thermal' in parent_title or 'comfort' in parent_title:
            feature_area = 'Thermals & Comfort'
        elif 'schedule' in parent_title:
            feature_area = 'Schedules'
        elif 'app' in parent_title:
            feature_area = 'All Things App (UX)'
        elif 'hardware' in parent_title:
            feature_area = 'Hardware Requests'
        elif 'dial' in parent_title:
            feature_area = 'Dial Interface'
        elif 'energy' in parent_title or 'usage' in parent_title:
            feature_area = 'Energy Usage'
        elif 'auto-away' in parent_title:
            feature_area = 'Auto-Away Pain Points'
        elif 'mode' in parent_title:
            feature_area = 'Modes & Controls'
    
    return {
        'ticket_id': ticket['identifier'],
        'title': ticket['title'],
        'epic': f"{ticket['parent']['identifier']}: {ticket['parent']['title']}" if ticket.get('parent') else 'No Epic',
        'epic_id': ticket['parent']['identifier'] if ticket.get('parent') else '',
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
        'has_customer_feedback': customer is not None
    }

def generate_csv(tickets, output_file='data/customer_feedback.csv'):
    """Generate CSV file with parsed ticket data"""
    print(f"📊 Generating CSV with {len(tickets)} tickets...")
    
    os.makedirs('data', exist_ok=True)
    
    # Filter to only tickets with customer feedback
    customer_tickets = [t for t in tickets if t['has_customer_feedback']]
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'ticket_id', 'title', 'epic', 'epic_id', 'feature_area', 'customer',
            'wave', 'source_type', 'source_detail', 'priority', 'quote',
            'status', 'created_at', 'updated_at'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for ticket in customer_tickets:
            # Remove the has_customer_feedback field for CSV
            csv_ticket = {k: v for k, v in ticket.items() if k != 'has_customer_feedback'}
            writer.writerow(csv_ticket)
    
    print(f"✅ CSV saved to {output_file}")
    return customer_tickets

def generate_statistics(tickets):
    """Generate statistics for the dashboard"""
    print("📈 Calculating statistics...")
    
    from collections import Counter
    
    stats = {
        'total_tickets': len(tickets),
        'unique_customers': len(set(t['customer'] for t in tickets if t['customer'])),
        'by_feature_area': dict(Counter(t['feature_area'] for t in tickets)),
        'by_epic': dict(Counter(t['epic'] for t in tickets)),
        'by_wave': dict(Counter(t['wave'] for t in tickets)),
        'by_source_type': dict(Counter(t['source_type'] for t in tickets)),
        'by_priority': dict(Counter(t['priority'] for t in tickets)),
        'last_updated': datetime.now().isoformat()
    }
    
    # Sort by count
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
    """Generate HTML dashboard"""
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
                    <div class="text-sm font-medium text-gray-600 mb-1">Feature Areas</div>
                    <div class="text-3xl font-bold text-gray-900">{len(stats['by_feature_area'])}</div>
                </div>
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <div class="text-sm font-medium text-gray-600 mb-1">Epics</div>
                    <div class="text-3xl font-bold text-gray-900">{len(stats['by_epic'])}</div>
                </div>
            </div>
            
            <!-- Charts -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <!-- Feature Area Chart -->
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <h2 class="text-lg font-semibold text-gray-900 mb-4">
                        Tickets by Feature Area
                    </h2>
                    <canvas id="featureAreaChart"></canvas>
                </div>
                
                <!-- Survey Wave Chart -->
                <div class="bg-white rounded-lg shadow-sm p-6">
                    <h2 class="text-lg font-semibold text-gray-900 mb-4">
                        Tickets by Survey Wave
                    </h2>
                    <canvas id="waveChart"></canvas>
                </div>
            </div>
            
            <!-- Top Epics -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-900 mb-4">
                    Top 10 Epics by Ticket Count
                </h2>
                <canvas id="epicChart" height="400"></canvas>
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
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Feature Area</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Wave</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
"""
    
    for ticket in recent_tickets:
        created_date = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00')).strftime('%b %d, %Y')
        html += f"""
                            <tr class="hover:bg-gray-50">
                                <td class="px-4 py-3">
                                    <div class="text-sm font-medium text-blue-600">{ticket['ticket_id']}</div>
                                    <div class="text-sm text-gray-500 truncate max-w-xs">{ticket['title']}</div>
                                </td>
                                <td class="px-4 py-3 text-sm text-gray-900">{ticket['customer'] or 'Unknown'}</td>
                                <td class="px-4 py-3 text-sm text-gray-900">{ticket['feature_area']}</td>
                                <td class="px-4 py-3 text-sm text-gray-900">{ticket['wave']}</td>
                                <td class="px-4 py-3 text-sm text-gray-500">{created_date}</td>
                            </tr>
"""
    
    # Prepare chart data
    feature_areas = list(stats['by_feature_area'].keys())
    feature_counts = list(stats['by_feature_area'].values())
    
    wave_labels = list(stats['by_wave'].keys())
    wave_counts = list(stats['by_wave'].values())
    
    top_epics = dict(list(stats['by_epic'].items())[:10])
    epic_labels = list(top_epics.keys())
    epic_counts = list(top_epics.values())
    
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
                <a href="data/customer_feedback.csv" 
                   download
                   class="inline-block px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium">
                    📥 Download CSV
                </a>
                <a href="data/statistics.json" 
                   download
                   class="inline-block ml-4 px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium">
                    📊 Download Statistics (JSON)
                </a>
            </div>
        </div>
    </div>
    
    <script>
        // Feature Area Chart
        const featureCtx = document.getElementById('featureAreaChart').getContext('2d');
        new Chart(featureCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(feature_areas)},
                datasets: [{{
                    label: 'Ticket Count',
                    data: {json.dumps(feature_counts)},
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
        
        // Wave Chart
        const waveCtx = document.getElementById('waveChart').getContext('2d');
        new Chart(waveCtx, {{
            type: 'pie',
            data: {{
                labels: {json.dumps(wave_labels)},
                datasets: [{{
                    data: {json.dumps(wave_counts)},
                    backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444']
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true
            }}
        }});
        
        // Epic Chart
        const epicCtx = document.getElementById('epicChart').getContext('2d');
        new Chart(epicCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(epic_labels)},
                datasets: [{{
                    label: 'Ticket Count',
                    data: {json.dumps(epic_counts)},
                    backgroundColor: '#10b981'
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }}
                }},
                scales: {{
                    x: {{ beginAtZero: true }}
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
    raw_tickets = fetch_linear_data()
    print(f"✅ Fetched {len(raw_tickets)} tickets from Linear")
    
    # Parse tickets
    parsed_tickets = [parse_ticket(t) for t in raw_tickets]
    
    # Filter to only tickets with customer feedback
    customer_tickets = [t for t in parsed_tickets if t['has_customer_feedback']]
    print(f"✅ Found {len(customer_tickets)} tickets with customer feedback")
    
    # Generate outputs
    generate_csv(customer_tickets)
    stats = generate_statistics(customer_tickets)
    generate_html_dashboard(customer_tickets, stats)
    
    print("=" * 60)
    print("✨ Dashboard generation complete!")
    print(f"📊 Total tickets analyzed: {stats['total_tickets']}")
    print(f"👥 Unique customers: {stats['unique_customers']}")
    print(f"📁 Feature areas: {len(stats['by_feature_area'])}")

if __name__ == '__main__':
    main()
