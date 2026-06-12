FROM python:3.11-slim

LABEL org.opencontainers.image.title="Music Release Prep Agent"
LABEL org.opencontainers.image.description="AI-powered music release metadata, artwork & packaging"
LABEL org.opencontainers.image.version="1.0.0"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Fix ImageMagick policy to allow SVG conversion
RUN sed -i 's/rights="none" pattern="SVG"/rights="read|write" pattern="SVG"/' \
    /etc/ImageMagick-6/policy.xml 2>/dev/null || true

WORKDIR /app

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Serve frontend as static from the frontend folder
RUN mkdir -p ./frontend/dist && cp ./frontend/index.html ./frontend/dist/index.html

# Volumes for output
VOLUME ["/tmp/mra_uploads", "/tmp/mra_output"]

ENV PORT=7700
EXPOSE 7700

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s \
  CMD curl -f http://localhost:7700/api/health || exit 1

CMD ["python3", "-u", "backend/main.py"]
