import os
import time
import logging
import redis
from flask import Flask, render_template, flash, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_session import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import text
from dotenv import load_dotenv
from extensions import db, login_manager
from datetime import datetime, timedelta
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded
from services.celery_base import init_celery

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    pass

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "a_secret_key"

# Redis host setup (Docker friendly)
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")

# Limiter with Redis backend
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=f"redis://{REDIS_HOST}:6379",
    storage_options={"socket_connect_timeout": 30},
    strategy="fixed-window",
    default_limits=["200 per day", "50 per hour"]
)

# Configure MySQL
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
else:
    logger.error("Database URL is not set in the environment.")
    exit(1)

# Retry DB connection
MAX_RETRIES = 5
RETRY_DELAY = 5
for attempt in range(MAX_RETRIES):
    try:
        db.init_app(app)
        with app.app_context():
            db.session.execute(text("SELECT 1"))
        logger.info("Database connected successfully!")
        break
    except OperationalError:
        logger.warning(f"MySQL not ready, retrying in {RETRY_DELAY}s... (Attempt {attempt + 1}/{MAX_RETRIES})")
        time.sleep(RETRY_DELAY)
else:
    logger.error("Failed to connect to MySQL after multiple attempts. Exiting.")
    exit(1)

# Email Configuration
app.config.update(
    MAIL_SERVER=os.environ.get('SMTP_SERVER', 'smtp.gmail.com'),
    MAIL_PORT=int(os.environ.get('SMTP_PORT', 587)),
    MAIL_USE_TLS=False,
    MAIL_USERNAME=os.environ.get('SMTP_USERNAME'),
    MAIL_PASSWORD=os.environ.get('SMTP_PASSWORD'),
    MAIL_DEFAULT_SENDER=os.environ.get('SMTP_USERNAME')
)

# Ensure these settings are also available for Celery tasks
app.config['SMTP_SETTINGS'] = {
    'MAIL_SERVER': app.config['MAIL_SERVER'],
    'MAIL_PORT': app.config['MAIL_PORT'],
    'MAIL_USE_TLS': app.config['MAIL_USE_TLS'],
    'MAIL_USERNAME': app.config['MAIL_USERNAME'],
    'MAIL_PASSWORD': app.config['MAIL_PASSWORD'],
    'MAIL_DEFAULT_SENDER': app.config['MAIL_USERNAME']
}

# Redis-based Celery config
app.config.update(
    broker_url=f'redis://{REDIS_HOST}:6379/0',
    result_backend=f'redis://{REDIS_HOST}:6379/0',
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
)

# Redis session config
app.config['SESSION_REDIS'] = redis.StrictRedis(
    host=REDIS_HOST,
    port=6379,
    db=0
)

# Flask-Session configuration
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # True in production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Add this after other app configurations
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), "uploads")

# Initialize Flask extensions
Session(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
migrate = Migrate(app, db)

# Register blueprints
with app.app_context():
    import models
    from auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from timetable import timetable_bp
    app.register_blueprint(timetable_bp, url_prefix='/timetable')

    from library import library_bp
    app.register_blueprint(library_bp)

    # Create all tables only if not running as Celery worker
    if not os.environ.get('SKIP_DB_CREATE'):
        try:
            db.create_all()
            logger.info("Database tables created successfully!")
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            raise

        # Create test data
        try:
            if not models.UserCredentials.query.filter_by(email='admin@example.com').first():
                logger.info("Creating test users and data")
                models.create_test_data()
            else:
                logger.info("Test data already exists")
        except Exception as e:
            logger.error(f"Error creating test data: {str(e)}")
            raise
