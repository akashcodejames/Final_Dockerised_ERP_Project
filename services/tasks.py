import asyncio
from celery.schedules import crontab
from sqlalchemy import or_, and_
import logging
from extensions import db
from models import EmailLog
from datetime import datetime, timedelta
from services.async_email_sender import AsyncEmailSender
import redis
from services.email_service import EmailService
from services.celery_base import celery
from flask import current_app
import os

logger = logging.getLogger(__name__)

# Initialize Redis client with container name
redis_client = redis.Redis(
    host=os.environ.get('REDIS_HOST', 'redis'),
    port=6379,
    db=0,
    decode_responses=True
)

# Configure beat schedule
celery.conf.update(
    beat_schedule={
        'process-email-queue': {
            'task': 'services.tasks.process_email_queue',
            'schedule': 30.0,
        },
        'cleanup-email-logs': {
            'task': 'services.tasks.cleanup_email_logs_in_batches',
            'schedule': crontab(hour=2, minute=0),
        }
    }
)

@celery.task
def cleanup_email_logs_in_batches():
    """
    Cleanup old email logs in batches to prevent memory issues
    with large deletions
    """
    try:
        current_time = datetime.utcnow()
        seven_days_ago = current_time - timedelta(days=7)
        thirty_days_ago = current_time - timedelta(days=30)
        batch_size = 1000
        total_deleted = 0

        while True:
            # Find batch of emails to delete
            emails_to_delete = EmailLog.query.filter(
                or_(
                    and_(
                        EmailLog.status == 'sent',
                        EmailLog.sent_at <= seven_days_ago
                    ),
                    and_(
                        EmailLog.status == 'failed',
                        EmailLog.retry_count >= 3,
                        EmailLog.created_at <= seven_days_ago
                    ),
                    EmailLog.created_at <= thirty_days_ago
                )
            ).limit(batch_size).all()

            if not emails_to_delete:
                break

            # Delete batch
            for email in emails_to_delete:
                db.session.delete(email)

            total_deleted += len(emails_to_delete)
            db.session.commit()

            logger.info(f"Deleted batch of {len(emails_to_delete)} email logs")

        logger.info(f"Total email logs cleaned up: {total_deleted}")
        return f"Total email logs cleaned up: {total_deleted}"

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in batch cleanup of email logs: {e}")
        raise

