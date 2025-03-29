#!/usr/bin/env python
"""

Tautulli Discord Webhook Script
Sends notifications to Discord when new content is added to Plex.

In Tautulli, add a new notification agent Script.
Triggers -> Recently Added
Arguments -> Recently Added -> Scripts Arguments
--media_type "{media_type}" --title "{title}" --summary "{summary}" --poster_url "{poster_url}" --plex_url "{plex_url}" --year "{year}" --season_num00 "{season_num00}" --episode_num00 "{episode_num00}" --episode_count "{episode_count}" --imdb_url "{imdb_url}" --themoviedb_url "{themoviedb_url}" --thetvdb_url "{thetvdb_url}" --trakt_url "{trakt_url}"

"""

import argparse
import json
import requests

# Configuration - set these values
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL_HERE"
AUTHOR_ICON_URL = "https://i.imgur.com/QLxJe4L.png"  # Default Plex icon

def send_discord_webhook(embed, webhook_url):
    """Send the embed to Discord via webhook."""
    data = {"embeds": [embed]}
    headers = {'Content-Type': 'application/json'}
    
    response = requests.post(webhook_url, data=json.dumps(data), headers=headers)
    
    if response.status_code == 204:
        print("Notification sent successfully to Discord.")
    else:
        print(f"Failed to send notification. Status code: {response.status_code}, Response: {response.text}")

def create_base_embed(args, notification_type):
    """Create base embed structure common to all media types."""
    embed = {
        "title": get_embed_title(args, notification_type),
        "url": args.plex_url,
        "author": {
            "name": f"Plex: New {notification_type.capitalize()} Added",
            "icon_url": AUTHOR_ICON_URL
        },
        "fields": [
            {
                "name": "Summary",
                "value": args.summary,
                "inline": False
            }
        ],
        "color": 0xE5A00D,  # Plex orange
        "thumbnail": {
            "url": args.poster_url
        }
    }

    # Add links if available with uppercase service names
    links = []
    link_mapping = {
        'imdb_url': 'IMDb',
        'themoviedb_url': 'TMDB',
        'thetvdb_url': 'TVDB',
        'trakt_url': 'Trakt'
    }
    
    for url_arg, display_name in link_mapping.items():
        url = getattr(args, url_arg, None)
        if url:
            links.append(f"[{display_name}]({url})")
    
    if links:
        embed["fields"].append({
            "name": "Links",
            "value": " • ".join(links),
            "inline": True
        })
        
    # Add media-specific fields
    if notification_type == "season":
        embed["fields"].append({
            "name": "Episodes",
            "value": args.episode_count,
            "inline": True
        })
    
    return embed

def get_embed_title(args, media_type):
    """Generate appropriate title based on media type."""
    if media_type == "movie":
        return f"{args.title} ({args.year})"
    elif media_type == "episode":
        return f"{args.title} (S{args.season_num00}E{args.episode_num00})"
    return args.title  # For season

def validate_args(args, media_type):
    """Validate required arguments for each media type."""
    if media_type == "movie" and not args.year:
        print("Error: Year is required for movies")
        return False
    elif media_type == "episode" and not all([args.season_num00, args.episode_num00]):
        print("Error: Season and episode numbers are required for episodes")
        return False
    elif media_type == "season" and not all([args.season_num00, args.episode_count]):
        print("Error: Season number and episode count are required for seasons")
        return False
    return True

def main():
    """Main function to handle arguments and send appropriate notification."""
    parser = argparse.ArgumentParser()
    
    # Required arguments for all media types
    parser.add_argument('--media_type', required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--summary', required=True)
    parser.add_argument('--poster_url', required=True)
    parser.add_argument('--plex_url', required=True)
    
    # Media-specific arguments
    parser.add_argument('--year')  # For movies
    parser.add_argument('--season_num00')  # For episodes and seasons
    parser.add_argument('--episode_num00')  # For episodes
    parser.add_argument('--episode_count')  # For seasons
    
    # Optional link arguments
    parser.add_argument('--imdb_url')
    parser.add_argument('--themoviedb_url')
    parser.add_argument('--thetvdb_url')
    parser.add_argument('--trakt_url')
    
    args = parser.parse_args()
    
    media_type = args.media_type.lower()
    
    if media_type not in ['movie', 'episode', 'season']:
        print(f"Error: Unsupported media type: {media_type}")
        return
    
    if not validate_args(args, media_type):
        return
    
    # Create and send the embed
    print(f"Sending notification for {media_type}...")
    print(f"Title: {args.title}")
    
    embed = create_base_embed(args, media_type)
    send_discord_webhook(embed, DISCORD_WEBHOOK_URL)

if __name__ == '__main__':
    main()