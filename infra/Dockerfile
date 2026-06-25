# Peakstone API image. Build context = repo root (see infra/docker-compose.yml).
FROM python:3.12-slim
WORKDIR /app

# deps first (better layer caching)
COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# the API reuses engine/ for bundle hashing + keys + the bundled schema (engine/schema/)
COPY engine/ ./engine/
COPY api/ ./api/
COPY alembic.ini ./alembic.ini   # `alembic upgrade head` on deploy (script_location -> api/alembic)

EXPOSE 8000
# compose overrides this to run migrations first; kept here for a bare `docker run`.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
