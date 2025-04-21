# celery_worker.py
from app import app  # make sure this creates the Flask app
from services.celery_base import celery, init_celery

init_celery(app)
