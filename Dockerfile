FROM python:3.11.0-alpine3.17

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apk add --no-cache --virtual .deps g++ gcc musl-dev python3-dev libffi-dev openssl-dev cargo pkgconfig
RUN apk add libpq-dev

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

RUN apk del .deps

COPY app ./app

RUN mkdir -p config
VOLUME /config

USER 999

ENV PATH="/opt/venv/bin:${PATH}"

CMD [ "python", "./app/main.py", "--config-file", "/config/config.yml"]
