FROM python:3.11-slim-bullseye

ENV POETRY_HOME=/opt/poetry
ENV POETRY_VENV=/opt/poetry-venv
ENV POETRY_CACHE_DIR=/opt/.cache

RUN apt update && apt upgrade

RUN apt install libffi-dev openssl-dev gcc libc-dev g++

RUN python3 -m venv ${POETRY_VENV} \
    && ${POETRY_VENV}/bin/pip install --upgrade pip setuptools wheel

ENV PATH="${PATH}:${POETRY_VENV}/bin"

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN ${POETRY_VENV}/bin/pip install poetry
RUN poetry install --no-root --only main

COPY app ./app

RUN mkdir -p config
VOLUME /config

USER 999

CMD [ "poetry", "run", "python", "./app/main.py", "--config-file", "/config/config.yml"]