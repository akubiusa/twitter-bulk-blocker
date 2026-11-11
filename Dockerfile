FROM python:3.15.2-slim

WORKDIR /app

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tzdata && \
    ln -snf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime && \
    echo "Asia/Tokyo" > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Tokyo \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TWITTER_COOKIES_PATH=/data/cookies.json \
    TWITTER_USERS_FILE=/data/users.json \
    TWITTER_BLOCK_DB=/data/block_history.db \
    CACHE_DIR=/data/cache

COPY requirements.txt ./

RUN python -m pip install --no-cache-dir --upgrade pip==26.2.2 && \
    pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/data && \
    chown -R appuser:appuser /app

COPY --chown=appuser:appuser twitter_blocker/ ./twitter_blocker/
COPY --chown=appuser:appuser README.md examples.md ./

# Embed the version in the image when CI passes APPLICATION_VERSION
ARG APPLICATION_VERSION
RUN if [ -n "$APPLICATION_VERSION" ]; then \
        echo "$APPLICATION_VERSION" > .app-version && \
        echo "✅ Version embedded: $APPLICATION_VERSION"; \
    else \
        echo "ℹ️ No APPLICATION_VERSION provided, using runtime version detection"; \
    fi

USER appuser

VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python3 -c "import sys; sys.exit(0)"

ENTRYPOINT ["python3", "-m", "twitter_blocker"]
CMD ["--help"]