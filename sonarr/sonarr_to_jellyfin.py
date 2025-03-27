#!/usr/bin/env python3
import http.client
import os

"""
This script triggers a library scan in Jellyfin when Sonarr imports or deletes a new episode.

Fill in the variables below and and set up a custom script in Sonarr Connect.
In Sonarr, go to Settings > Connect > Custom Script > Add a new custom script
Name: Jellyfin Library Scan
Notification Triggers: On Import Complete, On Rename, On Series Delete, On Episode File Delete, On Episode File Delete For Upgrade
Path: sonarr/sonarr_to_jellyfin.py
"""

# Configuration
JELLYFIN_HOST = ""  # Change this to your Jellyfin server IP
JELLYFIN_PORT = 8096  # Change if your port is different
API_KEY = ""  # Replace with your Jellyfin API key
LIBRARY_ID = ""  # Get the ID from Jellyfin's API or dashboard

def trigger_library_scan():
    conn = http.client.HTTPConnection(JELLYFIN_HOST, JELLYFIN_PORT)
    headers = {
        "X-Emby-Token": API_KEY,
        "Content-Type": "application/json",
    }
    
    url = f"/Library/Refresh?libraryId={LIBRARY_ID}"
    
    try:
        conn.request("POST", url, headers=headers)
        response = conn.getresponse()
        
        if response.status == 204:
            print("Jellyfin TV Show library scan triggered successfully.")
        else:
            print(f"Failed to trigger Jellyfin scan: {response.status} {response.reason}")
    
    except Exception as e:
        print(f"Error triggering Jellyfin scan: {e}")
    
    finally:
        conn.close()

if __name__ == "__main__":
    # Get the event type from Sonarr
    sonarr_event = os.getenv("sonarr_eventtype")

    if sonarr_event == "Test":
        print("Test event received. Script executed successfully.")
    elif sonarr_event in {"Download", "Rename", "EpisodeFileDelete", "SeriesDelete"}:
        trigger_library_scan()
    else:
        print(f"Unhandled event type: {sonarr_event}")