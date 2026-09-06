# tidal-automation

Rebuilds two Tidal playlists on a daily schedule, each as its own AWS Lambda deployed with CDK:

* **Daily Blend** — from Tidal's Daily Discover and New Arrivals mixes plus last.fm recommendations.
* **Darkroom** — the tracks themselves, taken from the tracklists of recent Dub Techno mixes on
  [MixesDB](https://www.mixesdb.com) and ranked by how strongly each track's Tidal radio neighbourhood is
  tagged like the genre the search asked for, then annealed to a tempo span one Technics pitch fader can
  bridge.

Both rebuild differentially: a track that survives an update keeps its original date-added, so sorting the
playlist by that shows what is new and what has been hanging around.

## Requirements
* Python 3.13
    * [pyenv](https://github.com/pyenv/pyenv?tab=readme-ov-file#installation) recommended for managing Python versions
* [Poetry](https://python-poetry.org/docs/#installation) for virtualenv & dependency management
* [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html) and Docker, to synth, diff and deploy
* [just](https://just.systems/man/en/packages.html) to run the tasks below

## Setup
```shell
just install
```

## Configuration
Local runs read these from a `.env` in the project root:
* `TIDAL_REFRESH_TOKEN` — log in with `just token` to print one
* `DAILY_DISCOVER_MIX_ID` — the Tidal mix the blend starts from
* `NEW_ARRIVALS_MIX_ID` — the Tidal mix the blend is topped up from, alongside last.fm
* `DAILY_BLEND_PLAYLIST_ID` — the playlist to rewrite
* `DAILY_BLEND_SIZE` — how many tracks to fill it up to
* `DARKROOM_PLAYLIST_ID` — the Darkroom playlist to rewrite; create it by hand in Tidal first
* `DARKROOM_SIZE` — how many tracks to fill it up to
* `LASTFM_API_KEY` — used by both playlists
* `DISCOGS_TOKEN` — optional; without it Discogs runs at the anonymous 25/min rate

The deployed Lambda takes the same settings from `aws/main.py`, apart from the refresh token,
which it reads from its Secrets Manager secret. CDK creates that secret with a generated placeholder
value, so after the first `just deploy` set it to `{"TIDAL_REFRESH_TOKEN": "<token from just token>"}`.

## Run locally
```shell
just daily-blend
just darkroom
```

## Checks
```shell
just check
```
Runs `lint`, `types`, `test` and `synth`; each is also its own recipe.

## Deploy
```shell
just deploy
```
