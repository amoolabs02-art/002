FROM python:3.13-slim-bookworm

# Chrome (Chromium) installieren
RUN apt-get update -qq && \
    apt-get install -y -qq chromium && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "main.py"]
