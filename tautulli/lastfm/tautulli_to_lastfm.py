#!/usr/bin/env python3

"""
Tautulli Last.FM Scrobbler
Sends scrobbles from Plexamp to Last.fm, only keeps the first artist like Spotify.

Tautulli setup:

Add a new notification agent (Script):

Triggers -> Playback Start, Playback Resume  
Conditions -> Library Name is Music (or your library name)  
Arguments -> Playback Start -> Script Arguments:
start "{track_artist}" "{track_name}" "{album_name}" "{duration}"  
Arguments -> Playback Resume -> Script Arguments:
start "{track_artist}" "{track_name}" "{album_name}" "{duration}"

Add a second notification agent (Script):

Triggers -> Playback Stop  
Conditions -> Library Name is Music (or your library name)  
Progress Percent is greater than 80 (or your own value)  
Condition Logic {1} and {2}  
Arguments -> Playback Stop:
stop "{track_artist}" "{track_name}" "{album_name}" "{duration}"

---

How to get a Last.fm SESSION_KEY (required for scrobbling):

1. Go to the Last.fm API authorization page in your browser:
   https://www.last.fm/api/auth/?api_key=YOUR_API_KEY

2. Log in and authorize your application.

3. You will get a token in the URL (e.g., ?token=XXXXXXXX).

4. Exchange the token for a session key by making a GET request:
   https://ws.audioscrobbler.com/2.0/?method=auth.getSession&api_key=YOUR_API_KEY&token=YOUR_TOKEN&api_sig=SIGNATURE&format=json

   Where SIGNATURE is:
       md5("api_keyYOUR_API_KEYmethodauth.getSessionYOUR_API_SECRET")

5. The JSON response will contain:
       "key": "YOUR_SESSION_KEY"

6. Copy this session key into config/config.py as SESSION_KEY.

---

Optional:

- You can add artists that should not be split in config.py under ARTIST_WHITELIST:
    e.g. ["Simon & Garfunkel", "Earth, Wind & Fire"]

"""

import sys
import os
import time
import hashlib
import urllib.parse
import urllib.request
import re

# ---------------- CONFIG ----------------
CONFIG_DIR = "config"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.py")

# If config doesn't exist, create it with placeholders
if not os.path.exists(CONFIG_FILE):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(
            "# config.py - Fill in your Last.fm credentials\n"
            "API_KEY = 'YOUR_API_KEY'\n"
            "API_SECRET = 'YOUR_API_SECRET'\n"
            "SESSION_KEY = 'YOUR_SESSION_KEY'\n\n"
            "# Artists that should not be split\n"
            "ARTIST_WHITELIST = [\n"
            "    'Simon & Garfunkel',\n"
            "    'Earth, Wind & Fire',\n"
            "    # Add more artists here\n"
            "]\n"
        )
    print(f"Config file created at {CONFIG_FILE}. Please fill in your API_KEY, API_SECRET, SESSION_KEY.")
    sys.exit(1)

# Import the config
from config.config import API_KEY, API_SECRET, SESSION_KEY, ARTIST_WHITELIST

# API endpoint
API_URL = "https://ws.audioscrobbler.com/2.0/"

# ---------------- FUNCTIONS ----------------
def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def clean_artist(artist):
    # If artist is in whitelist, return as-is
    if artist in ARTIST_WHITELIST:
        return artist

    patterns = [
        r" & ",
        r",",
        r" feat\. ",
        r" ft\. ",
        r" featuring "
    ]
    for p in patterns:
        artist = re.split(p, artist, flags=re.IGNORECASE)[0]
    return artist.strip()

def sign(params):
    sig = ""
    for key in sorted(params):
        sig += key + params[key]
    sig += API_SECRET
    return md5(sig)

def post(params):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data)
    with urllib.request.urlopen(req, timeout=10):
        pass

# ---------------- MAIN ----------------
def main():
    event = sys.argv[1]

    base = {
        "api_key": API_KEY,
        "sk": SESSION_KEY,
    }

    # ▶ START (now playing)
    if event == "start":
        artist = clean_artist(sys.argv[2])
        track = sys.argv[3]
        album = sys.argv[4]
        duration = sys.argv[5]

        params = {
            **base,
            "method": "track.updateNowPlaying",
            "artist": artist,
            "track": track,
            "duration": duration,
        }
        if album:
            params["album"] = album

    # ⏹ STOP (scrobble)
    elif event == "stop":
        artist = clean_artist(sys.argv[2])
        track = sys.argv[3]
        album = sys.argv[4]

        params = {
            **base,
            "method": "track.scrobble",
            "artist": artist,
            "track": track,
            "timestamp": str(int(time.time())),
        }
        if album:
            params["album"] = album

    else:
        sys.exit(0)

    params["api_sig"] = sign(params)
    params["format"] = "json"
    post(params)

if __name__ == "__main__":
    main()