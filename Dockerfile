FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.deno/bin:${PATH}"

# ffmpeg + curl/unzip for Deno.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno (yt-dlp uses it for YouTube JavaScript/EJS challenges).
RUN curl -fsSL https://deno.land/install.sh | sh \
    && /root/.deno/bin/deno --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user; copy Deno binary to a system path so it remains available.
RUN cp /root/.deno/bin/deno /usr/local/bin/deno \
    && useradd -m -u 1000 apiuser \
    && chown -R apiuser:apiuser /app

USER apiuser

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
