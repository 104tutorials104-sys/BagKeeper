FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 BAGKEEPER_ENV=production BAGKEEPER_DATA_DIR=/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
VOLUME /data
EXPOSE 8000
# SQLite: keep one process (threads handle concurrency) until you move to Postgres
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "run:app"]
