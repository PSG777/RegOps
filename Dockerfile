FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY pyproject.toml README.md ./
COPY regops ./regops
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 regops
USER regops
EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn regops.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
