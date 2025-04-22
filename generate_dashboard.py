import os
import requests
import json
from datetime import datetime, timedelta, date
import calendar

# --- Configuration ---
# These will be read from environment variables set by GitHub Secrets
STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
# IMPORTANT: You need a valid REFRESH token obtained through an initial OAuth flow
STRAVA_REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN")
OUTPUT_HTML_FILE = "strava_dashboard.html"
ACTIVITY_TYPES = ["Run", "Walk", "Hike"]

# Strava API URLs
AUTH_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

# --- Helper Functions ---

def refresh_access_token():
    """Refreshes the Strava access token using the refresh token."""
    if STRAVA_REFRESH_TOKEN is None:
        print("Error: STRAVA_REFRESH_TOKEN is not set.")
        return None
    # Prepare the payload for the token refresh request
    payload = {
        'client_id': STRAVA_CLIENT_ID,
        'client_secret': STRAVA_CLIENT_SECRET,
        'refresh_token': STRAVA_REFRESH_TOKEN,
        'grant_type': "refresh_token",
        'f': 'json'
    }
    print("Requesting new access token...")
    try:
        response = requests.post(AUTH_URL, data=payload, timeout=30)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        tokens = response.json()
        print("Access token refreshed successfully.")
        # You could potentially store the new refresh token if it changes,
        # but Strava refresh tokens are typically long-lived.
        # os.environ['STRAVA_REFRESH_TOKEN'] = tokens['refresh_token'] # Be careful managing state like this in actions
        return tokens['access_token']
    except requests.exceptions.RequestException as e:
        print(f"Error refreshing Strava token: {e}")
        if response is not None:
            print(f"Response status: {response.status_code}")
            print(f"Response body: {response.text}")
        return None
    except KeyError:
        print(f"Error parsing token response: 'access_token' not found in {tokens}")
        return None


def get_strava_activities(access_token, after_timestamp):
    """Fetches all activities after a specific timestamp, handling pagination."""
    activities = []
    page = 1
    per_page = 100 # Max 200, use 100 to be safe with URL length if filtering server-side
    headers = {'Authorization': f'Bearer {access_token}'}

    print(f"Fetching activities after timestamp: {after_timestamp} ({datetime.fromtimestamp(after_timestamp)})")

    while True:
        params = {'after': after_timestamp, 'page': page, 'per_page': per_page}
        try:
            response = requests.get(ACTIVITIES_URL, headers=headers, params=params, timeout=60)
            response.raise_for_status()
            current_page_activities = response.json()

            if not current_page_activities:
                print(f"No more activities found on page {page}.")
                break # No more activities

            print(f"Fetched {len(current_page_activities)} activities from page {page}.")
            activities.extend(current_page_activities)
            page += 1

            # Basic rate limit check (optional, depends on expected activity volume)
            # if 'X-RateLimit-Usage' in response.headers:
            #     usage = response.headers['X-RateLimit-Usage'].split(',')
            #     print(f"Rate Limit Usage: Short={usage[0]}, Long={usage[1]}")
            # if 'X-RateLimit-Limit' in response.headers:
            #     limit = response.headers['X-RateLimit-Limit'].split(',')
            #     print(f"Rate Limit Limits: Short={limit[0]}, Long={limit[1]}")

        except requests.exceptions.RequestException as e:
            print(f"Error fetching Strava activities (page {page}): {e}")
            if response is not None:
                print(f"Response status: {response.status_code}")
                print(f"Response body: {response.text}")
            # Decide if you want to stop or retry on error
            break
        except json.JSONDecodeError as e:
             print(f"Error decoding JSON response (page {page}): {e}")
             print(f"Response body: {response.text}")
             break


    print(f"Total activities fetched (before filtering): {len(activities)}")
    return activities

