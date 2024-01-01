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
import spotipy.util

SCOPES = (
    "playlist-read-collaborative",
    "playlist-read-private",
    "user-library-read",
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
        yield lst[i:i+n]


def process_tracks(tracks):
    result = []

    for item in tracks["items"]:
        track = item["track"]

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
        collaborative=collaborative
    )

    xspf_path = "{}/{}.xspf".format(dirname, name.replace("/", "_"))

    with open(xspf_path, "w") as f:
        f.write(content)


def export_playlists(sp, username, dirname):
    if not os.path.isdir(dirname):
        os.mkdir(dirname)

    playlists = sp.user_playlists(username)

    for playlist in playlists["items"]:
        tracks = sp.playlist_tracks(
            playlist["id"],
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
            collaborative=playlist["collaborative"]
        )

    tracks = sp.current_user_saved_tracks()
    tracks_processed = process_tracks(tracks)
    while tracks["next"]:
        tracks = sp.next(tracks)
        tracks_processed.extend(process_tracks(tracks))
    write_playlist("Saved tracks", dirname, tracks_processed, type="saved_tracks")


def import_playlist(sp, username, filename):
    tree = xml.etree.ElementTree.parse(filename)
    root = tree.getroot()

    name = root.find("{http://xspf.org/ns/0/}title").text
    tracks = []
    public = False
    collaborative = False

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

    playlist_id = sp.user_playlist_create(username, name, public=public)["id"]
    if collaborative:
        sp.user_playlist_change_details(username, playlist_id, collaborative=collaborative)

    # the Spotify API allows only 100 tracks per request
    for tracks_chunk in chunks(tracks, 100):
        sp.user_playlist_add_tracks(username, playlist_id, tracks_chunk)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("import", "export"):
        print("Usage: {} <import FILENAME / export DIR>".format(sys.argv[0]), file=sys.stderr)
        sys.exit(0)

    command = sys.argv[1]
    arg = sys.argv[2]

    config = configparser.ConfigParser()
    config.read(CONFIG_AUTH)

    token = spotipy.util.prompt_for_user_token(
        config["spotify"]["username"],
        " ".join(SCOPES),
        config["spotify"]["client_id"],
        config["spotify"]["client_secret"],
        config["spotify"]["redirect_uri"]
    )
    sp = spotipy.Spotify(auth=token)

    if command == "import":
        import_playlist(sp, config["spotify"]["username"], arg)
    else:
        export_playlists(sp, config["spotify"]["username"], arg)


if __name__ == "__main__":
    main()
