FROM python:3.11.0-alpine3.17

ENV POETRY_HOME=/opt/poetry
ENV POETRY_VENV=/opt/poetry-venv
ENV POETRY_CACHE_DIR=/opt/.cache

#RUN apk add --no-cache libpq musl-dev postgresql-dev openssl-dev libffi-dev g++
RUN apk add --no-cache --virtual .deps py-pip python3-dev libffi-dev openssl-dev gcc libc-dev rust cargo make ruby ca-certificates

RUN python3 -m venv ${POETRY_VENV} \
    && ${POETRY_VENV}/bin/pip install --upgrade pip setuptools wheel

ENV PATH="${PATH}:${POETRY_VENV}/bin"

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN ${POETRY_VENV}/bin/pip install poetry
RUN poetry install --no-root --only main

RUN apk del .deps

COPY app ./app

RUN mkdir -p config
VOLUME /config

USER 999

CMD [ "poetry", "run", "python", "./app/main.py", "--config-file", "/config/config.yml"]