install:
	poetry install --no-root

run:
	poetry run python -m src.main

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