@celery.task
def process_urgent_emails():
    """Process high priority emails (URGENT and HIGH priority only)"""
    lock = redis_client.lock("urgent_email_queue_lock", timeout=60)
    if not lock.acquire(blocking=False):
        return "Urgent task already running"

    try:
        # Process only URGENT and HIGH priority emails
        pending_emails = EmailLog.query.filter(
            EmailLog.status == 'pending',
            EmailLog.retry_count < 3,
            EmailLog.priority <= EmailService.PRIORITY_HIGH  # Priority 1 and 2 only
        ).order_by(
            EmailLog.priority,
            EmailLog.created_at
        ).limit(50).all()

        if not pending_emails:
            return "No urgent pending emails"

        emails_to_send = [
            {
                'email_id': email.id,
                'to_email': email.to_email,
                'subject': email.subject,
                'html_content': email.html_body or email.body
            }
            for email in pending_emails
        ]

        smtp_settings = {
            'MAIL_SERVER': current_app.config['MAIL_SERVER'],
            'MAIL_PORT': current_app.config['MAIL_PORT'],
            'MAIL_USE_TLS': current_app.config['MAIL_USE_TLS'],
            'MAIL_USERNAME': current_app.config['MAIL_USERNAME'],
            'MAIL_PASSWORD': current_app.config['MAIL_PASSWORD'],
            'MAIL_DEFAULT_SENDER': current_app.config['MAIL_DEFAULT_SENDER']
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(
            AsyncEmailSender.send_emails(
                smtp_settings=smtp_settings,
                emails=emails_to_send,
                batch_size=25  # Smaller batch size for urgent emails
            )
        )
        loop.close()

        for result in results:
            email_log = EmailLog.query.get(result['email_id'])
            if email_log:
                if result['success']:
                    email_log.status = 'sent'
                    email_log.sent_at = datetime.utcnow()
                else:
                    email_log.status = 'failed'
                    email_log.error_message = result['error']
                    email_log.retry_count += 1

        db.session.commit()
        return f"Processed {len(results)} urgent emails"

    except Exception as e:
        db.session.rollback()
        return f"Error processing urgent email queue: {str(e)}"

    finally:
        lock.release()

@celery.task(name='services.tasks.process_email_queue')
def process_email_queue():
    """Process regular priority emails (NORMAL, LOW, and BULK only)"""
    logger.info("Starting process_email_queue task")
    
    lock = redis_client.lock("email_queue_lock", timeout=120)
    if not lock.acquire(blocking=False):
        logger.info("Email queue task already running")
        return "Task already running"

    try:
        # Get SMTP settings from app config
        smtp_settings = current_app.config.get('SMTP_SETTINGS')
        safe_settings = {
            k: '****' if k in ['MAIL_PASSWORD'] else v
            for k, v in (smtp_settings or {}).items()
        }
        print("SMTP Settings in Celery task:", safe_settings)
        logger.info("SMTP Settings in Celery task: %s", safe_settings)
        # Validate SMTP settings
        if not smtp_settings or not all([
            smtp_settings.get('MAIL_SERVER'),
            smtp_settings.get('MAIL_USERNAME'),
            smtp_settings.get('MAIL_PASSWORD')
        ]):
            logger.error("SMTP settings missing or incomplete")
            logger.debug(f"Available settings: {smtp_settings}")
            raise ValueError("SMTP settings are not properly configured")

        logger.info(f"Using SMTP server: {smtp_settings['MAIL_SERVER']}:{smtp_settings['MAIL_PORT']}")
        
        # Log query parameters
        logger.info("Querying pending emails with: status='pending', retry_count<3, priority>2")
        
        # Process only NORMAL and lower priority emails
        pending_emails = EmailLog.query.filter(
            EmailLog.status == 'pending',
            EmailLog.retry_count < 3,
            EmailLog.priority > EmailService.PRIORITY_HIGH  # Priority 3, 4, and 5 only
        ).order_by(
            EmailLog.priority,
            EmailLog.created_at
        ).limit(100).all()

        logger.info(f"Found {len(pending_emails)} pending emails to process")
        
        if not pending_emails:
            logger.info("No pending emails found in database")
            return "No pending emails"

        # Log email details
        for email in pending_emails:
            logger.info(f"Processing email ID {email.id}: To={email.to_email}, Subject={email.subject}, Priority={email.priority}")

        emails_to_send = [
            {
                'email_id': email.id,
                'to_email': email.to_email,
                'subject': email.subject,
                'html_content': email.html_body or email.body
            }
            for email in pending_emails
        ]

        logger.info("Creating async event loop")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        logger.info("Starting AsyncEmailSender.send_emails")
        results = loop.run_until_complete(
            AsyncEmailSender.send_emails(
                smtp_settings=smtp_settings,
                emails=emails_to_send,
                batch_size=10
            )
        )
        loop.close()
        logger.info(f"AsyncEmailSender completed with {len(results)} results")

        # Log results processing
        success_count = 0
        failure_count = 0
        for result in results:
            email_log = EmailLog.query.get(result['email_id'])
            if email_log:
                if result['success']:
                    success_count += 1
                    email_log.status = 'sent'
                    email_log.sent_at = datetime.utcnow()
                    logger.info(f"Email {result['email_id']} sent successfully to {result['to_email']}")
                else:
                    failure_count += 1
                    email_log.status = 'failed'
                    email_log.error_message = result['error']
                    email_log.retry_count += 1
                    logger.error(f"Email {result['email_id']} failed: {result['error']}")

        logger.info(f"Committing changes: {success_count} successes, {failure_count} failures")
        db.session.commit()
        return f"Processed {len(results)} emails ({success_count} sent, {failure_count} failed)"

    except Exception as e:
        logger.error(f"Error processing email queue: {str(e)}", exc_info=True)
        db.session.rollback()
        return f"Error processing email queue: {str(e)}"

    finally:
        lock.release()
        logger.info("Email queue task completed")
