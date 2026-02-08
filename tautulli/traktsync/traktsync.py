import json
import time
import configparser
import sys
import requests
import urllib.parse
from datetime import datetime, timezone
import argparse
import os

"""
This script is used to sync watched content from Tautulli to Trakt. It supports double plays.

In Tautulli, go to Settings > Notification Agents > Add a new notification agent > Script -> Select tautulli_to_trakt.py
Triggers -> Check Watched
Conditions -> "Username" is "Your Tautulli username" (optional if you only want to sync your own plays)
Arguments -> Watched -> Script Arguments -> --contentType {media_type} <movie>--imdbId {imdb_id}</movie><episode>--tmdbId {themoviedb_id} --season_num {season_num} --episode_num {episode_num}</episode>

Run the script once and it will create a config.ini file.
Fill in the missing values in the config.ini file. The Discord webhook URL is optional.
Run the script again, you will need to authorize the script to access your Trakt account. 
When authorized, the notification agent in Tautulli will work and will automaticly refresh your token.

Optionally test the script at "Test Notifications" and fill these as script arguments: --contentType movie --imdbId tt0241527
It should mark "Harry Potter and the Sorcerer's Stone" as watched on Trakt.
"""

# Setup config folder
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
os.makedirs(CONFIG_DIR, exist_ok=True)

# Constants
TOKEN_FILE = os.path.join(CONFIG_DIR, "trakt_token.json")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")
DEDUPE_FILE = os.path.join(CONFIG_DIR, "trakt_dedupe.json")
DEDUPE_WINDOW_SECONDS = 60 * 60
TRAKT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
trakt_token = None

# Default configuration values
DEFAULT_CONFIG = {
    "Discord": {
        "webhook_url": ""
    },
    "Trakt": {
        "client_id": "",
        "client_secret": ""
    }
}

def create_default_config():
    if not os.path.exists(CONFIG_FILE):
        print("Config file not found. Creating default config.ini...")
        config = configparser.ConfigParser()
        for section, values in DEFAULT_CONFIG.items():
            config[section] = values
        with open(CONFIG_FILE, "w") as f:
            config.write(f)
        print(f"Default config.ini created. Please fill in the missing values in {CONFIG_FILE}.")
        sys.exit(1)

create_default_config()
config = configparser.ConfigParser()
config.read(CONFIG_FILE)

