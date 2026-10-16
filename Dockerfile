# Imagem do backend do MedRemind
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

COPY medremind/__init__.py medremind/__init__.py
COPY medremind/core medremind/core
COPY backend backend
COPY alembic.ini .

# Usuário sem privilégios
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# Aplica migrações e sobe a API (2 workers; o agendador roda só se SCHEDULER_ENABLED=true)
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app_factory --factory --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers"]
