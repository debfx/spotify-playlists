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
    "user-follow-read",
    "user-follow-modify",
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
        # The track object might be nested under "item" (new Web API rules) or "track" (legacy or saved tracks)
        track = item.get("item") or item.get("track")

        if track is None:
            # some playlists have extra "null" tracks (without any information), just skip them
            continue
        artists = ";".join([artist["name"] for artist in track["artists"]])
        result.append({"title": track["name"], "artists": artists, "uri": track["uri"]})

    return result


def write_playlist(name, dirname, tracks, type, location=None, public=False, collaborative=False):
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(PLAYLIST_TEMPLATE)
    content = template.render(
        title=name,
        location=location,
        tracklist=tracks,
        type=type,
        public=public,
        collaborative=collaborative,
    )

    xspf_path = "{}/{}.xspf".format(dirname, name.replace("/", "_"))

    with open(xspf_path, "w", encoding="utf-8") as f:
        f.write(content)


def export_playlists(sp, username, dirname):
    if not os.path.isdir(dirname):
        os.mkdir(dirname)

    # Retrieve canonical User ID from Spotify directly to handle cases where
    # the configured username in auth.ini is an email address or display name.
    try:
        current_user_id = sp.current_user()["id"]
    except Exception:
        current_user_id = username

    playlists = sp.current_user_playlists()
    playlist_items = playlists["items"]
    while playlists["next"]:
        playlists = sp.next(playlists)
        playlist_items.extend(playlists["items"])

    for playlist in playlist_items:
        # playlist sometimes contain null entries, skip them
        if playlist is None:
            continue

        # Spotify API February 2026 update: Playlist contents (items) are only available
        # for playlists the user owns or collaborates on.
        is_owner = playlist.get("owner", {}).get("id") == current_user_id
        is_collaborative = playlist.get("collaborative", False)
        if not (is_owner or is_collaborative):
            print(f"Skipping playlist '{playlist['name']}' as the user does not own or collaborate on it.", file=sys.stderr)
            continue

        try:
            tracks = sp.playlist_items(
                playlist["id"],
                fields="items(item(name,artists(name),uri)),next",
            )
            tracks_processed = process_tracks(tracks)
            while tracks["next"]:
                tracks = sp.next(tracks)
                tracks_processed.extend(process_tracks(tracks))
        except spotipy.SpotifyException as e:
            print(f"Error fetching tracks for playlist '{playlist['name']}': {e}", file=sys.stderr)
            continue

        write_playlist(
            playlist["name"],
            dirname,
            tracks_processed,
            type="playlist",
            location=playlist["uri"],
            public=playlist["public"],
            collaborative=playlist["collaborative"],
        )

    tracks = sp.current_user_saved_tracks()
    tracks_processed = process_tracks(tracks)
    while tracks["next"]:
        tracks = sp.next(tracks)
        tracks_processed.extend(process_tracks(tracks))
    write_playlist("Saved tracks", dirname, tracks_processed, type="saved_tracks")

    try:
        albums = sp.current_user_saved_albums()
        albums_processed = []
        while albums:
            for item in albums["items"]:
                album = item["album"]
                if album is None:
                    continue
                artists = ";".join([artist["name"] for artist in album["artists"]])
                albums_processed.append({"title": album["name"], "artists": artists, "uri": album["uri"]})
            if albums["next"]:
                albums = sp.next(albums)
            else:
                break
        write_playlist("Saved albums", dirname, albums_processed, type="saved_albums")
    except spotipy.SpotifyException as e:
        print(f"Error fetching saved albums: {e}", file=sys.stderr)

    try:
        artists_processed = []
        results = sp.current_user_followed_artists(limit=50)
        while results and "artists" in results:
            artists_list = results["artists"]["items"]
            for artist in artists_list:
                artists_processed.append({
                    "title": artist["name"],
                    "artists": artist["name"],
                    "uri": artist["uri"]
                })
            after = results["artists"]["cursors"]["after"]
            if after:
                results = sp.current_user_followed_artists(limit=50, after=after)
            else:
                break
        write_playlist("Followed artists", dirname, artists_processed, type="followed_artists")
    except spotipy.SpotifyException as e:
        print(f"Error fetching followed artists: {e}", file=sys.stderr)

    try:
        shows = sp.current_user_saved_shows()
        shows_processed = []
        while shows:
            for item in shows["items"]:
                show = item["show"]
                if show is None:
                    continue
                shows_processed.append({
                    "title": show["name"],
                    "artists": show.get("publisher", ""),
                    "uri": show["uri"]
                })
            if shows["next"]:
                shows = sp.next(shows)
            else:
                break
        write_playlist("Followed podcasts", dirname, shows_processed, type="followed_podcasts")
    except spotipy.SpotifyException as e:
        print(f"Error fetching followed podcasts: {e}", file=sys.stderr)

    try:
        episodes = sp.current_user_saved_episodes()
        episodes_processed = []
        while episodes:
            for item in episodes["items"]:
                episode = item["episode"]
                if episode is None:
                    continue
                show_name = episode.get("show", {}).get("name", "")
                episodes_processed.append({
                    "title": episode["name"],
                    "artists": show_name,
                    "uri": episode["uri"]
                })
            if episodes["next"]:
                episodes = sp.next(episodes)
            else:
                break
        write_playlist("Liked podcasts", dirname, episodes_processed, type="liked_podcasts")
    except spotipy.SpotifyException as e:
        print(f"Error fetching liked podcasts: {e}", file=sys.stderr)


