# tidal-automation

Rebuilds two Tidal playlists on a daily schedule, each as its own AWS Lambda deployed with CDK:

* **Daily Blend** — from Tidal's Daily Discover and New Arrivals mixes plus last.fm recommendations.
* **Dub Techno** — from the tracklists of the currently hottest Dub Techno DJ mixes on
  [MixesDB](https://www.mixesdb.com), picked by a weighted lottery that favours hotter and more recent mixes
  and heavily discounts mixes tagged Ambient or IDM.

* **Berghain Sound** — high-energy Berlin techno, from MixesDB mixes tagged `Techno` with any tracklist and
  `Berlin` in the title: Tresor, RSO, HÖR, Boiler Room, Berghain and others. Mixes tagged `Dub`,
  `Dub Techno`, `Minimal` or `Ambient` are excluded outright, and the lottery is weighted toward recent
  mixes.

All three rebuild differentially: a track that survives an update keeps its original date-added, so sorting
the playlist by that shows what is new and what has been hanging around.

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
* `DUB_TECHNO_PLAYLIST_ID` — the Dub Techno playlist to rewrite; create it by hand in Tidal first
* `DUB_TECHNO_SIZE` — how many tracks to fill it up to
* `BERGHAIN_SOUND_PLAYLIST_ID` — the Berghain Sound playlist to rewrite; create it by hand in Tidal first
* `BERGHAIN_SOUND_SIZE` — how many tracks to fill it up to

The deployed Lambda takes the same settings from `aws/main.py`, apart from the refresh token,
which it reads from its Secrets Manager secret. CDK creates that secret with a generated placeholder
value, so after the first `just deploy` set it to `{"TIDAL_REFRESH_TOKEN": "<token from just token>"}`.

## Run locally
```shell
just daily-blend
just dub-techno
just berghain-sound
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
