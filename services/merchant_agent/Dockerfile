FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY shared /app/shared
COPY services /app/services

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8002

CMD ["uvicorn", "services.merchant_agent.main:app", "--host", "0.0.0.0", "--port", "8002"]
