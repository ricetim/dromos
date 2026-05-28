# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime — serves API + static files
FROM python:3.11-slim
WORKDIR /app
COPY backend/pyproject.toml .
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" "sqlmodel<0.0.30" fitdecode \
    httpx python-multipart apscheduler exifread
COPY backend/app/ ./app/
COPY --from=frontend-builder /app/dist /app/frontend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
