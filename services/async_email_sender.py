import asyncio
import aiosmtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
import logging

from aiosmtplib import smtp

logger = logging.getLogger(__name__)

class AsyncEmailSender:
    def __init__(self, smtp_settings: Dict):
        self.settings = smtp_settings
        self.connection = None
        
    async def connect(self):
        """Create SMTP connection"""
        try:
            # Always start with non-TLS connection for port 587
            self.connection = aiosmtplib.SMTP(
                hostname=self.settings['MAIL_SERVER'],
                port=self.settings['MAIL_PORT'],
                use_tls=False  # Start without TLS
            )

            # Connect to the server
            await self.connection.connect()
            
            # For Gmail or when TLS is required, upgrade the connection using STARTTLS
            if self.settings.get('MAIL_USE_TLS', False):
                await self.connection.starttls(
                    tls_context=ssl.create_default_context()
                )

            # Login if credentials are provided
            if self.settings.get('MAIL_USERNAME') and self.settings.get('MAIL_PASSWORD'):
                await self.connection.login(
                    self.settings['MAIL_USERNAME'],
                    self.settings['MAIL_PASSWORD']
                )
                
            logger.info(f"Successfully connected to {self.settings['MAIL_SERVER']}:{self.settings['MAIL_PORT']}")
            
        except Exception as e:
            logger.error(f"SMTP Connection error: {str(e)}")
            if self.connection:
                try:
                    await self.connection.quit()
                except:
                    pass
            raise

    async def send_one(self, to_email: str, subject: str, html_content: str) -> bool:
        """Send a single email"""
        message = MIMEMultipart('alternative')
        message['From'] = self.settings['MAIL_DEFAULT_SENDER']
        message['To'] = to_email
        message['Subject'] = subject
        message.attach(MIMEText(html_content, 'html'))

        try:
            await self.connection.send_message(message)
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

    async def send_batch(self, emails: List[Dict]) -> List[Dict]:
        """Send multiple emails concurrently"""
        try:
            await self.connect()
            
            # Create tasks for all emails
            tasks = [
                self.send_one(
                    email['to_email'],
                    email['subject'],
                    email['html_content']
                ) for email in emails
            ]
            
            # Execute all tasks concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            processed_results = []
            for email, result in zip(emails, results):
                success = isinstance(result, bool) and result
                processed_results.append({
                    'email_id': email.get('email_id'),
                    'to_email': email['to_email'],
                    'success': success,
                    'error': str(result) if isinstance(result, Exception) else None
                })
            
            return processed_results
            
        finally:
            if self.connection:
                try:
                    await self.connection.quit()
                except:
                    pass

    @classmethod
    async def send_emails(cls, smtp_settings: Dict, emails: List[Dict], batch_size: int = 50) -> List[Dict]:
        """Send emails in batches"""
        sender = cls(smtp_settings)
        results = []
        
        # Process emails in batches
        for i in range(0, len(emails), batch_size):
            batch = emails[i:i + batch_size]
            batch_results = await sender.send_batch(batch)
            results.extend(batch_results)
            
        return results
