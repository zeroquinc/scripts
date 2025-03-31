import requests
from datetime import datetime, timedelta
import time
from collections import defaultdict

# Configuration (EDIT THIS)
TRAKT_API_KEY = "" # Trakt Client ID
TRAKT_USERNAME = "" # Trakt username (not user ID) capital sensitive
TMDB_API_KEY = ""  # TMDB API Key for posters
DISCORD_WEBHOOK_URL = "" # Discord Webhook URL
MAX_RETRIES = 3 # Number of retries for failed requests (increase if you get rate limited)
DELAY_BETWEEN_REQUESTS = 1  # seconds (increase if you get rate limited)

def get_trakt_datetime(dt):
    """Convert datetime to Trakt API format"""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')

def fetch_all_watched_history(start_date, end_date):
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_API_KEY
    }
    
    all_history = []
    page = 1
    has_more = True
    
    while has_more:
        for attempt in range(MAX_RETRIES):
            try:
                url = f"https://api.trakt.tv/users/{TRAKT_USERNAME}/history"
                params = {
                    "start_at": get_trakt_datetime(start_date),
                    "end_at": get_trakt_datetime(end_date),
                    "page": page,
                    "limit": 1000,
                    "extended": "full"  # Request full details to get runtime
                }
                
                print(f"Fetching page {page}...")
                response = requests.get(url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                
                history = response.json()
                if not history:
                    has_more = False
                    break
                
                all_history.extend(history)
                page += 1
                time.sleep(DELAY_BETWEEN_REQUESTS)
                break
                
            except requests.exceptions.RequestException as e:
                if attempt == MAX_RETRIES - 1:
                    print(f"Failed to fetch page {page} after {MAX_RETRIES} attempts: {str(e)}")
                    has_more = False
                    break
                time.sleep(DELAY_BETWEEN_REQUESTS * (attempt + 1))
    
    return all_history

def get_tmdb_poster_url(tmdb_id, media_type):
    if not tmdb_id:
        return None
    
    try:
        base_url = "https://api.themoviedb.org/3"
        endpoint = f"/{'tv' if media_type == 'show' else 'movie'}/{tmdb_id}"
        
        response = requests.get(
            base_url + endpoint,
            params={"api_key": TMDB_API_KEY},
            timeout=5
        )
        response.raise_for_status()
        
        data = response.json()
        if data.get("poster_path"):
            return f"https://image.tmdb.org/t/p/original{data['poster_path']}"
    except Exception as e:
        print(f"Error fetching TMDB poster: {str(e)}")
    
    return None

def process_watched_history(history):
    items = defaultdict(lambda: {
        'title': None,
        'count': 0,
        'total_minutes': 0,
        'type': None,
        'tmdb_id': None,
        'poster_url': None
    })
    
    for item in history:
        if item['type'] == 'episode':
            show = item['show']
            episode = item['episode']
            item_id = show['ids']['trakt']
            
            # Get runtime (fallback to show runtime if episode runtime not available)
            runtime = episode.get('runtime', show.get('runtime', 30))
            
            items[item_id]['title'] = show['title']
            items[item_id]['count'] += 1
            items[item_id]['total_minutes'] += runtime
            items[item_id]['type'] = 'show'
            items[item_id]['tmdb_id'] = show['ids'].get('tmdb')
            
        elif item['type'] == 'movie':
            movie = item['movie']
            item_id = movie['ids']['trakt']
            
            # Get movie runtime (default to 120 minutes if not available)
            runtime = movie.get('runtime', 120)
            
            items[item_id]['title'] = movie['title']
            items[item_id]['count'] += 1
            items[item_id]['total_minutes'] += runtime
            items[item_id]['type'] = 'movie'
            items[item_id]['tmdb_id'] = movie['ids'].get('tmdb')
    
    # Fetch posters for all items
    for item_id, item in items.items():
        if item['tmdb_id']:
            item['poster_url'] = get_tmdb_poster_url(item['tmdb_id'], item['type'])
            time.sleep(0.1)  # Small delay to avoid rate limiting
    
    return items

def format_duration(minutes):
    """Convert minutes to human-readable format (Xh Ym)"""
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"

def create_discord_embed(items):
    week_number = datetime.now().isocalendar()[1]
    year = datetime.now().year
    
    # Calculate total time
    total_minutes = sum(item['total_minutes'] for item in items.values())
    total_time = format_duration(total_minutes)
    
    # Find most watched item (by total minutes)
    if items:
        most_watched = max(items.values(), key=lambda x: x['total_minutes'])
        most_watched_time = format_duration(most_watched['total_minutes'])
    else:
        most_watched = None
    
    fields = []
    for item_id, item in sorted(items.items(), key=lambda x: (-x[1]['total_minutes'], x[1]['title'])):
        item_time = format_duration(item['total_minutes'])
        
        if item['type'] == 'show':
            value = f"{item['count']} episode{'s' if item['count'] > 1 else ''} - {item_time}"
        else:
            value = f"{item['count']} {'times' if item['count'] > 1 else 'time'} - {item_time}"
        
        fields.append({
            "name": item['title'],
            "value": value,
            "inline": False
        })
    
    embed = {
        "author": {
            "name": f"Trakt: Watched History for Week {week_number} of {year}",
            "icon_url": "https://i.imgur.com/7gkofW8.png"
        },
        "color": 0xFF0000,  # Red color
        "fields": fields
    }
    
    if items:
        embed["footer"] = {
            "text": f"Total watched time: {total_time} • Most watched: {most_watched['title']} ({most_watched_time})"
        }
        # Add thumbnail if most watched has a poster
        if most_watched['poster_url']:
            embed["thumbnail"] = {"url": most_watched['poster_url']}
    else:
        embed["description"] = "No items watched this week"
    
    return embed

def send_to_discord(embed):
    data = {
        "embeds": [embed]
    }
    
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        response.raise_for_status()
        print("Successfully sent to Discord!")
    except requests.exceptions.RequestException as e:
        print(f"Error sending to Discord: {str(e)}")

def main():
    print("Starting Trakt history fetch...")
    
    # Calculate date range (last 7 days including current time)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    
    print(f"Fetching history from {start_date} to {end_date}")
    
    # Fetch all history with pagination
    history = fetch_all_watched_history(start_date, end_date)
    
    if not history:
        print("No history data received or error occurred")
        return
    
    print(f"Processed {len(history)} history items")
    
    # Process the history
    items = process_watched_history(history)
    
    if not items:
        print("No items watched in the specified period")
    
    print(f"Found {len(items)} items watched")
    
    # Create Discord embed
    embed = create_discord_embed(items)
    
    # Send to Discord
    send_to_discord(embed)

if __name__ == "__main__":
    main()