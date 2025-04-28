import requests
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional, Dict, List
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from functools import lru_cache
import time
from dataclasses import dataclass

# Configuration
try:
    from config import (
        TRAKT_CLIENT_ID,
        TRAKT_USERNAME,
        TMDB_API_KEY,
        OMDB_API_KEY,
        DISCORD_WEBHOOK,
        LOG_LEVEL,
        CHECK_INTERVAL_MINUTES
    )
except ImportError:
    raise ImportError("Missing config.py - use config.example.py as template")

# Constants
TRAKT_API_BASE = "https://api.trakt.tv"
TMDB_API_BASE = "https://api.themoviedb.org/3"
OMDB_API_BASE = "http://www.omdbapi.com"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"
DISCORD_EMBED_LIMIT = 6000  # Discord's embed character limit
REQUEST_TIMEOUT = getattr(locals(), 'REQUEST_TIMEOUT', 15)
MAX_RETRIES = getattr(locals(), 'MAX_RETRIES', 3)

# Logging setup
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --------------------------------------------------
# API Clients
# --------------------------------------------------

class APIClientBase:
    """Base class for API clients with retry logic"""
    def __init__(self):
        self.session = requests.Session()
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[408, 429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get(self, url: str, **kwargs) -> Optional[Dict]:
        try:
            response = self.session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                **kwargs
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"API request failed to {url}: {str(e)}")
            return None

class TraktClient(APIClientBase):
    """Client for Trakt API"""
    def __init__(self):
        super().__init__()
        self.headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": TRAKT_CLIENT_ID,
            "User-Agent": f"TraktWatchlistNotifier/1.0 ({TRAKT_USERNAME})"
        }

    def get_watchlist(self) -> List[Dict]:
        """Get sorted watchlist (oldest first)"""
        url = f"{TRAKT_API_BASE}/users/{TRAKT_USERNAME}/watchlist?extended=full"
        if data := self._get(url, headers=self.headers):
            return sorted(data, key=lambda x: x["listed_at"])
        return []

    def get_user_profile(self) -> Optional[Dict]:
        """Get Trakt user profile with avatar"""
        url = f"{TRAKT_API_BASE}/users/{TRAKT_USERNAME}?extended=full"
        return self._get(url, headers=self.headers)

class TmdbClient(APIClientBase):
    """Client for TMDB API with response caching"""
    @lru_cache(maxsize=128)
    def get_details(self, tmdb_id: int, media_type: str) -> Optional[Dict]:
        """Get TMDB details with caching"""
        if not tmdb_id:
            return None

        media_type = 'tv' if media_type == 'show' else 'movie'
        url = f"{TMDB_API_BASE}/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        return self._get(url)

class OmdbClient(APIClientBase):
    """Client for OMDB API"""
    def get_ratings(self, imdb_id: str) -> Dict[str, str]:
        """Get ratings from OMDB"""
        if not imdb_id:
            return {}

        url = f"{OMDB_API_BASE}/?i={imdb_id}&apikey={OMDB_API_KEY}"
        if data := self._get(url):
            return self._parse_ratings(data.get("Ratings", []))
        return {}

    def _parse_ratings(self, ratings: List[Dict]) -> Dict[str, str]:
        """Extract IMDb and Rotten Tomatoes ratings"""
        result = {}
        for r in ratings:
            source = r.get("Source", "")
            if "Internet Movie Database" in source:
                result["imdb"] = r["Value"]
            elif "Rotten Tomatoes" in source:
                result["rotten_tomatoes"] = r["Value"]
        return result

# --------------------------------------------------
# Discord Components
# --------------------------------------------------

@dataclass
class MediaItem:
    """Dataclass for normalized media item data"""
    title: str
    year: str
    overview: str
    trakt_rating: Optional[float]
    tmdb_rating: Optional[float]
    imdb_rating: Optional[str]
    rt_rating: Optional[str]
    trakt_url: str
    poster_url: Optional[str]
    listed_at: str
    media_type: str

class DiscordNotifier:
    """Handles Discord webhook communications"""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def send(self, embed: Dict) -> bool:
        """Send embed to Discord with rate limit handling"""
        try:
            response = self.session.post(
                DISCORD_WEBHOOK,
                json={"embeds": [embed]},
                timeout=REQUEST_TIMEOUT
            )
            
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 5))
                logger.warning(f"Rate limited - retrying after {retry_after}s")
                time.sleep(retry_after)
                return self.send(embed)
                
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Discord notification failed: {str(e)}")
            return False

