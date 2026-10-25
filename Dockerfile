FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DB_PATH=/data/credit.db
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -r -u 10001 appuser && mkdir /data && chown appuser /data
USER appuser
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"
# один воркер: SQLite + фоновые потоки конвейера; для масштабирования — PostgreSQL + очередь (см. docs/ARCHITECTURE.md)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
