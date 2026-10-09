# --- estágio 1: build do frontend ---
FROM node:20-slim AS web
WORKDIR /src
COPY web/package.json web/package-lock.json* ./web/
RUN cd web && npm ci --no-audit --no-fund
COPY web/ ./web/
RUN cd web && npm run build

# --- estágio 2: servidor Python + FFmpeg ---
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY core/ ./core/
COPY audio/ ./audio/
COPY ai/ ./ai/
COPY images/ ./images/
COPY assets/ ./assets/
COPY config/ ./config/
COPY server/ ./server/
COPY scripts/ ./scripts/
COPY --from=web /src/web/dist ./web/dist
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT}"]
