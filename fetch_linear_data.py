#!/usr/bin/env python3
"""
Linear Feature Requests Dashboard Generator
Fetches data from Linear API and generates analysis + dashboard
Updated to support Project → Epic → Issue hierarchy
"""

import os
import json
import requests
from datetime import datetime, timedelta
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
query($teamId: String!, $createdAfter: DateTimeOrDuration!) {
  team(id: $teamId) {
    id
    name
    issues(first: 250, filter: { 
      state: { type: { nin: ["canceled"] } },
      createdAt: { gte: $createdAfter }
    }) {
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
        completedAt
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
    """Fetch issues from Linear API with pagination"""
    print("🔍 Fetching issues from Linear API...")
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': LINEAR_API_KEY
    }
    
    # Calculate date 12 months ago
    twelve_months_ago = datetime.now() - timedelta(days=365)
    created_after = twelve_months_ago.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    
    print(f"   📅 Filtering to tickets created after {twelve_months_ago.strftime('%Y-%m-%d')} OR in active work statuses")
    
    all_issues = []
    has_more = True
    cursor = None
    page = 1
    
    while has_more:
        # Build query with pagination
        # Fetch tickets that are either:
        # 1. Created within last 12 months, OR
        # 2. Currently in active work statuses (In Progress, Todo, In Review)
        query = """
        query($teamId: String!, $createdAfter: DateTimeOrDuration!, $after: String) {
          team(id: $teamId) {
            id
            name
            issues(first: 250, after: $after, filter: { 
              state: { type: { nin: ["canceled"] } },
              or: [
                { createdAt: { gte: $createdAfter } },
                { state: { name: { in: ["In Progress", "Todo", "In Review"] } } }
              ]
            }) {
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
                completedAt
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
              pageInfo {
                hasNextPage
                endCursor
              }
            }
          }
        }
        """
        
        variables = {
            'teamId': FEATURE_REQUESTS_TEAM_ID,
            'createdAfter': created_after
        }
        
        if cursor:
            variables['after'] = cursor
        
        payload = {
            'query': query,
            'variables': variables
        }
        
        response = requests.post(LINEAR_API_URL, json=payload, headers=headers)
        
        if response.status_code != 200:
            raise Exception(f"API request failed with status {response.status_code}: {response.text}")
        
        data = response.json()
        
        if 'errors' in data:
            raise Exception(f"GraphQL errors: {data['errors']}")
        
        issues_data = data['data']['team']['issues']
        issues = issues_data['nodes']
        page_info = issues_data['pageInfo']
        
        all_issues.extend(issues)
        print(f"   📄 Fetched page {page}: {len(issues)} issues (total so far: {len(all_issues)})")
        
        has_more = page_info['hasNextPage']
        cursor = page_info['endCursor']
        page += 1
        
        # Safety limit to prevent infinite loops
        if page > 20:
            print(f"   ⚠️  Reached pagination safety limit of 20 pages")
            break
    
    # Filter out issues that were converted to projects
    filtered_issues = [
        issue for issue in all_issues
        if not ('converted to project' in issue['title'].lower() or
                (issue.get('description') and 'converted to project' in issue['description'].lower()))
    ]
    
    print(f"✅ Found {len(all_issues)} issues total ({len(all_issues) - len(filtered_issues)} converted epics filtered out)")
    return filtered_issues

def get_source_label(labels):
    """Extract source label from ticket labels"""
    source_labels = {'zendesk', 'csat', 'sales', 'partner success', 'uxr', 'other', 'unlabeled'}
    
    if not labels:
        return 'unlabeled'
    
    label_names = [label['name'].lower() for label in labels]
    
    # Debug: print labels for troubleshooting
    # print(f"      Labels found: {label_names}")
    
    for label in label_names:
        if 'zendesk' in label:
            return 'zendesk'
        elif 'csat' in label:
            return 'CSAT'
        elif 'sales' in label:
            return 'sales'
        elif 'partner success' in label or 'partner-success' in label:
            return 'partner success'
        elif 'uxr' in label:
            return 'UXR'
        elif any(keyword in label for keyword in ['email', 'phone', 'slack', 'in person', 'in-person']):
            return 'other'
    
    return 'unlabeled'

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
            feature_area = 'Thermals & Comfort'
        elif 'schedule' in parent_lower:
            feature_area = 'Schedules'
        elif 'app' in parent_lower and 'ux' in parent_lower:
            feature_area = 'All things App'
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
    
    # Get source label
    source_label = get_source_label(ticket.get('labels', {}).get('nodes', []))
    
    # Get priority value (0-4)
    priority_value = ticket.get('priority', 0)
    
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
        'source_label': source_label,
        'priority': ticket.get('priorityLabel', 'No Priority'),
        'priority_value': priority_value,
        'quote': quote[:500] if quote else '',  # Truncate long quotes
        'status': ticket['state']['name'],
        'state_type': ticket['state']['type'],
        'created_at': ticket['createdAt'],
        'updated_at': ticket['updatedAt'],
        'completed_at': ticket.get('completedAt'),
        'has_customer_feedback': customer is not None,
        'url': f"https://linear.app/quiltair/issue/{ticket['identifier']}"
    }

def generate_csv(tickets, output_file='data/customer_feedback.csv'):
    """Generate CSV file with ALL parsed ticket data"""
    print(f"📊 Generating CSV with {len(tickets)} tickets...")
    
    os.makedirs('data', exist_ok=True)
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'ticket_id', 'title', 'project', 'epic', 'epic_id', 'feature_area', 
            'customer', 'wave', 'source_type', 'source_detail', 'source_label', 'priority', 
            'quote', 'status', 'created_at', 'updated_at', 'url'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for ticket in tickets:
            # Remove fields not needed in CSV
            csv_ticket = {k: v for k, v in ticket.items() 
                         if k in fieldnames}
            writer.writerow(csv_ticket)
    
    print(f"✅ CSV saved to {output_file}")
    return tickets

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
                'url': t['url'],
                'createdAt': t['created_at'],
                'updatedAt': t['updated_at'],
                'completedAt': t.get('completed_at'),
                'customer': t['customer'],
                'wave': t['wave'],
                'project': t['project'],
                'featureArea': t['feature_area'],
                'sourceLabel': t['source_label'],
                'priority': t['priority'],
                'priorityValue': t['priority_value'],
                'state': t['status'],
                'stateType': t['state_type']
            }
            for t in tickets
        ]
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ JSON data saved to {output_file}")

