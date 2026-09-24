# Multi-container variant: app only. Talks to a separate Redis container/service.
FROM python:3.12-slim

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/main.py app/load_data.py app/entrypoint-app.sh ./
COPY app/static ./static
RUN chmod +x entrypoint-app.sh

COPY data/movies.csv data/ratings_sample.csv /data/
ENV DATA_DIR=/data

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["./entrypoint-app.sh"]
