FROM amazon/aws-lambda-python:3.13-arm64

COPY pyproject.toml poetry.lock ${LAMBDA_TASK_ROOT}/
COPY src/ ${LAMBDA_TASK_ROOT}/src
WORKDIR ${LAMBDA_TASK_ROOT}
RUN pip install --upgrade pip
RUN pip install poetry
RUN poetry self add poetry-plugin-export
RUN poetry config virtualenvs.create false
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes
RUN pip install -r requirements.txt
COPY . ${LAMBDA_TASK_ROOT}