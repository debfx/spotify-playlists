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
import jinja2
import os
import spotipy
import spotipy.util
import sys
import xml.etree.ElementTree

SCOPES = (
    "playlist-read-collaborative",
    "playlist-read-private",
    "user-library-read",
    "playlist-modify-private",
)

CONFIG_AUTH = "auth.ini"

PLAYLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<playlist version="1" xmlns="http://xspf.org/ns/0/">
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


def process_tracks(tracks):
    result = []

    for item in tracks["items"]:
        track = item["track"]
        artists = ";".join([ artist["name"] for artist in track["artists"] ])
        result.append({ "title": track["name"], "artists": artists, "uri": track["uri"] })

    return result


def write_playlist(name, dirname, tracks):
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(PLAYLIST_TEMPLATE)
    content = template.render(tracklist=tracks)

    xspf_path = "{}/{}.xspf".format(dirname, name.replace("/", "_"))



    with open(xspf_path, "w") as f:
        f.write(content)


def export_playlists(sp, username, dirname):
    if not os.path.isdir(dirname):
        os.mkdir(dirname)

    playlists = sp.user_playlists(username)

    for playlist in playlists["items"]:
        results = sp.user_playlist(playlist["owner"]["id"], playlist["id"], fields="tracks,next")
        tracks = results["tracks"]
        tracks_processed = process_tracks(tracks)
        while tracks["next"]:
            tracks = sp.next(tracks)
            tracks_processed.extend(process_tracks(tracks))
        write_playlist(playlist["name"], dirname, tracks_processed)

    results = sp.current_user_saved_tracks()
    tracks_processed = process_tracks(results)
    write_playlist("Saved tracks", dirname, tracks_processed)


def import_playlist(sp, username, filename):
    tree = xml.etree.ElementTree.parse(filename)
    root = tree.getroot()

    name = os.path.splitext(os.path.basename(filename))[0]
    tracks = []

    for elem in root.findall("{http://xspf.org/ns/0/}trackList/{http://xspf.org/ns/0/}track"):
        location = elem.find("{http://xspf.org/ns/0/}location").text
        tracks.append(location)

    playlist_id = sp.user_playlist_create(username, name, public=False)["id"]

    sp.user_playlist_add_tracks(username, playlist_id, tracks)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("import", "export"):
        print("Usage: {} <import FILENAME / export DIR>".format(sys.argv[0]), file=sys.stderr)
        sys.exit(0)

    command = sys.argv[1]
    arg = sys.argv[2]

    config = configparser.ConfigParser()
    config.read(CONFIG_AUTH)

    token = spotipy.util.prompt_for_user_token(config["spotify"]["username"],
                                               " ".join(SCOPES),
                                               config["spotify"]["client_id"],
                                               config["spotify"]["client_secret"],
                                               config["spotify"]["redirect_uri"])
    sp = spotipy.Spotify(auth=token)

    if command == "import":
        import_playlist(sp, config["spotify"]["username"], arg)
    else:
        export_playlists(sp, config["spotify"]["username"], arg)


if __name__ == "__main__":
    main()
