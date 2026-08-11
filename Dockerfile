FROM python:3.13-slim

WORKDIR /app

RUN addgroup --system skysync && adduser --system --ingroup skysync skysync

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/telegram_sessions /data/uploads /data/previews /data/db && \
    chown -R skysync:skysync /app /data

USER skysync

ENV APP_ENV=production \
    FLASK_DEBUG=False \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:app"]
