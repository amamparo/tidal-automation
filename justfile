python := 'poetry run python'
sources := 'src tests aws'

[private]
default:
    @just --list

install:
    poetry config virtualenvs.in-project true --local
    @if [ ! -d .venv ]; then poetry env remove --all 2>/dev/null || true; fi
    poetry install --no-root

lint:
    poetry run pylint {{ sources }}

types:
    poetry run mypy {{ sources }}

test:
    {{ python }} -m unittest discover -s tests -p '*.py'

synth:
    cdk synth -q

check: lint types test synth

diff:
    cdk diff

secrets:
    {{ python }} -m util.sync_secrets

deploy: && secrets
    cdk deploy --require-approval never

token:
    {{ python }} -m util.make_refresh_token

daily-blend:
    {{ python }} -m src.update_daily_blend

dub-techno:
    {{ python }} -m src.update_dub_techno
