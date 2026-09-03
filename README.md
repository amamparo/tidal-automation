# tidal-automation

Rebuilds a Tidal "Daily Blend" playlist every day from Tidal's Daily Discover and New Arrivals mixes
plus last.fm recommendations. Runs as a scheduled AWS Lambda deployed with CDK.

## Requirements
* Python 3.13
    * [pyenv](https://github.com/pyenv/pyenv?tab=readme-ov-file#installation) recommended for managing Python versions
* [Poetry](https://python-poetry.org/docs/#installation) for virtualenv & dependency management
* [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html) and Docker, to synth, diff and deploy

## Setup
```shell
make install
```

## Configuration
Local runs read these from a `.env` in the project root:
* `TIDAL_REFRESH_TOKEN` — log in with `make token` to print one
* `DAILY_DISCOVER_MIX_ID` — the Tidal mix the blend starts from
* `NEW_ARRIVALS_MIX_ID` — the Tidal mix the blend is topped up from, alongside last.fm
* `DAILY_BLEND_PLAYLIST_ID` — the playlist to rewrite
* `DAILY_BLEND_SIZE` — how many tracks to fill it up to

The deployed Lambda takes the same settings from `aws/main.py`, apart from the refresh token,
which it reads from its Secrets Manager secret. CDK creates that secret with a generated placeholder
value, so after the first `make deploy` set it to `{"TIDAL_REFRESH_TOKEN": "<token from make token>"}`.

## Run locally
```shell
make daily_blend
```

## Checks
```shell
make check
```
Runs `lint`, `types`, `test` and `synth`; each is also its own target.

## Deploy
```shell
make deploy
```
