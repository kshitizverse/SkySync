"""
Gunicorn configuration for SkySync production deployment.
"""
import os
import multiprocessing

bind = os.getenv("FLASK_HOST", "0.0.0.0") + ":" + os.getenv("PORT", os.getenv("FLASK_PORT", "8000"))
workers = int(os.getenv("GUNICORN_WORKERS", str(min(multiprocessing.cpu_count() * 2 + 1, 9))))
worker_class = "gthread"
threads = 2
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
preload_app = True
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
