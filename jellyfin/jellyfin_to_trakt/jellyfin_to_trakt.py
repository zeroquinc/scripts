import requests
import os
from datetime import datetime, timedelta
import pytz
import time
import configparser
from pathlib import Path
import webbrowser
import logging
from logging.handlers import RotatingFileHandler

"""
This script syncs recently played items from Jellyfin to Trakt.
It only supports syncing movies and episodes played in the LAST 1 hour.
Run the script once manually and it will create a config.ini file.
Then run it with a cronjob every hour to sync new plays.
"""

# --- Config Setup ---
CONFIG_FILE = Path(__file__).parent / "config.ini"
TOKEN_URL = "https://trakt.tv/oauth/authorize"
TOKEN_EXCHANGE_URL = "https://api.trakt.tv/oauth/token"

def setup_logging(config):
    """Configure logging based on config settings"""
    log_level = config.get('LOGGING', 'level', fallback='INFO').upper()
    log_file = config.get('LOGGING', 'file', fallback='trakt_sync.log')
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3),
            logging.StreamHandler()
        ]
    )

def get_config_path():
    """Get absolute path to config.ini in the script's directory."""
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return script_dir / "config.ini"

def get_config():
    """Load or create config with OAuth tokens in script directory."""
    config_file = get_config_path()
    config = configparser.ConfigParser()
    
    if not config_file.exists():
        print(f"\nFirst run: Creating config at {config_file}\n")
        config["JELLYFIN"] = {
            "server": input("Jellyfin Server URL (e.g., http://192.168.0.150:8096): ").strip(),
            "api_key": input("Jellyfin API Key: ").strip(),
            "user_id": input("Jellyfin User ID: ").strip()
        }
        config["TRAKT"] = {
            "client_id": input("Trakt Client ID: ").strip(),
            "client_secret": input("Trakt Client Secret: ").strip(),
            "access_token": "",
            "refresh_token": "",
            "expires_at": "0"
        }
        config["LOGGING"] = {
            "level": "INFO",
            "file": "trakt_sync.log"
        }
        _authenticate_trakt(config)
        with open(config_file, "w") as f:
            config.write(f)
        print(f"\nConfiguration saved to {config_file}\n")
    else:
        config.read(config_file)
        if not config.has_section("TRAKT") or not config["TRAKT"].get("access_token"):
            _authenticate_trakt(config)
            with open(config_file, "w") as f:
                config.write(f)
    
    setup_logging(config)
    return config

def _authenticate_trakt(config):
    """Handle Trakt OAuth flow with proper error handling."""
    logging.info("Trakt authorization required. A browser will open to authenticate...")
    
    # Step 1: Get authorization code with proper application name
    auth_url = (
        f"https://trakt.tv/oauth/authorize?"
        f"response_type=code&"
        f"client_id={config['TRAKT']['client_id']}&"
        f"redirect_uri=urn:ietf:wg:oauth:2.0:oob&"
        f"response_type=code"
    )
    webbrowser.open(auth_url)
    auth_code = input("Paste the authorization code from Trakt: ").strip()
    
    # Step 2: Exchange for tokens with proper headers
    try:
        response = requests.post(
            "https://api.trakt.tv/oauth/token",
            json={
                "code": auth_code,
                "client_id": config["TRAKT"]["client_id"],
                "client_secret": config["TRAKT"]["client_secret"],
                "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                "grant_type": "authorization_code"
            },
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Jellyfin-Trakt-Sync/1.0"  # Custom user agent
            },
            timeout=30  # Add timeout
        )
        response.raise_for_status()
        tokens = response.json()
        
        if not all(key in tokens for key in ['access_token', 'refresh_token', 'expires_in']):
            raise ValueError("Invalid token response from Trakt")
        
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_details = e.response.json()
                error_msg = f"{error_msg} - {error_details.get('error_description', 'No error details')}"
            except ValueError:
                error_msg = f"{error_msg} - {e.response.text}"
        logging.error(f"Token exchange failed: {error_msg}")
        exit(1)
    except ValueError as e:
        logging.error(f"{str(e)}")
        logging.error(f"Response: {tokens}")
        exit(1)
    
    # Save tokens
    config["TRAKT"]["access_token"] = tokens["access_token"]
    config["TRAKT"]["refresh_token"] = tokens["refresh_token"]
    config["TRAKT"]["expires_at"] = str(int(time.time()) + tokens["expires_in"])
    
    logging.info("Trakt authentication successful!")