def generate_statistics(all_tickets):
    """Generate statistics for the dashboard - uses ALL tickets for Section 1"""
    print("📈 Calculating statistics...")
    
    from collections import Counter
    
    # Get customer tickets for customer-specific stats
    customer_tickets = [t for t in all_tickets if t['has_customer_feedback']]
    
    stats = {
        'total_tickets': len(customer_tickets),
        'unique_customers': len(set(t['customer'] for t in customer_tickets if t['customer'])),
        # Use ALL tickets for feature area (Section 1 needs this)
        'by_feature_area': dict(Counter(t['feature_area'] for t in all_tickets)),
        'by_source_label': dict(Counter(t['source_label'] for t in customer_tickets)),
        'by_wave': dict(Counter(t['wave'] for t in customer_tickets if t['wave'])),
        'by_source_type': dict(Counter(t['source_type'] for t in customer_tickets)),
        'by_priority': dict(Counter(t['priority'] for t in customer_tickets)),
        'last_updated': datetime.now().isoformat()
    }
    
    # Sort by count
    stats['by_feature_area'] = dict(sorted(stats['by_feature_area'].items(), 
                                           key=lambda x: x[1], reverse=True))
    
    return stats

def generate_html_dashboard(all_tickets, stats):
    """Generate HTML dashboard with improved layout
    
    Section 1 (Trends): Uses all tickets to capture epics and full feature area coverage
    Section 2 (Work in Queue): Uses all tickets to show current work
    Section 3 (Recent Tickets): Uses all tickets to show recently created tickets
    """
    print("🎨 Generating HTML dashboard...")
    
    # Separate customer tickets for Section 2
    customer_tickets = [t for t in all_tickets if t['has_customer_feedback']]
    
    # Section 2: Filter tickets for Work in Queue (use ALL tickets, not just customer feedback)
    # Include: In Progress, Todo, In Review, and Done (if completed within last 7 days)
    active_statuses = {'In Progress', 'Todo', 'In Review'}
    seven_days_ago = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).replace(tzinfo=None) - timedelta(days=7)
    
    priority_tickets = []
    for ticket in all_tickets:
        status = ticket['status']
        
        # Include active statuses
        if status in active_statuses:
            priority_tickets.append(ticket)
        # Include Done only if completed within last 7 days
        elif status == 'Done' and ticket.get('completed_at'):
            try:
                completed_date = datetime.fromisoformat(ticket['completed_at'].replace('Z', '+00:00')).replace(tzinfo=None)
                if completed_date >= seven_days_ago:
                    priority_tickets.append(ticket)
            except (ValueError, TypeError):
                # Skip if date parsing fails
                pass
    
    # Sort priority tickets by status order, then by updated date
    status_order = {'In Progress': 0, 'Todo': 1, 'In Review': 2, 'Done': 3}
    priority_tickets.sort(
        key=lambda x: (
            status_order.get(x['status'], 999),
            -datetime.fromisoformat(x['updated_at'].replace('Z', '+00:00')).timestamp()
        )
    )
    
    # Section 3: Sort ALL tickets by creation date (newest first) for Recent Tickets
    recent_tickets = sorted(all_tickets, key=lambda x: x['created_at'], reverse=True)[:10]
    
    print(f"📋 Sections generated: Work in Queue ({len(priority_tickets)} tickets), Recent Tickets ({len(recent_tickets)} tickets)")
    
    # Get all feature areas for the chart
    status_order = {'In Progress': 0, 'Todo': 1, 'In Review': 2, 'Done': 3}
    priority_tickets.sort(
        key=lambda x: (
            status_order.get(x['status'], 999),
            -datetime.fromisoformat(x['updated_at'].replace('Z', '+00:00')).timestamp()
        )
    )
    
    # Get all feature areas for the chart
    feature_areas = list(stats['by_feature_area'].keys())
    feature_counts = list(stats['by_feature_area'].values())
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quilt Customer Feedback Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        .priority-icon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: 600;
            color: #6b7280;
            font-family: monospace;
        }}
        .priority-urgent {{
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 3px;
        }}
    </style>
