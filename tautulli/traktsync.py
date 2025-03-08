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

In Tautulli, go to Settings > Notification Agents > Add a new notification agent > Script -> Select traktsync.py
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

# Constants
TOKEN_FILE = "trakt_token.json"
TRAKT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
CONFIG_FILE = "config.ini"
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
    """Create a default config.ini file if it doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        print("Config file not found. Creating default config.ini...")
        config = configparser.ConfigParser()
        for section, values in DEFAULT_CONFIG.items():
            config[section] = values

        with open(CONFIG_FILE, "w") as f:
            config.write(f)

        print(f"Default config.ini created. Please fill in the missing values in {CONFIG_FILE}.")
        sys.exit(1)  # Exit to prevent running with incomplete config

# Load configuration
create_default_config()
config = configparser.ConfigParser()
config.read(CONFIG_FILE)

TRAKT_CONFIG = config["Trakt"]
DISCORD_CONFIG = config["Discord"]

def load_or_refresh_token():
    """Load Trakt token from file or request a new one if needed."""
    global trakt_token
    try:
        with open(TOKEN_FILE, "r") as f:
            trakt_token = json.load(f)

        if trakt_token.get("expires_at", 0) - 300 < time.time():
            refresh_token()

    except (FileNotFoundError, json.JSONDecodeError):
        request_new_token()

def save_token():
    """Save the Trakt token to file."""
    with open(TOKEN_FILE, "w") as f:
        json.dump(trakt_token, f)

def request_new_token():
    """Request a new Trakt token."""
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
    """Refresh Trakt token if expired."""
    global trakt_token
    print("Refreshing Trakt token...")
    response = requests.post("https://trakt.tv/oauth/token", data={
        "client_id": TRAKT_CONFIG["client_id"],
        "client_secret": TRAKT_CONFIG["client_secret"],
        "refresh_token": trakt_token["refresh_token"],
        "grant_type": "refresh_token"
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})

    trakt_token = response.json()
    save_token()

def get_headers(auth=True):
    """Return common headers for Trakt API requests."""
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CONFIG["client_id"]
    }
    if auth:
        headers["Authorization"] = f"Bearer {trakt_token['access_token']}"
    return headers

def trakt_request(endpoint, params=None):
    """Generic function to make GET requests to Trakt API."""
    response = requests.get(f"https://api.trakt.tv/{endpoint}", headers=get_headers(), params=params)
    return response.json() if response.status_code == 200 else None

def get_show(tmdb_id):
    """Get show details from Trakt API."""
    return trakt_request(f"search/tmdb/{tmdb_id}?type=show")[0]["show"]

def get_episode(show, season_num, episode_num):
    """Get episode details from Trakt API."""
    return trakt_request(f"shows/{show['ids']['slug']}/seasons/{season_num}/episodes/{episode_num}")

def get_current_timestamp():
    """Generate current timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def send_discord_webhook(title):
    """Send a Discord webhook notification."""
    discord_webhook_url = DISCORD_CONFIG.get("webhook_url", "")

    if not discord_webhook_url:
        print("WARNING: Discord webhook URL not configured. Skipping notification.")
        return

    payload = {"embeds": [{"description": f"> Successfully marked {title} as watched on Trakt.", "color": 16711680}]}
    response = requests.post(discord_webhook_url, json=payload)

    if response.status_code == 204:
        print("Discord notification sent successfully.")
    else:
        print(f"ERROR: Discord notification failed. Status: {response.status_code}, Response: {response.text}")

def mark_as_watched(media_type, imdb_id=None, tmdb_id=None, season_num=None, episode_num=None):
    """Mark content as watched on Trakt and send a Discord webhook."""
    try:
        load_or_refresh_token()
        watched_at = get_current_timestamp()
        trakt_data = {"movies": [], "episodes": []}
        title = ""

        if media_type == "movie" and imdb_id:
            trakt_data["movies"].append({"watched_at": watched_at, "ids": {"imdb": imdb_id}})
            title = f"movie with IMDb ID: {imdb_id}"
        elif media_type == "episode" and tmdb_id:
            show = get_show(tmdb_id)
            episode = get_episode(show, season_num, episode_num)
            title = f"{show['title']} - S{season_num:02}E{episode_num:02}"
            trakt_data["episodes"].append({"watched_at": watched_at, "ids": episode["ids"]})

        response = requests.post("https://api.trakt.tv/sync/history", json=trakt_data, headers=get_headers())

        if response.status_code == 201:
            print(f"Marked {title} as watched on Trakt.")
            send_discord_webhook(title)
        else:
            print(f"ERROR: Failed to mark as watched. Status: {response.status_code}, Response: {response.text}")

    except Exception as e:
        print(f"ERROR: {e}")

def parse_arguments():
    """Parse command-line arguments using argparse."""
    parser = argparse.ArgumentParser(description="Sync watched content to Trakt.")
    parser.add_argument("--contentType", choices=["movie", "episode"], required=True)
    parser.add_argument("--imdbId", help="IMDB ID for movies")
    parser.add_argument("--tmdbId", help="TMDB ID for shows")
    parser.add_argument("--season_num", type=int, help="Season number (for episodes)")
    parser.add_argument("--episode_num", type=int, help="Episode number (for episodes)")

    return vars(parser.parse_args())

if __name__ == "__main__":
    args = parse_arguments()

    if args["contentType"] == "movie":
        mark_as_watched("movie", imdb_id=args.get("imdbId"))
    elif args["contentType"] == "episode":
        mark_as_watched("episode", tmdb_id=args.get("tmdbId"), season_num=args.get("season_num"), episode_num=args.get("episode_num"))