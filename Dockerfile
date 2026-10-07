FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg git curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --single-branch --branch main https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server && npm install && npx tsc

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd -m -u 1000 apiuser && chown -R apiuser:apiuser /app /opt/bgutil
USER apiuser

COPY start.sh /start.sh
USER root
RUN chmod +x /start.sh
USER apiuser

CMD ["/start.sh"]
