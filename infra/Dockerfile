# Peakstone API image. Build context = repo root (see infra/docker-compose.yml).
FROM python:3.12-slim
WORKDIR /app

# deps first (better layer caching)
COPY requirements.txt ./requirements.txt
COPY peakstone/api/requirements.txt ./peakstone/api/requirements.txt
RUN pip install --no-cache-dir -r peakstone/api/requirements.txt

# the whole package: api + the engine it reuses (bundle hashing/keys + the bundled schema)
COPY peakstone/ ./peakstone/
# alembic.ini drives `alembic upgrade head` on deploy (script_location -> peakstone/api/alembic)
COPY alembic.ini ./alembic.ini

EXPOSE 8000
# compose overrides this to run migrations first; kept here for a bare `docker run`.
CMD ["uvicorn", "peakstone.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
