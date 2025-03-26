import requests
from datetime import datetime, timedelta
import pytz
import time
import configparser
from pathlib import Path

# --- Config File Setup ---
CONFIG_FILE = Path("config.ini")

def get_config():
    """Load or create config.ini with user input."""
    config = configparser.ConfigParser()
    
    if not CONFIG_FILE.exists():
        print("\nFirst run: Let's configure your settings!\n")
        
        # Jellyfin Settings
        jellyfin_server = input("Jellyfin Server URL (e.g., http://192.168.0.150:8096): ").strip()
        jellyfin_api_key = input("Jellyfin API Key: ").strip()
        jellyfin_user_id = input("Jellyfin User ID: ").strip()
        
        # Trakt Settings
        trakt_api_key = input("Trakt API Key: ").strip()
        trakt_client_id = input("Trakt Client ID: ").strip()
        
        # Write to config.ini
        config["JELLYFIN"] = {
            "server": jellyfin_server,
            "api_key": jellyfin_api_key,
            "user_id": jellyfin_user_id
        }
        config["TRAKT"] = {
            "api_key": trakt_api_key,
            "client_id": trakt_client_id
        }
        
        with open(CONFIG_FILE, "w") as f:
            config.write(f)
        print("\nConfig saved to config.ini. You can edit it manually later.\n")
    
    config.read(CONFIG_FILE)
    return config

# --- Main Script Logic ---
def fetch_recently_played_items(item_type, config):
    """Fetch items played in the last hour."""
    now = datetime.now(pytz.utc)
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    
    response = requests.get(
        f"{config['JELLYFIN']['server']}/Users/{config['JELLYFIN']['user_id']}/Items",
        params={
            "Filters": "IsPlayed",
            "Recursive": "true",
            "IncludeItemTypes": item_type,
            "Fields": "ProviderIds,ParentId,SeriesName,UserData,ProductionYear",
            "MinDate": one_hour_ago
        },
        headers={"Authorization": f"MediaBrowser Token={config['JELLYFIN']['api_key']}"}
    )
    items = response.json().get("Items", [])
    
    # Strict time filtering
    return [
        item for item in items
        if (played_at := item.get("UserData", {}).get("LastPlayedDate")) and
        (now - datetime.fromisoformat(played_at.rstrip("Z")).replace(tzinfo=pytz.utc) <= timedelta(hours=1))
    ]

def mark_as_watched_on_trakt(item_type, external_id, played_at, config):
    """Sync an item to Trakt with rate limiting."""
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": config['TRAKT']['api_key'],
        "Authorization": f"Bearer {config['TRAKT']['client_id']}"
    }
    
    payload = {
        "watched_at": played_at,
        f"{item_type}s": [{"ids": {"tmdb" if item_type == "movie" else "tvdb": external_id}}]
    }
    
    time.sleep(1)  # Rate limit
    response = requests.post("https://api.trakt.tv/sync/history", headers=headers, json=payload)
    
    if response.status_code == 201:
        print(f"✓ Synced {item_type} (ID: {external_id})")
    else:
        print(f"✗ Failed to sync {item_type} (ID: {external_id}). Error: {response.text}")

if __name__ == "__main__":
    config = get_config()
    
    print("\nSyncing recently played items...")
    recent_movies = fetch_recently_played_items("Movie", config)
    recent_episodes = fetch_recently_played_items("Episode", config)
    
    print(f"Found {len(recent_movies)} movies and {len(recent_episodes)} episodes played in the last hour.")
    
    for movie in recent_movies:
        if tmdb_id := movie.get("ProviderIds", {}).get("Tmdb"):
            mark_as_watched_on_trakt("movie", tmdb_id, movie["UserData"]["LastPlayedDate"], config)
    
    for episode in recent_episodes:
        if tvdb_id := episode.get("ProviderIds", {}).get("Tvdb"):
            mark_as_watched_on_trakt("episode", tvdb_id, episode["UserData"]["LastPlayedDate"], config)
    
    print("Sync complete!")