FROM vllm/vllm-openai-cpu:v0.31.0-x86_64

ARG APP_UID=10001
ARG APP_GID=10001

USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HF_HOME=/home/app/.cache/huggingface \
    VLLM_CACHE_ROOT=/home/app/.cache/vllm \
    VLLM_LOGGING_LEVEL=INFO

RUN groupadd \
        --gid "${APP_GID}" \
        app \
    && useradd \
        --uid "${APP_UID}" \
        --gid "${APP_GID}" \
        --create-home \
        --home-dir /home/app \
        --shell /usr/sbin/nologin \
        app \
    && mkdir -p \
        /app/config \
        /app/src \
        /home/app/.cache/huggingface \
        /home/app/.cache/vllm \
        /models \
        /tmp/vllm \
    && chown -R "${APP_UID}:${APP_GID}" \
        /app \
        /home/app \
        /models \
        /tmp/vllm

COPY --chown=10001:10001 \
    config/logging_config.json \
    /app/config/logging_config.json

COPY --chown=10001:10001 \
    src/redacting_filter.py \
    /app/src/redacting_filter.py

COPY requirements.txt /app/requirements.txt

RUN python -m pip check

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["vllm", "serve"]