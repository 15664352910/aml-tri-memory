FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# AML_MEMORY_SYSTEM_KEY must be supplied at runtime (never baked in).
# DATABASE_URL optional; without it the service runs in-memory.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
