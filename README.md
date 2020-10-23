# Spotify Playlists

Import / export Spotify playlists


## Usage

    ./spotify-playlists.py <import FILENAME / export DIR>

Examples:

* `./spotify-playlists.py export playlists`
* `./spotify-playlists.py import playlists/MyPlaylist.xspf`


## Install

* `python3 -m venv --system-site-packages venv`
* `venv/bin/pip install -r requirements.txt`


## Setup

* Create an app on [Spotify My Dashboard](https://developer.spotify.com/dashboard/applications)
* Redirect URI can be anything (e.g. `http://localhost/`)
* Copy auth.ini.example to auth.ini
* Insert the client id, token, redirect uri and Spotify username in auth.ini
