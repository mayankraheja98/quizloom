# Hugging Face Spaces (Docker SDK): single container, port 7860, runs as UID 1000.
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user backend/ .
COPY --chown=user --from=web /web/dist /app/static

ENV DISABLE_OLLAMA=true \
    STATIC_DIR=/app/static \
    DATABASE_URL=sqlite:////tmp/examprep.db
USER user
EXPOSE 7860
CMD ["uvicorn", "space_app:app", "--host", "0.0.0.0", "--port", "7860"]
