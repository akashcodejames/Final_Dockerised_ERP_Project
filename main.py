import logging
from app import app
from session_cleanup import cleanup_expired_sessions, start_cleanup_thread
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

try:
    if __name__ == "__main__":
        # Only start the cleanup thread in the main process
        if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            logger.info("Starting session cleanup thread")
            # start_cleanup_thread()

        app.run(host="0.0.0.0", port=5001, debug=True)
except Exception as e:
    logger.error(f"Failed to start server: {str(e)}")
    raise