class EmbedBuilder:
    """Constructs Discord embeds from media data"""
    def __init__(self, trakt_client: TraktClient, tmdb_client: TmdbClient, omdb_client: OmdbClient):
        self.trakt = trakt_client
        self.tmdb = tmdb_client
        self.omdb = omdb_client

    def create_from_trakt_item(self, item: Dict) -> Dict:
        """Main method to convert Trakt item to Discord embed"""
        media_type = "movie" if "movie" in item else "show"
        media_data = item[media_type]
        ids = media_data.get("ids", {})

        # Fetch additional data
        tmdb_data = self.tmdb.get_details(ids.get("tmdb"), media_type)
        omdb_ratings = self.omdb.get_ratings(ids.get("imdb"))
        user_profile = self.trakt.get_user_profile()

        # Normalize data
        media_item = MediaItem(
            title=media_data["title"],
            year=str(media_data.get("year", "N/A")),
            overview=media_data.get("overview", "No summary available."),
            trakt_rating=media_data.get("rating"),
            tmdb_rating=round(tmdb_data.get("vote_average", 0), 1) if tmdb_data else None,
            imdb_rating=omdb_ratings.get("imdb"),
            rt_rating=omdb_ratings.get("rotten_tomatoes"),
            trakt_url=f"https://trakt.tv/{media_type}s/{ids.get('slug', '')}",
            poster_url=f"{POSTER_BASE_URL}{tmdb_data['poster_path']}" if tmdb_data and tmdb_data.get("poster_path") else None,
            listed_at=item["listed_at"],
            media_type=media_type
        )

        return self._build_embed(media_item, user_profile)

    def _build_embed(self, item: MediaItem, user_profile: Optional[Dict]) -> Dict:
        """Construct the final embed structure"""
        embed = {
            "title": f"{item.title} ({item.year})",
            "url": item.trakt_url,
            "description": self._truncate(item.overview),
            "color": 0xE5A00D,
            "fields": [self._build_ratings_field(item)],
            "timestamp": item.listed_at,
            "author": {
                "name": f"New {item.media_type} added to watchlist",
                "icon_url": "https://i.imgur.com/7gkofW8.png"
            },
            "footer": self._build_footer(user_profile)
        }

        if item.poster_url:
            embed["image"] = {"url": item.poster_url}

        return embed

    def _build_ratings_field(self, item: MediaItem) -> Dict:
        """Construct the ratings field"""
        parts = []
        if item.trakt_rating:
            parts.append(f"Trakt: {int(round(item.trakt_rating * 10))}%")
        if item.tmdb_rating:
            parts.append(f"TMDB: {item.tmdb_rating}/10")
        if item.imdb_rating:
            parts.append(f"IMDb: {item.imdb_rating}")
        if item.rt_rating:
            parts.append(f"RT: {item.rt_rating}")

        return {
            "name": "Ratings",
            "value": " • ".join(parts) if parts else "No ratings available",
            "inline": False
        }

    def _build_footer(self, user_profile: Optional[Dict]) -> Dict:
        """Construct footer with user info"""
        avatar = (user_profile or {}).get("images", {}).get("avatar", {}).get("full", "")
        return {
            "text": f"Added by {TRAKT_USERNAME}",
            "icon_url": avatar
        }

    @staticmethod
    def _truncate(text: str, limit: int = DISCORD_EMBED_LIMIT) -> str:
        """Ensure text fits within Discord's limits"""
        return text[:limit-3] + "..." if len(text) > limit else text

# --------------------------------------------------
# Main Application
# --------------------------------------------------

class WatchlistNotifier:
    """Main application class"""
    def __init__(self):
        self.trakt = TraktClient()
        self.tmdb = TmdbClient()
        self.omdb = OmdbClient()
        self.discord = DiscordNotifier()
        self.embed_builder = EmbedBuilder(self.trakt, self.tmdb, self.omdb)

    def get_recent_items(self, minutes: int = None) -> List[Dict]:
        """Get items added since last check"""
        minutes = minutes or CHECK_INTERVAL_MINUTES
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        return [
            item for item in self.trakt.get_watchlist()
            if item["listed_at"] > cutoff
        ]

    def process_and_notify(self):
        """Main workflow"""
        try:
            logger.info("Checking for new watchlist items...")
            new_items = self.get_recent_items()
            
            if not new_items:
                logger.info("No new items found")
                return

            logger.info(f"Processing {len(new_items)} new items")
            success_count = 0

            for item in new_items:
                embed = self.embed_builder.create_from_trakt_item(item)
                if self.discord.send(embed):
                    success_count += 1
                else:
                    logger.warning(f"Failed to send item: {item.get('title', 'Unknown')}")

            logger.info(f"Successfully sent {success_count}/{len(new_items)} notifications")

        except Exception as e:
            logger.critical(f"Fatal error: {str(e)}", exc_info=True)
            raise

def main():
    """Entry point"""
    notifier = WatchlistNotifier()
    notifier.process_and_notify()

if __name__ == "__main__":
    main()