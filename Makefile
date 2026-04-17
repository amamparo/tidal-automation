install:
	poetry config virtualenvs.in-project true --local
	@if [ ! -d .venv ]; then poetry env remove --all 2>/dev/null || true; fi
	poetry install --no-root

lint:
	poetry run pylint src tests aws

types:
	poetry run mypy src tests aws

test:
	poetry run python -m unittest discover -s 'tests' -p '*.py'

synth:
	cdk synth -q

check: lint types test synth

diff:
	cdk diff

deploy:
	cdk deploy --require-approval never

token:
	poetry run python -m util.make_refresh_token

daily_blend:
	poetry run python -m src.update_daily_blend

kexp:
	poetry run python -m src.update_kexp_playlist

kcrw:
	poetry run python -m src.update_kcrw_playlist

colors:
	poetry run python -m src.update_colors_playlist