def refresh_trakt_token(config):
    """Refresh expired Trakt token."""
    if int(config["TRAKT"]["expires_at"]) > time.time() + 300:  # 5-minute buffer
        return
    
    logging.info("Refreshing Trakt token...")
    response = requests.post(
        TOKEN_EXCHANGE_URL,
        json={
            "refresh_token": config["TRAKT"]["refresh_token"],
            "client_id": config["TRAKT"]["client_id"],
            "client_secret": config["TRAKT"]["client_secret"],
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "grant_type": "refresh_token"
        }
    )
    tokens = response.json()
    
    config["TRAKT"]["access_token"] = tokens["access_token"]
    config["TRAKT"]["refresh_token"] = tokens["refresh_token"]
    config["TRAKT"]["expires_at"] = str(int(time.time()) + tokens["expires_in"])
    
    with open(CONFIG_FILE, "w") as f:
        config.write(f)

# --- Main Sync Logic ---
def fetch_recently_played_items(item_type, config):
    """Fetch items played in the last hour from Jellyfin."""
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
    
    return [
        item for item in items
        if (played_at := item.get("UserData", {}).get("LastPlayedDate")) and
        (now - datetime.fromisoformat(played_at.replace('Z', '+00:00')).replace(tzinfo=pytz.UTC) <= timedelta(hours=1))
    ]

def sync_to_trakt(item_type, item_data, external_id, played_at, config):
    """Sync an item to Trakt with OAuth with proper historical timestamp handling."""
    refresh_trakt_token(config)
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['TRAKT']['access_token']}",
        "trakt-api-version": "2",
        "trakt-api-key": config["TRAKT"]["client_id"]
    }
    
    try:
        # Parse the timestamp from Jellyfin
        if 'Z' in played_at:
            dt = datetime.fromisoformat(played_at.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(played_at)
        
        # Ensure we have timezone-aware datetime in UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        else:
            dt = dt.astimezone(pytz.UTC)
        
        # Format for Trakt API (technical format)
        trakt_date = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        # Format for human-readable display
        human_date = dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # Verify the timestamp isn't in the future
        now_utc = datetime.now(pytz.UTC)
        if dt > now_utc:
            logging.warning(f"[WARNING] Future timestamp {human_date}, using current time")
            trakt_date = now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            human_date = now_utc.strftime("%Y-%m-%d %H:%M:%S")
            
    except Exception as e:
        logging.error(f"[ERROR] Processing date {played_at}: {str(e)}")
        now_utc = datetime.now(pytz.UTC)
        trakt_date = now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        human_date = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    
    payload = {
        f"{item_type}s": [{
            "ids": {"tmdb" if item_type == "movie" else "tvdb": external_id},
            "watched_at": trakt_date
        }]
    }
    
    time.sleep(1)
    response = requests.post(
        "https://api.trakt.tv/sync/history",
        headers=headers,
        json=payload
    )
    
    if response.status_code == 201:
        if item_type == "movie":
            name = item_data.get('Name', 'Unknown Movie')
            year = item_data.get('ProductionYear', '')
            logging.info(f"[SUCCESS] Marked Movie as watched on Trakt: {name} ({year}) - Watched at {human_date}")
        else:
            series = item_data.get('SeriesName', 'Unknown Series')
            episode = item_data.get('Name', 'Unknown Episode')
            season = item_data.get('ParentIndexNumber', 0)
            episode_num = item_data.get('IndexNumber', 0)
            logging.info(f"[SUCCESS] Marked Episode as watched on Trakt: {series} - {episode} (S{season:02d}E{episode_num:02d}) - Watched at {human_date}")
    else:
        logging.error(f"[ERROR] Failed to sync {item_type}. Status: {response.status_code}")
        logging.debug(f"[DEBUG] Error details: {response.text}")

if __name__ == "__main__":
    config = get_config()
    logging.info("Syncing recently played items...")
    
    recent_movies = fetch_recently_played_items("Movie", config)
    recent_episodes = fetch_recently_played_items("Episode", config)
    
    logging.info(f"Found {len(recent_movies)} movies and {len(recent_episodes)} episodes played in the last hour.")
    
    for movie in recent_movies:
        if tmdb_id := movie.get("ProviderIds", {}).get("Tmdb"):
            sync_to_trakt("movie", movie, tmdb_id, movie["UserData"]["LastPlayedDate"], config)
    
    for episode in recent_episodes:
        if tvdb_id := episode.get("ProviderIds", {}).get("Tvdb"):
            sync_to_trakt("episode", episode, tvdb_id, episode["UserData"]["LastPlayedDate"], config)
    
    logging.info("Sync complete!")