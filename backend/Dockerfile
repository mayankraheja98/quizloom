FROM python:3.12-slim

WORKDIR /app

# Install deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Railway sets $PORT dynamically; default to 8000 for local/Docker Compose
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