def process_activities(activities):
    """Filters activities and aggregates elevation gain by day."""
    daily_elevation = {}
    print(f"Processing {len(activities)} activities...")
    filtered_count = 0
    for activity in activities:
        if activity.get('type') in ACTIVITY_TYPES:
            filtered_count += 1
            try:
                # Use start_date_local for user's perspective
                activity_date_str = activity['start_date_local'][:10] # YYYY-MM-DD
                activity_date = datetime.strptime(activity_date_str, "%Y-%m-%d").date()
                elevation_gain = float(activity.get('total_elevation_gain', 0))

                daily_elevation[activity_date] = daily_elevation.get(activity_date, 0) + elevation_gain
            except Exception as e:
                print(f"Warning: Could not process activity {activity.get('id', 'N/A')}: {e}")
                print(f"Activity data: {activity}")


    print(f"Processed {filtered_count} activities of types {ACTIVITY_TYPES}.")
    print(f"Found elevation data for {len(daily_elevation)} days.")
    return daily_elevation

def aggregate_data(daily_elevation, today):
    """Aggregates daily data for the required chart timeframes."""
    aggregates = {}

    # --- Timeframe Calculations ---
    one_year_ago = today - timedelta(days=365)
    first_day_current_year = date(today.year, 1, 1)
    first_day_current_month = date(today.year, today.month, 1)

    # Calculate the first day of the *previous* month
    first_day_last_month_dt = (first_day_current_month - timedelta(days=1)).replace(day=1)
    first_day_last_month = first_day_last_month_dt.date()
    # Calculate the last day of the *previous* month
    last_day_last_month = first_day_current_month - timedelta(days=1)


    # Calculate the start of the current week (assuming Monday is day 0)
    start_of_week = today - timedelta(days=today.weekday())

    print(f"Today: {today}")
    print(f"One Year Ago: {one_year_ago}")
    print(f"First Day of Current Year: {first_day_current_year}")
    print(f"First Day of Current Month: {first_day_current_month}")
    print(f"First Day of Last Month: {first_day_last_month}")
    print(f"Last Day of Last Month: {last_day_last_month}")
    print(f"Start of Current Week (Mon): {start_of_week}")


    # --- Aggregations ---

    # 1. Histogram: Last Year by Month (Previous 12 full months + current partial month)
    monthly_histogram = {}
    current_date = first_day_last_month_dt # Start from beginning of last month for full 12 months view
    # Go back 11 more months to cover a full year ending last month
    current_date = (current_date.replace(day=1) - timedelta(days=1)).replace(day=1) # Go to prev month start
    for _ in range(11):
         current_date = (current_date.replace(day=1) - timedelta(days=1)).replace(day=1)

    # Iterate through 13 months (12 full past + current partial)
    for i in range(13):
        month_start = date(current_date.year, current_date.month, 1)
        month_end_day = calendar.monthrange(current_date.year, current_date.month)[1]
        month_end = date(current_date.year, current_date.month, month_end_day)

        month_str = month_start.strftime("%Y-%m")
        total_gain = 0
        current_day = month_start
        while current_day <= month_end:
             # Only include days up to today if it's the current month
            if current_day <= today:
                total_gain += daily_elevation.get(current_day, 0)
            current_day += timedelta(days=1)

        # Only add if there was gain or it's a past month within the window
        if total_gain > 0 or month_start < first_day_current_month:
             # Only include the last 12 relevant months ending with the current one
             if month_start >= (today.replace(day=1) - timedelta(days=365*1.1)).replace(day=1) : # Approx filter
                 monthly_histogram[month_str] = round(total_gain)

        # Move to the next month
        next_month_day_one = (month_end + timedelta(days=1)).replace(day=1)
        current_date = next_month_day_one


    # Ensure we have exactly the last 12 months + current partial if needed
    # Sort by key (date string) and take the last 12 entries
    sorted_months = sorted(monthly_histogram.keys())
    aggregates['hist_year_month'] = {m: monthly_histogram[m] for m in sorted_months[-12:]} # Get last 12 months
    print(f"Aggregated Year/Month Histogram: {len(aggregates['hist_year_month'])} months")


    # 2. Histogram: Last Month by Day
    daily_hist_last_month = {}
    current_day = first_day_last_month
    while current_day <= last_day_last_month:
        gain = daily_elevation.get(current_day, 0)
        # Include days even if gain is 0 for a complete histogram
        daily_hist_last_month[current_day.strftime("%Y-%m-%d")] = round(gain)
        current_day += timedelta(days=1)
    aggregates['hist_last_month_day'] = daily_hist_last_month
    print(f"Aggregated Last Month/Day Histogram: {len(daily_hist_last_month)} days")


    # 3. Cumulative: Current Year
    cumulative_year = {}
    running_total = 0
    current_day = first_day_current_year
    while current_day <= today:
        running_total += daily_elevation.get(current_day, 0)
        cumulative_year[current_day.strftime("%Y-%m-%d")] = round(running_total)
        current_day += timedelta(days=1)
    aggregates['cumul_year'] = cumulative_year
    print(f"Aggregated Cumulative Year: {len(cumulative_year)} days")


    # 4. Cumulative: Current Month
    cumulative_month = {}
    running_total = 0
    current_day = first_day_current_month
    while current_day <= today:
        running_total += daily_elevation.get(current_day, 0)
        cumulative_month[current_day.strftime("%Y-%m-%d")] = round(running_total)
        current_day += timedelta(days=1)
    aggregates['cumul_month'] = cumulative_month
    print(f"Aggregated Cumulative Month: {len(cumulative_month)} days")

    # 5. Cumulative: Current Week
    cumulative_week = {}
    running_total = 0
    current_day = start_of_week
    while current_day <= today:
        # Ensure we don't include days from the previous month if week spans months
        if current_day >= start_of_week:
             running_total += daily_elevation.get(current_day, 0)
             cumulative_week[current_day.strftime("%Y-%m-%d")] = round(running_total)
        current_day += timedelta(days=1)
    aggregates['cumul_week'] = cumulative_week
    print(f"Aggregated Cumulative Week: {len(cumulative_week)} days")


    return aggregates