</head>
<body class="bg-gray-50">
    <div class="min-h-screen p-6">
        <div class="max-w-7xl mx-auto">
            <!-- Header -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h1 class="text-3xl font-bold text-gray-900 mb-2">
                    Quilt Customer Feedback Dashboard
                </h1>
                <p class="text-gray-600">
                    Automated ticket analysis from Quilt's Feature Requests team in Linear
                </p>
                <p class="text-sm text-gray-500 mt-2">
                    Last updated: {datetime.fromisoformat(stats['last_updated'].replace('Z', '+00:00')).strftime('%B %d, %Y at %I:%M %p UTC')}
                </p>
            </div>
            
            <!-- Summary Stats -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
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
            </div>
            
            <!-- Section 1: Trends -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-900 mb-4">
                    Feedback Trends
                </h2>
                
                <!-- Filters -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Time Period</label>
                        <select id="timeFilter" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500">
                            <option value="all">All time</option>
                            <option value="30" selected>Last 30 days</option>
                            <option value="60">Last 60 days</option>
                            <option value="90">Last 90 days</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Source</label>
                        <select id="sourceFilter" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500">
                            <option value="all" selected>All sources</option>
                            <option value="zendesk">Zendesk</option>
                            <option value="CSAT">CSAT</option>
                            <option value="sales">Sales</option>
                            <option value="partner success">Partner Success</option>
                            <option value="UXR">UXR</option>
                            <option value="other">Other</option>
                            <option value="unlabeled">Unlabeled</option>
                        </select>
                    </div>
                </div>
                
                <!-- Horizontal Bar Chart -->
                <div style="height: 500px;">
                    <canvas id="featureAreaChart"></canvas>
                </div>
            </div>
            
            <!-- Section 2: Work in Queue (formerly Section 3) -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-900 mb-4">
                    Work in Queue
                </h2>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead>
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Title</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Project</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Priority</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
"""
    
    for ticket in priority_tickets:
        # Priority icon
        priority_html = ''
        if ticket['priority'] == 'Urgent':
            priority_html = '<span class="priority-icon priority-urgent">!</span>'
        elif ticket['priority'] == 'High':
            priority_html = '<span class="priority-icon">▮▮▮</span>'
        elif ticket['priority'] == 'Medium':
            priority_html = '<span class="priority-icon">▮▮▯</span>'
        elif ticket['priority'] == 'Low':
            priority_html = '<span class="priority-icon">▮▯▯</span>'
        else:
            priority_html = '<span class="priority-icon">---</span>'
        
        # Status badge color
        status_color = 'bg-blue-100 text-blue-800'
        if ticket['status'] == 'Done':
            status_color = 'bg-green-100 text-green-800'
        elif ticket['status'] == 'In Progress':
            status_color = 'bg-yellow-100 text-yellow-800'
        elif ticket['status'] == 'In Review':
            status_color = 'bg-purple-100 text-purple-800'
        
        html += f"""
                            <tr class="hover:bg-gray-50">
                                <td class="px-4 py-3">
                                    <a href="{ticket['url']}" target="_blank" class="text-sm font-medium text-blue-600 hover:underline">
                                        {ticket['ticket_id']}
                                    </a>
                                    <div class="text-sm text-gray-900 truncate max-w-md">{ticket['title']}</div>
                                </td>
                                <td class="px-4 py-3 text-sm text-gray-700">{ticket['project']}</td>
                                <td class="px-4 py-3">
                                    <span class="px-2 py-1 text-xs font-medium rounded bg-gray-100 text-gray-700">
                                        {ticket['source_label']}
                                    </span>
                                </td>
                                <td class="px-4 py-3">{priority_html}</td>
                                <td class="px-4 py-3">
                                    <span class="px-2 py-1 text-xs font-medium rounded {status_color}">
                                        {ticket['status']}
                                    </span>
                                </td>
                            </tr>
