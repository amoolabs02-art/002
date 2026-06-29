FROM python:3.13-slim-bookworm

# Google Chrome installieren (undetected_chromedriver erwartet das)
RUN apt-get update -qq && \
    apt-get install -y -qq wget gnupg && \
    wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install -y -qq /tmp/chrome.deb && \
    rm /tmp/chrome.deb && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "-u", "main.py"]