def import_playlist(sp, username, filename):
    tree = xml.etree.ElementTree.parse(filename)
    root = tree.getroot()

    name = root.find("{http://xspf.org/ns/0/}title").text
    tracks = []
    public = False
    collaborative = False
    playlist_type = "playlist"

    for elem in root.findall("{http://xspf.org/ns/0/}trackList/{http://xspf.org/ns/0/}track"):
        location = elem.find("{http://xspf.org/ns/0/}location").text
        tracks.append(location)

    elem_extension = root.find(
        "{http://xspf.org/ns/0/}extension[@application='https://github.com/debfx/spotify-playlists']"
    )
    if elem_extension is not None:
        elem_public = elem_extension.find("{http://xspf.org/ns/0/}public")
        if elem_public is not None:
            public = elem_public.text.lower() == "true"

        elem_collaborative = elem_extension.find("{http://xspf.org/ns/0/}collaborative")
        if elem_collaborative is not None:
            collaborative = elem_collaborative.text.lower() == "true"

        elem_type = elem_extension.find("{http://xspf.org/ns/0/}type")
        if elem_type is not None:
            playlist_type = elem_type.text

    # docs say limit is 50 but we get an error if more than 40
    if playlist_type == "saved_tracks":
        # Save tracks directly to user's library in chunks of 40 (API limit)
        for tracks_chunk in chunks(tracks, 40):
            sp.current_user_saved_tracks_add(tracks_chunk)
    elif playlist_type == "saved_albums":
        # Save albums directly to user's library in chunks of 40 (API limit)
        for albums_chunk in chunks(tracks, 40):
            sp.current_user_saved_albums_add(albums_chunk)
    elif playlist_type == "followed_artists":
        # Follow artists directly in chunks of 40 (API limit)
        for artists_chunk in chunks(tracks, 40):
            sp.user_follow_artists(artists_chunk)
    elif playlist_type == "followed_podcasts":
        # Follow podcast shows directly to user's library in chunks of 40 (API limit)
        for shows_chunk in chunks(tracks, 40):
            sp.current_user_saved_shows_add(shows_chunk)
    elif playlist_type == "liked_podcasts":
        # Save episodes directly to user's library in chunks of 40 (API limit)
        for episodes_chunk in chunks(tracks, 40):
            sp.current_user_saved_episodes_add(episodes_chunk)
    else:
        # Use current_user_playlist_create instead of deprecated user_playlist_create
        # which used the removed POST /users/{user_id}/playlists endpoint.
        playlist_id = sp.current_user_playlist_create(name, public=public, collaborative=collaborative)["id"]

        # the Spotify API allows only 100 tracks per request
        for tracks_chunk in chunks(tracks, 100):
            sp.playlist_add_items(playlist_id, tracks_chunk)


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
