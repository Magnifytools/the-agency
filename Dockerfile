FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY Procfile ./Procfile
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
COPY chrome-extension/manifest.json ./chrome-extension/manifest.json
COPY chrome-extension/dist/ ./chrome-extension/dist/

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PORT=8004
# Build: 2026-03-30-v6-sprint-digest-timer

EXPOSE ${PORT}
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 75
