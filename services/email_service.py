from models import EmailLog
from flask import current_app, render_template
from extensions import db
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class EmailService:
    # Priority Constants
    PRIORITY_URGENT = 1    # Immediate notifications
    PRIORITY_HIGH = 2      # Password resets, account verification
    PRIORITY_NORMAL = 3    # Regular notifications
    PRIORITY_LOW = 4       # Marketing emails
    PRIORITY_BULK = 5      # Bulk mailings

    @staticmethod
    def send_email(to_email, subject, body=None, html_body=None, template_name=None, context=None, priority=PRIORITY_NORMAL):
        """Queue a single email for sending"""
        try:
            # Render template if provided
            rendered_html = None
            if template_name:
                try:
                    rendered_html = render_template(template_name, **(context or {}))
                except Exception as e:
                    logger.error(f"Failed to render template {template_name}: {e}")
                    raise

            email_log = EmailLog(
                to_email=to_email,
                from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                subject=subject,
                body=body or '',
                html_body=rendered_html or html_body,
                template_name=template_name,
                context_data=context,
                priority=priority
            )
            db.session.add(email_log)
            db.session.commit()
            return email_log.id

        except Exception as e:
            logger.error(f"Failed to queue email to {to_email}: {e}")
            db.session.rollback()
            raise

    @staticmethod
    def send_bulk_emails(emails):
        """Efficiently queue multiple emails"""
        try:
            email_logs = []
            for email in emails:
                # Render template if provided
                rendered_html = None
                template_name = email.get('template_name')
                context = email.get('context')
                
                if template_name:
                    try:
                        rendered_html = render_template(template_name, **(context or {}))
                    except Exception as e:
                        logger.error(f"Failed to render template {template_name} for {email['to_email']}: {e}")
                        continue

                email_logs.append(
                    EmailLog(
                        to_email=email['to_email'],
                        from_email=current_app.config['MAIL_DEFAULT_SENDER'],
                        subject=email['subject'],
                        body=email.get('body', ''),
                        html_body=rendered_html or email.get('html_body'),
                        template_name=template_name,
                        context_data=context,
                        priority=email.get('priority', EmailService.PRIORITY_BULK)
                    )
                )

            if email_logs:
                db.session.bulk_save_objects(email_logs)
                db.session.commit()
                return len(email_logs)
            return 0

        except Exception as e:
            logger.error(f"Failed to queue bulk emails: {e}")
            db.session.rollback()
            raise

    @staticmethod
    def get_email_status(email_id):
        """Get status of a queued email"""
        email_log = EmailLog.query.get(email_id)
        if not email_log:
            return None
        return {
            'status': email_log.status,
            'sent_at': email_log.sent_at,
            'error': email_log.error_message,
            'retry_count': email_log.retry_count,
            'priority': email_log.priority
        }