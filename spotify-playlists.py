#!/usr/bin/env python3

# Copyright (C) 2017 Felix Geyer <debfx@fobos.de>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 or (at your option)
# version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import configparser
import os
import sys
import xml.etree.ElementTree

import jinja2
import spotipy
import spotipy.cache_handler
import spotipy.oauth2
import spotipy.util

SCOPES = (
    "playlist-read-collaborative",
    "playlist-read-private",
    "user-library-read",
    "user-library-modify",
    "playlist-modify-private",
    "playlist-modify-public",
)

CONFIG_AUTH = "auth.ini"

PLAYLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<playlist version="1" xmlns="http://xspf.org/ns/0/">
  <title>{{ title }}</title>
{%- if location %}
  <location>{{ location }}</location>
{%- endif %}
  <extension application="https://github.com/debfx/spotify-playlists">
    <public>{{ public | string | lower }}</public>
    <collaborative>{{ collaborative | string | lower }}</collaborative>
    <type>{{ type }}</type>
{%- if owner_id %}
    <owner_id>{{ owner_id }}</owner_id>
{%- endif %}
{%- if is_official %}
    <is_official>{{ is_official | string | lower }}</is_official>
{%- endif %}
  </extension>
  <trackList>
{%- for track in tracklist %}
    <track>
      <title>{{ track.title }}</title>
      <creator>{{ track.artists }}</creator>
      <location>{{ track.uri }}</location>
    </track>
{%- endfor %}
  </trackList>
