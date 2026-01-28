import requests
import json
import time
import urllib.parse
import os
from datetime import datetime, timedelta

from config.config import TRAKT_CLIENT_ID, TRAKT_CLIENT_SECRET, TMDB_API_KEY, DISCORD_WEBHOOK_URL

# Constants (DO NOT EDIT)
EMBED_COLORS = {'movie': 0xffa500, 'show': 0x67B7D1}
TMDB_URLS = {'movie': 'https://api.themoviedb.org/3/movie/', 'show': 'https://api.themoviedb.org/3/tv/'}
TMDB_IMAGE_URL = 'https://image.tmdb.org/t/p/w500/'
RANKING_EMOJIS = {1: ":first_place:", 2: ":second_place:", 3: ":third_place:"}
DISCORD_THUMBNAIL = "https://i.postimg.cc/KvSTwcQ0/undefined-Imgur.png"
TRAKT_ICON = "https://i.imgur.com/tvnkxAY.png"
TRAKT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

# Setup config folder
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
os.makedirs(CONFIG_DIR, exist_ok=True)
TOKEN_FILE = os.path.join(CONFIG_DIR, "trakt_token.json")
trakt_token = None

def load_or_refresh_token():
    global trakt_token
    try:
        with open(TOKEN_FILE, "r") as f:
            trakt_token = json.load(f)
        if trakt_token.get("expires_at", 0) - 300 < time.time():
            refresh_token()
    except (FileNotFoundError, json.JSONDecodeError):
        request_new_token()

def save_token():
    with open(TOKEN_FILE, "w") as f:
        json.dump(trakt_token, f)

def request_new_token():
    global trakt_token
    print("ERROR: Token file missing. Please authorize at:")
    auth_url = f"https://trakt.tv/oauth/authorize?client_id={TRAKT_CLIENT_ID}&response_type=code&redirect_uri={urllib.parse.quote(TRAKT_REDIRECT_URI)}"
    print(auth_url)
    auth_code = input("Enter the code from Trakt: ")
    response = requests.post("https://trakt.tv/oauth/token", data={
        "code": auth_code,
        "client_id": TRAKT_CLIENT_ID,
        "client_secret": TRAKT_CLIENT_SECRET,
        "redirect_uri": TRAKT_REDIRECT_URI,
        "grant_type": "authorization_code"
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    trakt_token = response.json()
    save_token()

def refresh_token():
    global trakt_token
    if not trakt_token:
        print("ERROR: No token to refresh. Please authorize first.")
        request_new_token()
        return
    
    print("Refreshing Trakt token...")
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            response = requests.post("https://trakt.tv/oauth/token", data={
                "client_id": TRAKT_CLIENT_ID,
                "client_secret": TRAKT_CLIENT_SECRET,
                "refresh_token": trakt_token.get("refresh_token"),
                "grant_type": "refresh_token"
            }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                if token_data and "access_token" in token_data:
                    trakt_token = token_data
                    save_token()
                    print("Token refreshed successfully.")
                    return
                else:
                    print(f"ERROR: Invalid token response (attempt {attempt + 1}/{max_retries}): {token_data}")
            else:
                print(f"ERROR: Token refresh failed with status {response.status_code} (attempt {attempt + 1}/{max_retries}): {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"ERROR: Network error during token refresh (attempt {attempt + 1}/{max_retries}): {e}")
        
        # Retry after delay (except on last attempt)
        if attempt < max_retries - 1:
            print(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
    
    print("ERROR: Failed to refresh token after all retries. The script may not function correctly.")

def get_headers():
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID
    }
    if trakt_token and "access_token" in trakt_token:
        headers["Authorization"] = f"Bearer {trakt_token['access_token']}"
    return headers

def get_data_from_url(url):
    try:
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return sorted(response.json(), key=lambda x: x['watcher_count'], reverse=True)
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return []

def fetch_image(item_type, item_id):
    url = f'{TMDB_URLS[item_type]}{item_id}?api_key={TMDB_API_KEY}&language=en-US'
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if poster_path := data.get('poster_path'):
            return f'{TMDB_IMAGE_URL}{poster_path}'
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
    return ''

def create_embed(item_type, items, week, footer_text):
    embed = {
        "color": EMBED_COLORS[item_type],
        "fields": [],
        "thumbnail": {"url": ""},
        "image": {"url": DISCORD_THUMBNAIL},
        "author": {"name": f"Trakt: Top {item_type.capitalize()}s in Week {week}", "icon_url": TRAKT_ICON},
        "footer": {"text": footer_text}
    }

    for i, item in enumerate(items[:9]):
        image_url = fetch_image(item_type, item[item_type]['ids']['tmdb'])
        if not embed["thumbnail"]["url"] and image_url:
            embed["thumbnail"]["url"] = image_url
        embed["fields"].append({
            "name": f"{RANKING_EMOJIS.get(i + 1, '')} {item[item_type]['title']} ({item[item_type]['year']})",
            "value": f"[{item['watcher_count']:,} watchers](https://trakt.tv/{item_type}s/{item[item_type]['ids']['slug']})",
            "inline": True
        })
    return embed

def create_weekly_global_embed():
    load_or_refresh_token()
    previous_week_start = datetime.now() - timedelta(days=7)
    previous_week_end = datetime.now() - timedelta(days=1)
    footer_text = f"{previous_week_start.strftime('%a %b %d %Y')} to {previous_week_end.strftime('%a %b %d %Y')}"
    week = previous_week_start.isocalendar()[1]

    movies = get_data_from_url('https://api.trakt.tv/movies/watched/period=weekly')
    shows = get_data_from_url('https://api.trakt.tv/shows/watched/period=weekly')

    movie_embed = create_embed('movie', movies, week, footer_text)
    show_embed = create_embed('show', shows, week, footer_text)

    return {"embeds": [movie_embed, show_embed]}

def send_to_discord(embed_data):
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=embed_data)
        response.raise_for_status()
        print("Successfully sent to Discord webhook")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send to Discord webhook: {e}")

if __name__ == "__main__":
    embed_data = create_weekly_global_embed()
    send_to_discord(embed_data)