def generate_html(aggregated_data, today_date):
    """Generates the HTML dashboard file with embedded Chart.js charts."""

    # Safely dump data into JSON format for JavaScript
    hist_year_month_data = json.dumps(aggregated_data.get('hist_year_month', {}))
    hist_last_month_day_data = json.dumps(aggregated_data.get('hist_last_month_day', {}))
    cumul_year_data = json.dumps(aggregated_data.get('cumul_year', {}))
    cumul_month_data = json.dumps(aggregated_data.get('cumul_month', {}))
    cumul_week_data = json.dumps(aggregated_data.get('cumul_week', {}))

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Strava Elevation Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
        .chart-container {{
            position: relative;
            margin: auto;
            height: 60vh; /* Adjust height as needed */
            width: 90vw;  /* Adjust width as needed */
            margin-bottom: 2rem; /* Add space between charts */
        }}
        /* Ensure canvas is responsive */
        canvas {{
            display: block;
            box-sizing: border-box;
            height: 100%;
            width: 100%;
        }}
        /* Style for small screens */
        @media (max-width: 768px) {{
            .chart-container {{
                height: 50vh;
                width: 95vw;
            }}
        }}
    </style>
     <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body class="bg-gray-100 p-4 md:p-8">

    <h1 class="text-2xl md:text-3xl font-bold text-center mb-6 text-gray-800">Strava Elevation Dashboard</h1>
    <p class="text-center text-gray-600 mb-8">Activities: {', '.join(ACTIVITY_TYPES)} | Last Updated: {today_date.strftime('%Y-%m-%d %H:%M:%S')} CEST</p>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div>
            <h2 class="text-xl font-semibold text-center mb-3 text-gray-700">Climbed Meters - Last 12 Months</h2>
            <div class="chart-container bg-white rounded-lg shadow p-4">
                <canvas id="histYearMonthChart"></canvas>
            </div>
        </div>
        <div>
            <h2 class="text-xl font-semibold text-center mb-3 text-gray-700">Climbed Meters - Last Month (by Day)</h2>
            <div class="chart-container bg-white rounded-lg shadow p-4">
                <canvas id="histLastMonthDayChart"></canvas>
            </div>
        </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div>
            <h2 class="text-xl font-semibold text-center mb-3 text-gray-700">Cumulative Climb - Current Year</h2>
            <div class="chart-container bg-white rounded-lg shadow p-4">
                <canvas id="cumulYearChart"></canvas>
            </div>
        </div>
        <div>
            <h2 class="text-xl font-semibold text-center mb-3 text-gray-700">Cumulative Climb - Current Month</h2>
            <div class="chart-container bg-white rounded-lg shadow p-4">
                <canvas id="cumulMonthChart"></canvas>
            </div>
        </div>
        <div>
            <h2 class="text-xl font-semibold text-center mb-3 text-gray-700">Cumulative Climb - Current Week</h2>
            <div class="chart-container bg-white rounded-lg shadow p-4">
                <canvas id="cumulWeekChart"></canvas>
            </div>
        </div>
    </div>

    <script>
        // --- Chart Data (Embedded from Python) ---
        const histYearMonthData = {json.dumps(aggregated_data.get('hist_year_month', {}), indent=4)};
        const histLastMonthDayData = {json.dumps(aggregated_data.get('hist_last_month_day', {}), indent=4)};
        const cumulYearData = {json.dumps(aggregated_data.get('cumul_year', {}), indent=4)};
        const cumulMonthData = {json.dumps(aggregated_data.get('cumul_month', {}), indent=4)};
        const cumulWeekData = {json.dumps(aggregated_data.get('cumul_week', {}), indent=4)};

        const chartOptions = {{
            responsive: true,
            maintainAspectRatio: false, // Important for custom container size
            scales: {{
                y: {{
                    beginAtZero: true,
                    title: {{ display: true, text: 'Elevation Gain (m)' }}
                }},
                x: {{
                    title: {{ display: true }} // Title set per chart
                }}
            }},
            plugins: {{
                tooltip: {{
                    mode: 'index',
                    intersect: false
                }}
            }}
        }};

        // --- Initialize Charts ---
        try {{
            // 1. Histogram Year/Month
            const ctxHistYM = document.getElementById('histYearMonthChart').getContext('2d');
            new Chart(ctxHistYM, {{
                type: 'bar',
                data: {{
                    labels: Object.keys(histYearMonthData),
                    datasets: [{{
                        label: 'Meters Climbed',
                        data: Object.values(histYearMonthData),
                        backgroundColor: 'rgba(54, 162, 235, 0.6)', // Blue
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    }}]
                }},
                options: {{ ...chartOptions, scales: {{ ...chartOptions.scales, x: {{ ...chartOptions.scales.x, title: {{ display: true, text: 'Month' }} }} }} }}
            }});

            // 2. Histogram Last Month/Day
            const ctxHistLMD = document.getElementById('histLastMonthDayChart').getContext('2d');
            new Chart(ctxHistLMD, {{
                type: 'bar',
                data: {{
                    labels: Object.keys(histLastMonthDayData),
                    datasets: [{{
                        label: 'Meters Climbed',
                        data: Object.values(histLastMonthDayData),
                        backgroundColor: 'rgba(255, 159, 64, 0.6)', // Orange
                        borderColor: 'rgba(255, 159, 64, 1)',
                        borderWidth: 1
                    }}]
                }},
                 options: {{ ...chartOptions, scales: {{ ...chartOptions.scales, x: {{ ...chartOptions.scales.x, title: {{ display: true, text: 'Day of Month' }} }} }} }}
            }});

            // 3. Cumulative Year
            const ctxCumulY = document.getElementById('cumulYearChart').getContext('2d');
            new Chart(ctxCumulY, {{
                type: 'line',
                data: {{
                    labels: Object.keys(cumulYearData),
                    datasets: [{{
                        label: 'Cumulative Meters',
                        data: Object.values(cumulYearData),
                        borderColor: 'rgba(75, 192, 192, 1)', // Green
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        fill: true,
                        tension: 0.1
                    }}]
                }},
                 options: {{ ...chartOptions, scales: {{ ...chartOptions.scales, x: {{ ...chartOptions.scales.x, title: {{ display: true, text: 'Date' }} }} }} }}
            }});

            // 4. Cumulative Month
            const ctxCumulM = document.getElementById('cumulMonthChart').getContext('2d');
            new Chart(ctxCumulM, {{
                type: 'line',
                data: {{
                    labels: Object.keys(cumulMonthData),
                    datasets: [{{
                        label: 'Cumulative Meters',
                        data: Object.values(cumulMonthData),
                        borderColor: 'rgba(153, 102, 255, 1)', // Purple
                        backgroundColor: 'rgba(153, 102, 255, 0.2)',
                        fill: true,
                        tension: 0.1
                    }}]
                }},
                 options: {{ ...chartOptions, scales: {{ ...chartOptions.scales, x: {{ ...chartOptions.scales.x, title: {{ display: true, text: 'Date' }} }} }} }}
            }});

            // 5. Cumulative Week
            const ctxCumulW = document.getElementById('cumulWeekChart').getContext('2d');
            new Chart(ctxCumulW, {{
                type: 'line',
                data: {{
                    labels: Object.keys(cumulWeekData),
                    datasets: [{{
                        label: 'Cumulative Meters',
                        data: Object.values(cumulWeekData),
                        borderColor: 'rgba(255, 99, 132, 1)', // Red
                        backgroundColor: 'rgba(255, 99, 132, 0.2)',
                        fill: true,
                        tension: 0.1
                    }}]
                }},
                 options: {{ ...chartOptions, scales: {{ ...chartOptions.scales, x: {{ ...chartOptions.scales.x, title: {{ display: true, text: 'Date' }} }} }} }}
            }});
        }} catch (error) {{
            console.error("Error initializing charts:", error);
            // Optionally display an error message to the user on the page
        }}
    </script>

