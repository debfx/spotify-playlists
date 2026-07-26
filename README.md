# Spotify Playlists

Import / export Spotify playlists


## Usage

    ./spotify-playlists.py <import FILENAME / export DIR>

Examples:

* `./spotify-playlists.py export playlists`
* `./spotify-playlists.py import playlists/MyPlaylist.xspf`


## Install

* [uv](https://github.com/astral-sh/uv) must be installed
* `uv sync --locked`


## Setup

* Create an app on [Spotify My Dashboard](https://developer.spotify.com/dashboard/applications)
* Set Redirect URI to `http://127.0.0.1:8080/`
* Copy auth.ini.example to auth.ini
* Insert the client id, token, redirect uri and Spotify username in auth.ini
