# Peakstone API image. Build context = repo root (see infra/docker-compose.yml).
FROM python:3.12-slim
WORKDIR /app

# deps first (better layer caching)
COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# the API reuses engine/ (bundle hashing + keys) and schema/ (bundle validation)
COPY engine/ ./engine/
COPY schema/ ./schema/
COPY api/ ./api/

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
