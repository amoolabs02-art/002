FROM python:3.13-slim-bookworm

# Google Chrome + Node.js installieren
RUN apt-get update -qq && \
    apt-get install -y -qq wget gnupg nodejs npm && \
    wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install -y -qq /tmp/chrome.deb && \
    rm /tmp/chrome.deb && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt package.json .
RUN pip install --no-cache-dir -r requirements.txt
ENV PUPPETEER_SKIP_DOWNLOAD=1
RUN npm i

COPY . .

# Starte captchaSolver (Node.js) + Bot (Python)
CMD sh -c "node captchaSolver.js & sleep 4 && python -u main.py"