TRAKT_CONFIG = config["Trakt"]
DISCORD_CONFIG = config["Discord"]

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
    auth_url = f"https://trakt.tv/oauth/authorize?client_id={TRAKT_CONFIG['client_id']}&response_type=code&redirect_uri={urllib.parse.quote(TRAKT_REDIRECT_URI)}"
    print(auth_url)
    auth_code = input("Enter the code from Trakt: ")
    response = requests.post("https://trakt.tv/oauth/token", data={
        "code": auth_code,
        "client_id": TRAKT_CONFIG["client_id"],
        "client_secret": TRAKT_CONFIG["client_secret"],
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
    max_retries = 5  # Increased from 3 to 5 for DNS issues
    base_delay = 3  # Increased base delay
    
    for attempt in range(max_retries):
        try:
            response = requests.post("https://trakt.tv/oauth/token", data={
                "client_id": TRAKT_CONFIG["client_id"],
                "client_secret": TRAKT_CONFIG["client_secret"],
                "refresh_token": trakt_token.get("refresh_token"),
                "grant_type": "refresh_token"
            }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
            
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
            error_str = str(e)
            if "Failed to resolve" in error_str or "NameResolutionError" in error_str:
                print(f"ERROR: DNS resolution failed (attempt {attempt + 1}/{max_retries}): Network may be temporarily unavailable")
            else:
                print(f"ERROR: Network error during token refresh (attempt {attempt + 1}/{max_retries}): {e}")
        
        # Retry with exponential backoff (except on last attempt)
        if attempt < max_retries - 1:
            retry_delay = base_delay * (2 ** attempt)  # Exponential backoff: 3s, 6s, 12s, 24s
            print(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
    
    print("ERROR: Failed to refresh token after all retries. The script may not function correctly.")

def get_headers(auth=True):
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CONFIG["client_id"]
    }
    if auth and trakt_token and "access_token" in trakt_token:
        headers["Authorization"] = f"Bearer {trakt_token['access_token']}"
    return headers

def trakt_request(endpoint, params=None, max_retries=5):
    """Make a request to Trakt API with retry logic for network errors."""
    base_delay = 3
    
    for attempt in range(max_retries):
        try:
            response = requests.get(
                f"https://api.trakt.tv/{endpoint}", 
                headers=get_headers(), 
                params=params,
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
            else:
                print(f"WARNING: Trakt API returned status {response.status_code} for {endpoint}")
                if response.status_code >= 500:  # Server errors, retry
                    if attempt < max_retries - 1:
                        retry_delay = base_delay * (2 ** attempt)
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
                return None
        except requests.exceptions.RequestException as e:
            error_str = str(e)
            if "Failed to resolve" in error_str or "NameResolutionError" in error_str:
                print(f"ERROR: DNS resolution failed for {endpoint} (attempt {attempt + 1}/{max_retries})")
            else:
                print(f"ERROR: Network error for {endpoint} (attempt {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                retry_delay = base_delay * (2 ** attempt)
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                return None
    
    return None

def get_show(tmdb_id):
    result = trakt_request(f"search/tmdb/{tmdb_id}?type=show")
    if result and len(result) > 0 and "show" in result[0]:
        return result[0]["show"]
    print(f"ERROR: Could not find show with TMDB ID {tmdb_id}")
    return None

def get_episode(show, season_num, episode_num):
    return trakt_request(f"shows/{show['ids']['slug']}/seasons/{season_num}/episodes/{episode_num}")

def get_current_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def send_discord_webhook(title, url=None, poster_url=None):
    discord_webhook_url = DISCORD_CONFIG.get("webhook_url", "")
    if not discord_webhook_url:
        print("WARNING: Discord webhook URL not configured. Skipping notification.")
        return

    description = f"Marked [{title}]({url}) as watched on Trakt." if url else f"Marked {title} as watched on Trakt."

    embed = {
        "description": description,
        "color": 16711680
    }

    if poster_url:
        embed["thumbnail"] = {"url": poster_url}

    payload = {"embeds": [embed]}
    response = requests.post(discord_webhook_url, json=payload)

    if response.status_code == 204:
        print("Discord notification sent successfully.")
    else:
        print(f"ERROR: Discord notification failed. Status: {response.status_code}, Response: {response.text}")

def load_dedupe_cache():
    try:
        with open(DEDUPE_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {}

def save_dedupe_cache(cache):
    with open(DEDUPE_FILE, "w") as f:
        json.dump(cache, f)

def is_recent_duplicate(cache_key, now_ts):
    cache = load_dedupe_cache()
    last_ts = cache.get(cache_key)
    if last_ts and (now_ts - last_ts) < DEDUPE_WINDOW_SECONDS:
        return True

    # Prune stale entries and update cache
    cutoff = now_ts - (DEDUPE_WINDOW_SECONDS * 2)
    cache = {k: v for k, v in cache.items() if v >= cutoff}
    cache[cache_key] = now_ts
    save_dedupe_cache(cache)
    return False

def mark_as_watched(media_type, imdb_id=None, tmdb_id=None, season_num=None, episode_num=None, poster_url=None):
    try:
        now_ts = time.time()
        if media_type == "movie" and imdb_id:
            cache_key = f"movie:{imdb_id}"
        elif media_type == "episode" and tmdb_id and season_num is not None and episode_num is not None:
            cache_key = f"episode:{tmdb_id}:{season_num}:{episode_num}"
        else:
            cache_key = None

        if cache_key and is_recent_duplicate(cache_key, now_ts):
            print("Skipping duplicate play within dedupe window.")
            return

        load_or_refresh_token()
        watched_at = get_current_timestamp()
        trakt_data = {"movies": [], "episodes": []}
        title = ""
        trakt_url = ""

        if media_type == "movie" and imdb_id:
            movie_search = trakt_request(f"search/imdb/{imdb_id}?type=movie")
            if not movie_search:
                print("ERROR: Could not find movie details.")
                return
            movie = movie_search[0]["movie"]
            trakt_data["movies"].append({"watched_at": watched_at, "ids": {"imdb": imdb_id}})
            title = f"{movie['title']} ({movie['year']})"
            trakt_url = f"https://trakt.tv/movies/{movie['ids']['slug']}"

        elif media_type == "episode" and tmdb_id:
            show = get_show(tmdb_id)
            if not show:
                print("ERROR: Could not find show details.")
                return
            episode = get_episode(show, season_num, episode_num)
            if not episode:
                print("ERROR: Could not find episode details.")
                return
            title = f"{show['title']} - S{season_num:02}E{episode_num:02}"
            trakt_data["episodes"].append({"watched_at": watched_at, "ids": episode["ids"]})
            trakt_url = f"https://trakt.tv/shows/{show['ids']['slug']}/seasons/{season_num}/episodes/{episode_num}"

        # Post with retry logic
        max_retries = 5
        base_delay = 3
        success = False
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    "https://api.trakt.tv/sync/history", 
                    json=trakt_data, 
                    headers=get_headers(),
                    timeout=15
                )

                if response.status_code == 201:
                    print(f"Marked {title} as watched on Trakt.")
                    send_discord_webhook(title, trakt_url, poster_url)
                    success = True
                    break
                else:
                    print(f"ERROR: Failed to mark as watched. Status: {response.status_code}, Response: {response.text}")
                    if response.status_code >= 500 and attempt < max_retries - 1:
                        retry_delay = base_delay * (2 ** attempt)
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                    else:
                        break
            except requests.exceptions.RequestException as e:
                error_str = str(e)
                if "Failed to resolve" in error_str or "NameResolutionError" in error_str:
                    print(f"ERROR: DNS resolution failed (attempt {attempt + 1}/{max_retries})")
                else:
                    print(f"ERROR: Network error (attempt {attempt + 1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    retry_delay = base_delay * (2 ** attempt)
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
        
        if not success:
            print("ERROR: Failed to mark as watched after all retries.")

    except Exception as e:
        print(f"ERROR: {e}")

def parse_arguments():
    parser = argparse.ArgumentParser(description="Sync watched content to Trakt.")
    parser.add_argument("--contentType", choices=["movie", "episode"], required=True)
    parser.add_argument("--imdbId", help="IMDB ID for movies")
    parser.add_argument("--tmdbId", help="TMDB ID for shows")
    parser.add_argument("--season_num", type=int, help="Season number (for episodes)")
    parser.add_argument("--episode_num", type=int, help="Episode number (for episodes)")
    parser.add_argument("--posterUrl", help="Poster image URL to include in Discord embed")
    return vars(parser.parse_args())

if __name__ == "__main__":
    args = parse_arguments()
    if args["contentType"] == "movie":
        mark_as_watched("movie", imdb_id=args.get("imdbId"), poster_url=args.get("posterUrl"))
    elif args["contentType"] == "episode":
        mark_as_watched(
            "episode",
            tmdb_id=args.get("tmdbId"),
            season_num=args.get("season_num"),
            episode_num=args.get("episode_num"),
            poster_url=args.get("posterUrl")
        )