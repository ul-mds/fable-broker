# python:3.13.14-slim
FROM python@sha256:eb43ff125d8d58d7449dcba7d336c23bcac412f526d861db493b9994d8010280 AS builder

WORKDIR /tmp

COPY ./poetry.lock ./pyproject.toml /tmp/

RUN set -ex && \
  python -m pip install --disable-pip-version-check --no-cache-dir poetry==2.4.1 && \
  poetry self add poetry-plugin-export==1.10.0 && \
  poetry export -n -f requirements.txt -o requirements.txt

# python:3.13.14-slim
FROM python@sha256:eb43ff125d8d58d7449dcba7d336c23bcac412f526d861db493b9994d8010280

WORKDIR /app

RUN mkdir logs

COPY --from=builder /tmp/requirements.txt ./
COPY ./config/logging.yaml ./config/logging.yaml
COPY ./fable_broker ./fable_broker

RUN set -ex && \
  groupadd --system nonroot && \
  useradd --system --gid nonroot --create-home nonroot && \
  chown -R nonroot:nonroot /app

RUN set -ex && \
  python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080/tcp

USER nonroot
