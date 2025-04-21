import threading
import time
from datetime import datetime
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)
_cleanup_thread = None

def cleanup_expired_sessions():
    while True:
        try:
            from app import app, db  # Import here to avoid circular imports
            with app.app_context():
                result = db.session.execute(
                    text("DELETE FROM sessions WHERE expiry < :current_time"),
                    {"current_time": datetime.utcnow()}
                )
                db.session.commit()
                logger.info(f"[SESSION CLEANUP] Deleted {result.rowcount} expired sessions")
        except Exception as e:
            logger.error(f"[SESSION CLEANUP ERROR] {str(e)}")
        time.sleep(3600)  # Sleep for 1 hour

def start_cleanup_thread():
    global _cleanup_thread
    if _cleanup_thread is None or not _cleanup_thread.is_alive():
        _cleanup_thread = threading.Thread(
            target=cleanup_expired_sessions,
            daemon=True,
            name="session-cleanup"
        )
        _cleanup_thread.start()
        logger.info("Session cleanup thread started")