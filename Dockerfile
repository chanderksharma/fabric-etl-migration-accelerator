FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.13-slim AS wheels
WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY packages/ ./packages/
RUN pip install --no-cache-dir "uv>=0.7,<1" \
    && uv export --frozen --no-dev --no-emit-workspace --no-emit-project -o /tmp/requirements.txt \
    && uv build --all-packages --wheel --out-dir /wheels

FROM python:3.13-slim
WORKDIR /app
RUN groupadd --system accelerator \
    && useradd --system --gid accelerator --home-dir /app --no-create-home accelerator \
    && mkdir -p /data \
    && chown accelerator:accelerator /app /data
COPY --from=wheels /tmp/requirements.txt /tmp/requirements.txt
COPY --from=wheels /wheels/*.whl /tmp/wheels/
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/requirements.txt /tmp/wheels
COPY --from=web --chown=accelerator:accelerator /web/dist/ /app/apps/web/dist/
ENV ACCELERATOR_MODE=server
ENV ACCELERATOR_ALLOW_LOCAL_FILESYSTEM=false
ENV ACCELERATOR_STATE_DIR=/data
ENV ACCELERATOR_WEB_ROOT=/app/apps/web/dist
USER accelerator
EXPOSE 8050
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8050/health', timeout=3)"
CMD ["uvicorn", "accelerator.api:app", "--host", "0.0.0.0", "--port", "8050"]
