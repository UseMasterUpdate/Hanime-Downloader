FROM python:3.11-slim

# Install system deps: imagemagick (thumbnails), ffmpeg (video merge), fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    imagemagick \
    ffmpeg \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Allow ImageMagick to write files (disabled by default in some distros)
RUN sed -i 's|<policy domain="path" rights="none" pattern="@\*"/>|<!-- disabled -->|g' \
    /etc/ImageMagick-6/policy.xml 2>/dev/null || true

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source
COPY bot.py .

# /tmp/hanime is created by the bot itself at runtime
CMD ["python", "bot.py"]