</playlist>
"""


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def process_tracks(tracks):
    result = []

    for item in tracks["items"]:
        track = item["track"]

        if track is None:
            # some playlists have extra "null" tracks (without any information), just skip them
            continue
        
        # Check if the track has the expected structure
        if "artists" not in track:
            # This is likely a podcast episode, not a music track
            print(f"Info: Found podcast episode instead of track: {track.get('name', 'Unknown')}")
            # Add the episode with appropriate fields
            result.append({
                "title": track.get("name", "Unknown"), 
                "artists": "Podcast Episode", 
                "uri": track.get("uri", "")
            })
            continue
        
        try:
            # Safely extract artist names, ensuring they are all strings
            artist_names = []
            for artist in track["artists"]:
                if artist and "name" in artist and artist["name"] is not None:
                    artist_names.append(str(artist["name"]))
                else:
                    artist_names.append("Unknown Artist")
            
            artists = ";".join(artist_names)
            result.append({
                "title": str(track.get("name", "Unknown")), 
                "artists": artists, 
                "uri": str(track.get("uri", ""))
            })
        except Exception as e:
            print(f"Warning: Error processing track '{track.get('name', 'Unknown')}': {e}")
            # Add the track with fallback values
            result.append({
                "title": str(track.get("name", "Unknown")), 
                "artists": "Unknown Artist", 
                "uri": str(track.get("uri", ""))
            })

    return result


def write_playlist(name, dirname, tracks, type, location=None, public=False, collaborative=False, owner_id=None, is_official=False):
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(PLAYLIST_TEMPLATE)
    content = template.render(
        title=name,
        location=location,
        tracklist=tracks,
        type=type,
        public=public,
        collaborative=collaborative,
        owner_id=owner_id,
        is_official=is_official,
    )

    xspf_path = "{}/{}.xspf".format(dirname, name.replace("/", "_"))

    with open(xspf_path, "w") as f:
        f.write(content)


def export_playlists(sp, username, dirname):
    if not os.path.isdir(dirname):
        os.mkdir(dirname)

    playlists = sp.user_playlists(username)
    playlist_items = playlists["items"]
    while playlists["next"]:
        playlists = sp.next(playlists)
        playlist_items.extend(playlists["items"])

    for playlist in playlist_items:
        # playlist sometimes contain null entries, skip them
        if playlist is None:
            continue

        try:
            # Check if this is an official/third-party playlist
            is_official = playlist['owner']['id'] != username
            owner_id = playlist['owner']['id']

            tracks = sp.playlist_items(
                playlist["id"],
                fields="items(track(name,artists(name),uri)),next",
            )
            tracks_processed = process_tracks(tracks)
            while tracks["next"]:
                tracks = sp.next(tracks)
                tracks_processed.extend(process_tracks(tracks))
            write_playlist(
                playlist["name"],
                dirname,
                tracks_processed,
                type="playlist",
                location=playlist["uri"],
                public=playlist["public"],
                collaborative=playlist["collaborative"],
                owner_id=owner_id,
                is_official=is_official,
            )
        except Exception as e:
            print(f"Error processing playlist '{playlist['name']}': {e}")

    try:
        # For saved tracks, ensure we get the right track structure
        tracks = sp.current_user_saved_tracks(limit=50)
        tracks_processed = process_tracks(tracks)
        while tracks["next"]:
            tracks = sp.next(tracks)
            tracks_processed.extend(process_tracks(tracks))
        write_playlist("Saved tracks", dirname, tracks_processed, type="saved_tracks")
    except Exception as e:
        print(f"Error processing saved tracks: {e}")


def import_playlist(sp, username, filename):
    tree = xml.etree.ElementTree.parse(filename)
    root = tree.getroot()

    name = root.find("{http://xspf.org/ns/0/}title").text
    tracks = []
    public = False
    collaborative = False
    is_official = False
    owner_id = None
    playlist_uri = None
    playlist_type = "playlist"  # Default type

    # Get the playlist URI if available
    location_elem = root.find("{http://xspf.org/ns/0/}location")
    if location_elem is not None and location_elem.text:
        playlist_uri = location_elem.text
        print(f"Found playlist URI: {playlist_uri}")

    for elem in root.findall("{http://xspf.org/ns/0/}trackList/{http://xspf.org/ns/0/}track"):
        location = elem.find("{http://xspf.org/ns/0/}location").text
        tracks.append(location)

    # Debug: print extension content
    elem_extension = root.find(
        "{http://xspf.org/ns/0/}extension[@application='https://github.com/debfx/spotify-playlists']"
    )
    
    if elem_extension is not None:
        # Debug output
        print("Extension elements found:")
        for child in elem_extension:
            print(f"  {child.tag}: {child.text}")
        
        # Use proper namespace for elements
        ns_tag = "{http://xspf.org/ns/0/}"
        
        elem_public = elem_extension.find(f"{ns_tag}public")
        if elem_public is not None:
            public = elem_public.text.lower() == "true"

        elem_collaborative = elem_extension.find(f"{ns_tag}collaborative")
        if elem_collaborative is not None:
            collaborative = elem_collaborative.text.lower() == "true"
            
        # Check if this is an official playlist
        elem_official = elem_extension.find(f"{ns_tag}is_official")
        if elem_official is not None:
            is_official = elem_official.text.lower() == "true"
            
        # Get owner ID if available
        elem_owner = elem_extension.find(f"{ns_tag}owner_id")
        if elem_owner is not None:
            owner_id = elem_owner.text
            
        # Get playlist type - this is directly in the extension with namespace
        elem_type = elem_extension.find(f"{ns_tag}type")
        if elem_type is not None:
            playlist_type = elem_type.text
            print(f"Playlist type identified: {playlist_type}")
    
    # Handle Saved Tracks specially
    if playlist_type == "saved_tracks":
        print(f"Importing '{name}' as saved tracks to your library...")
        
        # For saved tracks, we don't follow - we add them to the library
        added_count = 0
        for tracks_chunk in chunks(tracks, 50):  # Use 50 for saved tracks (API limit)
            try:
                sp.current_user_saved_tracks_add(tracks=tracks_chunk)
                added_count += len(tracks_chunk)
                print(f"  Added {added_count}/{len(tracks)} tracks to your Saved Tracks library")
            except Exception as e:
                print(f"  Error adding tracks to library: {e}")
        
        print(f"Finished importing {added_count} tracks to your Saved Tracks library")
        return
            
    # If it's an official playlist and we have the URI, offer to follow it instead
    if playlist_uri:  # We just need the URI, even if is_official is not set
        print(f"\nPlaylist '{name}' with URI {playlist_uri}")
        print("Options:")
        print("1. Follow the original playlist (recommended for official playlists)")
        print("2. Create a new copy (won't get updates from the original)")
        
        choice = input("Enter your choice (1 or 2): ").strip()
        
        if choice == "1":
            # Follow the playlist using its Spotify URI
            try:
                # Extract the playlist ID from the URI (format: spotify:playlist:ID or spotify:user:USER:playlist:ID)
                if ':playlist:' in playlist_uri:
                    playlist_id = playlist_uri.split(':playlist:')[-1]
                else:
                    # Handle older format URIs
                    parts = playlist_uri.split(':')
                    playlist_id = parts[-1]
                
                print(f"Attempting to follow playlist with ID: {playlist_id}")
                sp.current_user_follow_playlist(playlist_id)
                print(f"Successfully followed the original playlist '{name}'.")
                return
            except Exception as e:
                print(f"Error following playlist: {e}")
                print("Falling back to creating a copy...")
        
    # Create a new playlist (either by choice or as fallback)
    print(f"Creating a new playlist copy: {name}")
    playlist_id = sp.user_playlist_create(username, name, public=public)["id"]
    if collaborative:
        sp.user_playlist_change_details(username, playlist_id, collaborative=collaborative)

    # the Spotify API allows only 100 tracks per request
    for tracks_chunk in chunks(tracks, 100):
        sp.user_playlist_add_tracks(username, playlist_id, tracks_chunk)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("import", "export"):
        print(
            "Usage: {} <import FILENAME / export DIR>".format(sys.argv[0]),
            file=sys.stderr,
        )
        sys.exit(0)

    command = sys.argv[1]
    arg = sys.argv[2]

    config = configparser.ConfigParser()
    config.read(CONFIG_AUTH)

    auth_manager = spotipy.oauth2.SpotifyOAuth(
        client_id=config["spotify"]["client_id"],
        client_secret=config["spotify"]["client_secret"],
        redirect_uri=config["spotify"]["redirect_uri"],
        scope=" ".join(SCOPES),
        cache_handler=spotipy.cache_handler.CacheFileHandler(
            username=config["spotify"]["username"],
        ),
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)

    if command == "import":
        import_playlist(sp, config["spotify"]["username"], arg)
    else:
        export_playlists(sp, config["spotify"]["username"], arg)


if __name__ == "__main__":
    main()
