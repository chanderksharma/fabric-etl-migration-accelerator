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
RUN pip install --no-cache-dir uv \
    && uv export --frozen --no-dev --no-emit-workspace --no-emit-project -o /tmp/requirements.txt \
    && uv build --all-packages --wheel --out-dir /wheels

FROM python:3.13-slim
WORKDIR /app
COPY --from=wheels /tmp/requirements.txt /tmp/requirements.txt
COPY --from=wheels /wheels/*.whl /tmp/wheels/
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/requirements.txt /tmp/wheels
COPY --from=web /web/dist/ /app/apps/web/dist/
ENV ACCELERATOR_STATE_DIR=/data
ENV ACCELERATOR_WEB_ROOT=/app/apps/web/dist
EXPOSE 8050
VOLUME /data
CMD ["uvicorn", "accelerator.api:app", "--host", "0.0.0.0", "--port", "8050"]
