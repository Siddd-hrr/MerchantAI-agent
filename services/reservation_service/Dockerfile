FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY shared /app/shared
COPY services /app/services

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8005

CMD ["uvicorn", "services.reservation_service.main:app", "--host", "0.0.0.0", "--port", "8005"]
