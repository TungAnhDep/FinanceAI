FROM python:3.12-slim
RUN apt-get update && apt-get install -y \
    make \
    # Tesseract OCR 
    tesseract-ocr \
    tesseract-ocr-vie \
    #  Postgres
    libpq-dev \
    build-essential \
    # Playwright
    libnss3 \
    libnspr4 \
    libasound2 \
    libatk1.0-0 \
    libc6 \
    ca-certificates \
    fonts-liberation \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    lsb-release \
    wget \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium

RUN mkdir -p exports

CMD ["make", "dev"]