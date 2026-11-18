FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir uv && uv sync --locked --no-dev
COPY --from=web /web/dist/ /app/apps/web/dist/
ENV ACCELERATOR_STATE_DIR=/data
ENV ACCELERATOR_WEB_ROOT=/app/apps/web/dist
EXPOSE 8050
VOLUME /data
CMD ["uv", "run", "--no-sync", "uvicorn", "accelerator.api:app", "--host", "0.0.0.0", "--port", "8050"]
