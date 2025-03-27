import requests
import configparser
import logging
import os
from datetime import datetime, timedelta

# Constants
CONFIG_FILE = 'config.ini'
LOG_FILE = 'trakt_weekly.log'
BASE_URLS = {
    'trakt': 'https://api.trakt.tv/',
    'tmdb': {
        'movie': 'https://api.themoviedb.org/3/movie/',
        'show': 'https://api.themoviedb.org/3/tv/'
    }
}
TMDB_IMAGE_URL = 'https://image.tmdb.org/t/p/w500/'

class Config:
    """Centralized configuration handler"""
    SECTIONS = {
        'DISCORD': {'webhook_url': 'Enter your Discord Webhook URL: '},
        'TRAKT': {'client_id': 'Enter your Trakt Client ID: '},
        'TMDB': {'api_key': 'Enter your TMDB API Key: '}
    }

    @classmethod
    def load(cls):
        config = configparser.ConfigParser()
        if not os.path.exists(CONFIG_FILE):
            cls._create_config(config)
        config.read(CONFIG_FILE)
        cls._validate_config(config)
        return config

    @classmethod
    def _create_config(cls, config):
        logger.info("Creating new config file...")
        for section, settings in cls.SECTIONS.items():
            config[section] = {k: input(prompt) for k, prompt in settings.items()}
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)

    @classmethod
    def _validate_config(cls, config):
        for section, settings in cls.SECTIONS.items():
            if section not in config or any(k not in config[section] for k in settings):
                raise ValueError(f"Invalid config: Missing section or keys in [{section}]")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Load config
try:
    config = Config.load()
    WEBHOOK_URL = config['DISCORD']['webhook_url']
    TRAKT_HEADERS = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': config['TRAKT']['client_id']
    }
    TMDB_API_KEY = config['TMDB']['api_key']
except Exception as e:
    logger.error(f"Configuration error: {e}")
    raise

class EmbedBuilder:
    """Handles Discord embed creation and styling"""
    STYLES = {
        'movie': {'color': 0xffa500, 'emoji': '🎬'},
        'show': {'color': 0x67B7D1, 'emoji': '📺'}
    }
    RANK_EMOJIS = {1: "🥇", 2: "🥈", 3: "🥉"}
    THUMBNAIL = "https://i.imgur.com/tvnkxAY.png"

    @classmethod
    def create(cls, item_type, items):
        date_range = cls._get_date_range()
        week_number = (datetime.now() - timedelta(days=7)).isocalendar()[1]
        embed = {
            'color': cls.STYLES[item_type]['color'],
            'author': {
                'name': f"{cls.STYLES[item_type]['emoji']} Top {item_type}s (Week {week_number})",
                'icon_url': cls.THUMBNAIL
            },
            'footer': {'text': date_range},
            'fields': []
        }

        for i, item in enumerate(items[:9]):
            poster_url = APIHandler.get_tmdb_poster(item_type, item[item_type]['ids']['tmdb'])
            if i == 0 and poster_url:  # Use first item's poster as thumbnail
                embed['thumbnail'] = {'url': poster_url}
            
            embed['fields'].append({
                'name': f"{cls.RANK_EMOJIS.get(i+1, '')} {item[item_type]['title']} ({item[item_type]['year']})",
                'value': f"[{item['watcher_count']:,} watchers](https://trakt.tv/{item_type}s/{item[item_type]['ids']['slug']})",
                'inline': True
            })

        return embed

    @staticmethod
    def _get_date_range():
        """Returns 8-day range including today (Mar 20-27 when run on Mar 27)"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)  # 8 days total (7 days back + today)
        return f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d %Y')}"

class APIHandler:
    """Handles all API communications"""
    @staticmethod
    def get_trakt_data(item_type):
        url = f"{BASE_URLS['trakt']}{item_type}s/watched/period=weekly"
        try:
            response = requests.get(url, headers=TRAKT_HEADERS)
            response.raise_for_status()
            return sorted(response.json(), key=lambda x: x['watcher_count'], reverse=True)
        except requests.exceptions.RequestException as e:
            logger.error(f"Trakt API error: {e}")
            return []

    @staticmethod
    def get_tmdb_poster(item_type, tmdb_id):
        """Fetch poster URL from TMDB API"""
        if not tmdb_id:
            return None
            
        url = f"{BASE_URLS['tmdb'][item_type]}{tmdb_id}?api_key={TMDB_API_KEY}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            if poster_path := response.json().get('poster_path'):
                return f"{TMDB_IMAGE_URL}{poster_path}"
        except requests.exceptions.RequestException as e:
            logger.error(f"TMDB API error for {item_type} ID {tmdb_id}: {e}")
        return None

    @staticmethod
    def send_to_discord(embeds):
        try:
            response = requests.post(WEBHOOK_URL, json={'embeds': embeds})
            response.raise_for_status()
            logger.info("Successfully sent to Discord")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Discord webhook error: {e}")
            return False

def main():
    embeds = []
    
    for media_type in ['movie', 'show']:
        if data := APIHandler.get_trakt_data(media_type):
            embeds.append(EmbedBuilder.create(media_type, data))
    
    if not APIHandler.send_to_discord(embeds):
        logger.warning("Using fallback output")
        return {'embeds': embeds}
    return {'status': 'success'}

if __name__ == "__main__":
    main()