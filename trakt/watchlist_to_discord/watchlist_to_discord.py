import requests
from datetime import datetime, timedelta, timezone
import logging

try:
    from config import (
        TRAKT_CLIENT_ID, 
        TRAKT_USERNAME, 
        TMDB_API_KEY, 
        OMDB_API_KEY, 
        DISCORD_WEBHOOK,
        LOG_LEVEL
    )
except ImportError:
    raise ImportError("Please create a config.py file with your credentials (use config.example.py as a template)")

# Setup logging with default format but configurable level
logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)

# --- API HELPERS --- #
def get_trakt_watchlist():
    """Get sorted watchlist (oldest first) with Trakt ratings"""
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID
    }
    url = f"https://api.trakt.tv/users/{TRAKT_USERNAME}/watchlist?extended=full"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        items = response.json()
        logger.debug(f"Trakt Watchlist Response: {items}")
        return sorted(items, key=lambda x: x["listed_at"])  # Oldest first
    except Exception as e:
        logger.error(f"Trakt API Error: {e}")
        return []

def get_trakt_user():
    """Get Trakt user info including avatar"""
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID
    }
    url = f"https://api.trakt.tv/users/{TRAKT_USERNAME}?extended=full"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Trakt User API Error: {e}")
        return None

def get_tmdb_data(tmdb_id, media_type):
    """Get TMDB details including rating"""
    if not tmdb_id: return None
    if media_type == 'show':
        media_type = 'tv'
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        logger.debug(f"TMDB Response: {response.json()}")
        return response.json()
    except Exception as e:
        logger.error(f"TMDB Error: {e}")
        return None

def get_omdb_ratings(imdb_id):
    """Get IMDb + Rotten Tomatoes ratings"""
    if not imdb_id: return {}
    try:
        url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        logger.debug(f"OMDB Response: {response.json()}")
        ratings = {}
        for r in response.json().get("Ratings", []):
            if "Internet Movie Database" in r["Source"]:
                ratings["imdb"] = r["Value"]
            elif "Rotten Tomatoes" in r["Source"]:
                ratings["rotten_tomatoes"] = r["Value"]
        return ratings
    except Exception as e:
        logger.error(f"OMDB Error: {e}")
        return {}

# --- NOTIFICATION BUILDER --- #
def build_ratings_string(trakt_rating, tmdb_rating, omdb_ratings):
    """Combine all ratings into one line with proper Trakt % formatting"""
    parts = []
    if trakt_rating:
        parts.append(f"Trakt: {int(round(float(trakt_rating) * 10))}%")
    if tmdb_rating:
        parts.append(f"TMDB: {tmdb_rating}/10")
    if omdb_ratings.get("imdb"):
        parts.append(f"IMDb: {omdb_ratings['imdb']}")
    if omdb_ratings.get("rotten_tomatoes"):
        parts.append(f"RT: {omdb_ratings['rotten_tomatoes']}")
    return " • ".join(parts) if parts else "No ratings"

def create_embed(item):
    media_type = "movie" if "movie" in item else "show"
    media_data = item[media_type]
    ids = media_data.get("ids", {})
    
    # Get all ratings
    trakt_rating = media_data.get("rating")
    tmdb_data = get_tmdb_data(ids.get("tmdb"), media_type)
    tmdb_rating = round(tmdb_data.get("vote_average", 0), 1) if tmdb_data else None
    omdb_ratings = get_omdb_ratings(ids.get("imdb"))
    
    # Get Trakt user info for footer
    trakt_user = get_trakt_user()
    
    # Build embed
    embed = {
        "title": f"{media_data['title']} ({media_data.get('year', 'N/A')})",
        "url": f"https://trakt.tv/{media_type}s/{ids.get('slug', '')}",
        "description": f"**Summary**\n{media_data.get('overview', 'No summary available.')}",
        "color": 0xE5A00D,
        "fields": [{
            "name": "Ratings",
            "value": build_ratings_string(trakt_rating, tmdb_rating, omdb_ratings),
            "inline": False
        }],
        "timestamp": item["listed_at"],
        "author": {
            "name": f"Trakt: New {media_type} added to Watchlist",
            "icon_url": "https://i.imgur.com/7gkofW8.png"
        },
        "footer": {
            "text": f"Added by: {TRAKT_USERNAME}",
            "icon_url": trakt_user.get("images", {}).get("avatar", {}).get("full") if trakt_user else ""
        }
    }
    
    # Add TMDB poster if available
    if tmdb_data and tmdb_data.get("poster_path"):
        embed["image"] = {"url": f"https://image.tmdb.org/t/p/w500{tmdb_data['poster_path']}"}
    
    return embed

# --- MAIN EXECUTION --- #
def main():
    try:
        # Get recent additions (sorted oldest first)
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        new_items = [
            item for item in get_trakt_watchlist()
            if item["listed_at"] > one_hour_ago
        ]
        logger.info(f"New items in watchlist: {len(new_items)}")
        # Send notifications
        for item in new_items:
            requests.post(DISCORD_WEBHOOK, json={"embeds": [create_embed(item)]}, timeout=10)
    except Exception as e:
        logger.error(f"Runtime Error: {e}")

if __name__ == "__main__":
    main()