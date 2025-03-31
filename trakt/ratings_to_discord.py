import requests
from datetime import datetime, timedelta, timezone

# Configuration (EDIT THIS)
TRAKT_API_KEY = "" # Trakt Client ID
TMDB_API_KEY = ""  # TMDB API Key for posters
TRAKT_USERNAME = "" # Trakt username (not user ID) capital sensitive
DISCORD_WEBHOOK_URL = "" # Discord Webhook URL
HOURS = 1  # Number of hours to check for new ratings

def log(message):
    """Simple logging function with timestamps"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")

def get_tmdb_poster_url(tmdb_id, media_type):
    if not tmdb_id or not media_type:
        return None

    base_url = "https://api.themoviedb.org/3"
    
    try:
        # First get the main details to find the best poster
        if media_type == "movie":
            details_url = f"{base_url}/movie/{tmdb_id}?api_key={TMDB_API_KEY}"
        else:  # for shows
            details_url = f"{base_url}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
        
        response = requests.get(details_url)
        response.raise_for_status()
        data = response.json()
        
        # Try to get poster path from details first
        poster_path = data.get('poster_path')
        
        if poster_path:
            return f"https://image.tmdb.org/t/p/w500{poster_path}"
        
        # If no poster in details, try the images endpoint
        images_url = f"{base_url}/{media_type}/{tmdb_id}/images?api_key={TMDB_API_KEY}"
        response = requests.get(images_url)
        response.raise_for_status()
        images_data = response.json()
        
        # Get the first poster if available
        if images_data.get('posters') and len(images_data['posters']) > 0:
            poster_path = images_data['posters'][0]['file_path']
            return f"https://image.tmdb.org/t/p/w500{poster_path}"
        
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            log(f"TMDb ID {tmdb_id} not found for {media_type}")
        else:
            log(f"Error fetching TMDb poster: {e}")
    except requests.exceptions.RequestException as e:
        log(f"Request error fetching TMDb poster: {e}")
    
    return None

def get_comments_for_item(item_type, item_id, show_id=None, season_num=None, episode_num=None):
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_API_KEY
    }
    
    # For episodes, we need to use a different endpoint
    if item_type == "episode":
        if not show_id or not season_num or not episode_num:
            return []
        url = f"https://api.trakt.tv/shows/{show_id}/seasons/{season_num}/episodes/{episode_num}/comments"
    else:
        url = f"https://api.trakt.tv/users/{TRAKT_USERNAME}/comments/{item_type}/{item_id}"
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        comments = response.json()

        # Filter for comments in the last hour (same as ratings)
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=HOURS)
        recent_comments = []
        
        for c in comments:
            try:
                created_at = c.get('created_at')
                if not created_at:
                    continue
                    
                created_date = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                if created_date > one_hour_ago and c.get('user', {}).get('username') == TRAKT_USERNAME:
                    recent_comments.append(c)
            except (ValueError, TypeError) as e:
                log(f"Error parsing comment date: {e}")
                continue
        
        return recent_comments
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            return []  # No comments found
        log(f"Error fetching comments: {e}")
        return []
    except requests.exceptions.RequestException as e:
        log(f"Request error fetching comments: {e}")
        return []

def get_all_ratings():
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_API_KEY
    }
    
    url = f"https://api.trakt.tv/users/{TRAKT_USERNAME}/ratings"
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        log(f"Error fetching ratings: {e}")
        return None

def filter_recent_ratings(ratings):
    if not ratings:
        return []
    
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=HOURS)
    recent_ratings = []
    
    for item in ratings:
        rated_at = datetime.strptime(item.get('rated_at'), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        if rated_at > one_hour_ago:
            recent_ratings.append(item)
    
    return recent_ratings

def create_discord_embed(ratings):
    if not ratings:
        return None
    
    embeds = []
    
    for item in ratings:
        rating = item.get('rating', 0)
        item_type = item.get('type', '')
        item_id = None
        show_id = None
        season_num = None
        episode_num = None
        
        title = ""
        tmdb_id = None
        media_type_for_tmdb = None
        fields = []  # We'll use fields instead of description
        trakt_url = None  # This will store the URL to the item on Trakt

        # Create fields for user and rating
        fields.append({
            "name": "User",
            "value": TRAKT_USERNAME,
            "inline": True,
        })
        fields.append({
            "name": "Rating",
            "value": f"{rating}/10 ⭐",
            "inline": True,
        })

        if item_type == "movie":
            item_data = item.get('movie', {})
            title = f"{item_data.get('title', 'Unknown')} ({item_data.get('year', '')})"
            tmdb_id = item_data.get('ids', {}).get('tmdb')
            item_id = item_data.get('ids', {}).get('trakt')
            media_type_for_tmdb = "movie"
            trakt_url = f"https://trakt.tv/movies/{item_data.get('ids', {}).get('slug', '')}"
        elif item_type == "show":
            item_data = item.get('show', {})
            title = f"{item_data.get('title', 'Unknown')} ({item_data.get('year', '')})"
            tmdb_id = item_data.get('ids', {}).get('tmdb')
            item_id = item_data.get('ids', {}).get('trakt')
            media_type_for_tmdb = "tv"
            trakt_url = f"https://trakt.tv/shows/{item_data.get('ids', {}).get('slug', '')}"
        elif item_type == "season":
            item_data = item.get('season', {})
            show_data = item.get('show', {})
            show_title = show_data.get('title', 'Unknown Show')
            season_num = item_data.get('number', 0)
            title = f"{show_title} - Season {season_num}"
            tmdb_id = show_data.get('ids', {}).get('tmdb')
            item_id = item_data.get('ids', {}).get('trakt')
            show_id = show_data.get('ids', {}).get('trakt')
            media_type_for_tmdb = "tv"
            trakt_url = f"https://trakt.tv/shows/{show_data.get('ids', {}).get('slug', '')}/seasons/{season_num}"
        elif item_type == "episode":
            item_data = item.get('episode', {})
            show_data = item.get('show', {})
            show_title = show_data.get('title', 'Unknown Show')
            season_num = item_data.get('season', item_data.get('number', 0))
            episode_num = item_data.get('number', 0)
            episode_title = item_data.get('title', 'Unknown Episode')
            title = f"{show_title} - {episode_title} (S{season_num:02d}E{episode_num:02d})"
            tmdb_id = show_data.get('ids', {}).get('tmdb')
            item_id = item_data.get('ids', {}).get('trakt')
            show_id = show_data.get('ids', {}).get('trakt')
            media_type_for_tmdb = "tv"
            trakt_url = f"https://trakt.tv/shows/{show_data.get('ids', {}).get('slug', '')}/seasons/{season_num}/episodes/{episode_num}"
        
        # Check for comments on this item
        comments = get_comments_for_item(
            item_type, 
            item_id,
            show_id=show_id,
            season_num=season_num,
            episode_num=episode_num
        )
        
        if comments:
            comment_texts = []
            for comment in comments[:3]:  # Show up to 3 recent comments
                comment_text = comment.get('comment', '').strip()
                if comment_text:
                    comment_texts.append(f"• {comment_text[:200]}{'...' if len(comment_text) > 200 else ''}")
            
            if comment_texts:
                fields.append({
                    "name": "User Comments",
                    "value": "\n".join(comment_texts),
                    "inline": False
                })

        if rating >= 7:
            color = 0x00FF00
        elif rating >= 5:
            color = 0xFFA500
        else:
            color = 0xFF0000

        embed = {
            "title": title[:256],
            "url": trakt_url,
            "fields": fields,
            "color": color,
            "author": {
                "name": "Trakt: Item Rated",
                "icon_url": "https://i.imgur.com/7gkofW8.png"
            },
        }
        
        # Fetch poster from TMDb if available
        if tmdb_id and media_type_for_tmdb:
            poster_url = get_tmdb_poster_url(tmdb_id, media_type_for_tmdb)
            if poster_url:
                embed["thumbnail"] = {"url": poster_url}
        
        embeds.append(embed)
    
    return embeds

def send_to_discord(embeds):
    if not embeds:
        log("No new ratings to send.")
        return
    
    payload = {
        "embeds": embeds,
    }
    
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        log(f"Successfully sent {len(embeds)} rating{'s' if len(embeds) != 1 else ''} to Discord")
    except requests.exceptions.RequestException as e:
        log(f"Error sending to Discord: {e}")

def main():
    log("Fetching all ratings...")
    ratings = get_all_ratings()
    
    if ratings:
        log(f"Found {len(ratings)} total ratings")
        recent_ratings = filter_recent_ratings(ratings)
        count = len(recent_ratings)
        log(f"Found {count} new rating{'s' if count != 1 else ''} in the last {HOURS} hour{'s' if HOURS != 1 else ''}")
        
        if recent_ratings:
            # Sort ratings by 'rated_at' in ascending order to send the oldest first
            recent_ratings.sort(key=lambda x: datetime.strptime(x['rated_at'], "%Y-%m-%dT%H:%M:%S.%fZ"))
            embeds = create_discord_embed(recent_ratings)
            send_to_discord(embeds)
    else:
        log("No ratings found")

if __name__ == "__main__":
    main()