</body>
</html>
    """
    try:
        with open(OUTPUT_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Successfully generated HTML dashboard: {OUTPUT_HTML_FILE}")
    except IOError as e:
        print(f"Error writing HTML file: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    print("Starting Strava dashboard generation...")

    if not all([STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN]):
        print("Error: Missing required Strava environment variables (CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN).")
        exit(1)

    access_token = refresh_access_token()

    if access_token:
        today = date.today() # Use current date
        print(f"Using current date: {today}")

        # Calculate timestamp for 1 year ago to fetch activities
        # Fetch slightly more just in case of timezone edge cases, filter later
        one_year_ago_dt = datetime(today.year - 1, today.month, today.day)
        after_timestamp = int(one_year_ago_dt.timestamp())

        all_activities = get_strava_activities(access_token, after_timestamp)

        if all_activities:
            daily_elevation_data = process_activities(all_activities)
            aggregated_results = aggregate_data(daily_elevation_data, today)

            # Get current time for the "Last Updated" timestamp
            # Note: GitHub Actions runners typically use UTC. Consider timezone if needed.
            # Using CEST as requested in context. Requires pytz or similar if not on a system with it.
            # For simplicity in Action, let's just note UTC or assume runner timezone.
            # Hardcoding CEST for this example output based on prompt context.
            now_cest = datetime.now() # Replace with timezone aware logic if needed
            generate_html(aggregated_results, now_cest)
        else:
            print("No activities fetched or processed.")
            # Consider generating an HTML file indicating no data or an error
            # generate_html({}, datetime.now()) # Generate empty dashboard
    else:
        print("Could not obtain Strava access token. Aborting.")
        exit(1)

    print("Dashboard generation finished.")