"""
    
    html += """
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- Section 3: Recent Tickets (formerly Section 2) -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-900 mb-4">
                    Recent Tickets
                </h2>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead>
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Title</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Project</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Priority</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
"""
    
    for ticket in recent_tickets:
        created_date = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00')).strftime('%b %d, %Y')
        
        # Priority icon
        priority_html = ''
        if ticket['priority'] == 'Urgent':
            priority_html = '<span class="priority-icon priority-urgent">!</span>'
        elif ticket['priority'] == 'High':
            priority_html = '<span class="priority-icon">▮▮▮</span>'
        elif ticket['priority'] == 'Medium':
            priority_html = '<span class="priority-icon">▮▮▯</span>'
        elif ticket['priority'] == 'Low':
            priority_html = '<span class="priority-icon">▮▯▯</span>'
        else:
            priority_html = '<span class="priority-icon">---</span>'
        
        html += f"""
                            <tr class="hover:bg-gray-50">
                                <td class="px-4 py-3">
                                    <a href="{ticket['url']}" target="_blank" class="text-sm font-medium text-blue-600 hover:underline">
                                        {ticket['ticket_id']}
                                    </a>
                                    <div class="text-sm text-gray-900 truncate max-w-md">{ticket['title']}</div>
                                </td>
                                <td class="px-4 py-3 text-sm text-gray-700">{ticket['project']}</td>
                                <td class="px-4 py-3">
                                    <span class="px-2 py-1 text-xs font-medium rounded bg-gray-100 text-gray-700">
                                        {ticket['source_label']}
                                    </span>
                                </td>
                                <td class="px-4 py-3 text-sm text-gray-500">{created_date}</td>
                                <td class="px-4 py-3">{priority_html}</td>
                                <td class="px-4 py-3 text-sm text-gray-700">{ticket['status']}</td>
                            </tr>
"""
    
    # Prepare chart data
    feature_areas = list(stats['by_feature_area'].keys())
    feature_counts = list(stats['by_feature_area'].values())
    
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
                        📥 Download CSV (All Tickets)
                    </a>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Load full data for filtering
        let allIssues = [];
        
        fetch('data.json')
            .then(response => response.json())
            .then(data => {{
                allIssues = data.issues;
                updateChart();
            }});
        
        let featureChart = null;
        
        function updateChart() {{
            const timeFilter = document.getElementById('timeFilter').value;
            const sourceFilter = document.getElementById('sourceFilter').value;
            
            // Filter issues based on selections
            let filteredIssues = allIssues.filter(issue => {{
                // Time filter
                if (timeFilter !== 'all') {{
                    const daysAgo = parseInt(timeFilter);
                    const cutoffDate = new Date();
                    cutoffDate.setDate(cutoffDate.getDate() - daysAgo);
                    const createdDate = new Date(issue.createdAt);
                    if (createdDate < cutoffDate) return false;
                }}
                
                // Source filter
                if (sourceFilter !== 'all') {{
                    if (issue.sourceLabel !== sourceFilter) return false;
                }}
                
                return true;
            }});
            
            // Count by feature area
            const featureAreaCounts = {{}};
            filteredIssues.forEach(issue => {{
                const area = issue.featureArea || 'Unknown';
                featureAreaCounts[area] = (featureAreaCounts[area] || 0) + 1;
            }});
            
            // Sort by count descending
            const sortedAreas = Object.entries(featureAreaCounts)
                .sort((a, b) => b[1] - a[1]);
            
            const labels = sortedAreas.map(([area, _]) => area);
            const counts = sortedAreas.map(([_, count]) => count);
            
            // Update or create chart
            const ctx = document.getElementById('featureAreaChart').getContext('2d');
            
            if (featureChart) {{
                featureChart.destroy();
            }}
            
            featureChart = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Ticket Count',
                        data: counts,
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
                        x: {{ 
                            beginAtZero: true,
                            ticks: {{
                                stepSize: 1
                            }}
                        }}
                    }}
                }}
            }});
        }}
        
        // Add event listeners
        document.getElementById('timeFilter').addEventListener('change', updateChart);
        document.getElementById('sourceFilter').addEventListener('change', updateChart);
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
    generate_csv(parsed_tickets)  # Include all tickets in CSV
    generate_json(parsed_tickets, projects)  # Keep JSON for dashboard filtering (not exposed to user)
    stats = generate_statistics(parsed_tickets)  # Pass all tickets for Section 1 stats
    generate_html_dashboard(parsed_tickets, stats)  # Pass all tickets for full dashboard
    
    print("=" * 60)
    print("✨ Dashboard generation complete!")
    print(f"📊 Total tickets analyzed: {stats['total_tickets']}")
    print(f"👥 Unique customers: {stats['unique_customers']}")
    print(f"📁 Feature areas: {len(stats['by_feature_area'])}")

if __name__ == '__main__':
    main()
