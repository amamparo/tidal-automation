# tidal-automation

Rebuilds a Tidal "Daily Blend" playlist every day from Tidal's Daily Discover and New Arrivals mixes
plus last.fm recommendations. Runs as a scheduled AWS Lambda deployed with CDK.

## Requirements
* Python 3.13
    * [pyenv](https://github.com/pyenv/pyenv?tab=readme-ov-file#installation) recommended for managing Python versions
* [Poetry](https://python-poetry.org/docs/#installation) for virtualenv & dependency management

## Setup
```shell
make install
```

## Run locally
```shell
make daily_blend
```

## Deploy
```shell
make deploy
```
