FROM amazon/aws-lambda-python:3.13-arm64

COPY . ${LAMBDA_TASK_ROOT}
COPY src/ ${LAMBDA_TASK_ROOT}/src
WORKDIR ${LAMBDA_TASK_ROOT}
RUN pip install --upgrade pip
RUN pip install poetry
RUN poetry install --no-root
RUN poetry export -f requirements.txt --output requirements.txt
RUN pip install -r requirements.txt