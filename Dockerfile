FROM python:3.12-slim

WORKDIR /app

# Install Python deps first so this layer is cached across code changes.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App source + built frontend + demo sample images.
COPY backend ./backend
COPY frontend/dist ./frontend/dist
COPY samples ./samples

# Runtime data (submissions, workbook, conversations) is written here and
# auto-seeded on first run. On Render's free tier it is ephemeral (resets on
# redeploy/restart), which is fine for a demo.
ENV SHG_DATA_DIR=/app/data

# Offline demo mode is automatic: no ANTHROPIC_API_KEY is set, so the app only
# recognises the synthetic sample photos and never calls Claude.

WORKDIR /app/backend
EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
