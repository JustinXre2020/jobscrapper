"""
Email sender using Gmail SMTP
Sends daily job digest with HTML formatting
Supports multiple recipients with per-recipient job filtering
"""
from loguru import logger
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional, Union
from datetime import datetime

from utils.config import settings, Recipient, parse_recipients



def mask_email(email: str) -> str:
    """Mask email address for privacy in logs (e.g., j***n@gmail.com)"""
    if not email or '@' not in email:
        return '***'
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + '***'
    else:
        masked_local = local[0] + '***' + local[-1]
    return f"{masked_local}@{domain}"


class EmailSender:
    """Email dispatcher using Gmail SMTP with multi-recipient support"""

    def __init__(self):
        """
        Initialize Gmail SMTP client with multi-recipient configuration
        """
        self.gmail_email = settings.gmail_email
        self.gmail_app_password = settings.gmail_app_password

        if not self.gmail_email or not self.gmail_app_password:
            raise ValueError(
                "GMAIL_EMAIL and GMAIL_APP_PASSWORD must be set in environment. "
                "Get an App Password from: https://myaccount.google.com/apppasswords"
            )

        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.from_email = self.gmail_email

        # Load recipients from config
        self.recipients = parse_recipients()
        logger.info(f"📧 Loaded {len(self.recipients)} recipient(s)")

    def _send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        Send an email via Gmail SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content of the email

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"Job Hunter Sentinel <{self.from_email}>"
            msg["To"] = to_email

            # Attach HTML content
            html_part = MIMEText(html_body, "html", "utf-8")
            msg.attach(html_part)

            # Connect and send
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.gmail_email, self.gmail_app_password)
                server.sendmail(self.from_email, to_email, msg.as_string())

            return True

        except Exception as e:
            logger.error(f"❌ SMTP error: {e}")
            return False

    def filter_jobs_for_recipient(
        self,
        jobs_by_term: Dict[str, List[Dict]],
        recipient: Recipient
    ) -> List[Dict]:
        """
        Filter jobs for a specific recipient based on their search terms and sponsorship needs.

        Args:
            jobs_by_term: Dict mapping search term -> list of jobs
            recipient: Recipient configuration

        Returns:
            List of jobs filtered for this recipient
        """
        recipient_jobs = []

        # Collect jobs matching recipient's search terms (case-insensitive)
        recipient_terms_lower = {term.lower().strip() for term in recipient.search_terms}

        for term, jobs in jobs_by_term.items():
            if term.lower().strip() in recipient_terms_lower:
                recipient_jobs.extend(jobs)

        # Deduplicate by job_url (same job may match multiple terms)
        seen_urls = set()
        unique_jobs = []
        for job in recipient_jobs:
            url = job.get('job_url')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_jobs.append(job)

        # Filter by sponsorship if needed
        if recipient.needs_sponsorship:
            unique_jobs = [
                j for j in unique_jobs
                if j.get('llm_evaluation', {}).get('visa_sponsorship', False)
            ]

        return unique_jobs

    def create_job_html(self, job: Dict) -> str:
        """
        Generate HTML for a single job listing

        Args:
            job: Job dict with job data

        Returns:
            HTML string
        """
        import pandas as pd

        # Helper to safely get string values (handles NaN/None)
        def safe_str(value, default=''):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return default
            return str(value)

        title = safe_str(job.get('title'), 'Unknown Position')
        company = safe_str(job.get('company'), 'Unknown Company')
        location = safe_str(job.get('location'), 'Unknown Location')
        job_url = safe_str(job.get('job_url_direct'), '#')
        site = safe_str(job.get('site'), 'Unknown')

        # Get visa sponsorship status for badge
        llm_eval = job.get('llm_evaluation', {})
        has_visa = llm_eval.get('visa_sponsorship', False)
        visa_badge = '🟢 Visa Sponsor' if has_visa else '🔴 No Visa Info'


        return f"""
        <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 20px; background-color: #ffffff;">
            <div style="margin-bottom: 12px;">
                <h2 style="margin: 0; font-size: 20px; color: #1e293b;">
                    <a href="{job_url}" style="color: #2563eb; text-decoration: none;">{title}</a>
                </h2>
            </div>

            <div style="color: #64748b; font-size: 14px; margin-bottom: 8px;">
                <span style="font-weight: 600; color: #475569;">🏢 {company}</span> · 📍 {location}
            </div>

            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 12px;">
                来源: {site.upper() if site else 'N/A'} · {visa_badge}
            </div>

            <div style="margin-top: 12px;">
                <a href="{job_url}" style="display: inline-block; background-color: #2563eb; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 14px; font-weight: 500;">
                    查看详情 →
                </a>
            </div>
        </div>
        """

    def create_email_body(self, jobs: List[Dict], date: str, recipient: Optional[Recipient] = None) -> str:
        """
        Create full HTML email body

        Args:
            jobs: List of analyzed jobs
            date: Date string for email title
            recipient: Optional recipient for personalization

        Returns:
            Complete HTML email
        """
        # Personalization info
        sponsorship_note = ""
        if recipient and recipient.needs_sponsorship:
            sponsorship_note = " (已筛选Visa Sponsor)"

        # Header
        html = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Job Hunter Daily Digest</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">

                <!-- Header -->
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px; font-weight: 700;">
                        🎯 Job Hunter Sentinel
                    </h1>
                    <p style="color: #e0e7ff; margin: 8px 0 0 0; font-size: 16px;">
                        您的每日职位精选 · {date}
                    </p>
                </div>

                <!-- Summary -->
                <div style="padding: 20px; background-color: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                    <p style="margin: 0; color: #475569; font-size: 16px;">
                        今日为您精选 <strong style="color: #2563eb; font-size: 20px;">{len(jobs)}</strong> 个高匹配度职位{sponsorship_note}
                    </p>
                </div>

                <!-- Job Listings -->
                <div style="padding: 20px;">
        """

        # Add each job
        for job in jobs:
            html += self.create_job_html(job)

        # Footer
        html += """
                </div>

                <!-- Footer -->
                <div style="padding: 20px; background-color: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center;">
                    <p style="margin: 0 0 8px 0; color: #64748b; font-size: 14px;">
                        由 Job Hunter Sentinel 自动生成
                    </p>
                    <p style="margin: 0; color: #94a3b8; font-size: 12px;">
                        使用 Python JobSpy + LLM AI + Gmail SMTP 构建
                    </p>
                </div>

            </div>
        </body>
        </html>
        """

        return html

    def send_daily_digest(
        self,
        jobs_or_jobs_by_term: Union[List[Dict], Dict[str, List[Dict]]],
        custom_subject: Optional[str] = None
    ) -> Dict[str, bool]:
        """
        Send daily job digest email to all recipients.

        Args:
            jobs_or_jobs_by_term: Either a flat list of jobs (legacy) or
                                  Dict mapping search term -> list of jobs (new)
            custom_subject: Optional custom email subject

        Returns:
            Dict mapping recipient email -> success status
        """
        results = {}

        # Handle legacy format (flat list)
        if isinstance(jobs_or_jobs_by_term, list):
            # Convert to jobs_by_term format using a generic key
            jobs_by_term = {"all": jobs_or_jobs_by_term}
            # For legacy, all recipients get all jobs
            for recipient in self.recipients:
                recipient.search_terms = ["all"]
        else:
            jobs_by_term = jobs_or_jobs_by_term

        # Get current date
        today = datetime.now().strftime("%Y年%m月%d日")

        for recipient in self.recipients:
            try:
                # Filter jobs for this recipient
                filtered_jobs = self.filter_jobs_for_recipient(jobs_by_term, recipient)

                if not filtered_jobs:
                    logger.warning(f"⚠️ No jobs for {mask_email(recipient.email)} (needs_sponsorship={recipient.needs_sponsorship})")
                    self.send_empty_notification([recipient])
                    results[recipient.email] = True  # Not a failure, just no matching jobs
                    continue

                # Create email content
                html_body = self.create_email_body(filtered_jobs, today, recipient)

                # Subject with recipient-specific job count
                subject = custom_subject or f"🎯 Job Hunter Daily Digest - {len(filtered_jobs)} 个职位推荐 ({today})"

                # Send via Gmail SMTP
                logger.info(f"📧 Sending {len(filtered_jobs)} jobs to {mask_email(recipient.email)}...")

                success = self._send_email(recipient.email, subject, html_body)

                if success:
                    logger.info(f"✅ Email sent to {mask_email(recipient.email)}!")
                    results[recipient.email] = True
                else:
                    results[recipient.email] = False

            except Exception as e:
                logger.error(f"❌ Email to {mask_email(recipient.email)} failed: {e}")
                results[recipient.email] = False

        return results

    def send_empty_notification(self, recipents: List[Recipient] = []) -> Dict[str, bool]:
        """
        Send a notification when no jobs are found to all recipients. If no recipents passed, default to send all

        Returns:
            Dict mapping recipient email -> success status
        """
        results = {}
        today = datetime.now().strftime("%Y年%m月%d日")

        html_body = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f1f5f9; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; padding: 30px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                <h1 style="color: #64748b; margin: 0 0 16px 0; font-size: 24px;">
                    📭 Job Hunter Sentinel
                </h1>
                <p style="color: #475569; font-size: 16px; line-height: 1.6;">
                    今日（{today}）未发现符合条件的新职位。
                </p>
                <p style="color: #94a3b8; font-size: 14px; margin-top: 20px;">
                    系统将继续监控，有新职位时会立即通知您。
                </p>
            </div>
        </body>
        </html>
        """

        subject = f"📭 Job Hunter - 今日无新职位 ({today})"

        for recipient in recipents or self.recipients:
            try:
                success = self._send_email(recipient.email, subject, html_body)

                if success:
                    logger.info(f"📭 Empty notification sent to {mask_email(recipient.email)}.")
                    results[recipient.email] = True
                else:
                    results[recipient.email] = False

            except Exception as e:
                logger.error(f"❌ Failed to send empty notification to {mask_email(recipient.email)}: {e}")
                results[recipient.email] = False

        return results


def main():
    """Test email sending"""
    sender = EmailSender()

    # Test jobs with visa sponsorship info
    test_jobs = [
        {
            "title": "Junior Software Engineer",
            "company": "Google",
            "location": "Mountain View, CA",
            "job_url": "https://example.com/job/1",
            "site": "linkedin",
            "description": "Entry level position for new graduates. Work on cutting-edge technology.",
            "llm_evaluation": {"visa_sponsorship": True, "entry_level": True}
        },
        {
            "title": "Entry Level Full Stack Engineer",
            "company": "OpenAI",
            "location": "San Francisco, CA",
            "job_url": "https://example.com/job/2",
            "site": "indeed",
            "description": "Join our team as a new grad engineer and help build the future of AI.",
            "llm_evaluation": {"visa_sponsorship": False, "entry_level": True}
        }
    ]

    # Test with jobs_by_term format
    jobs_by_term = {
        "software engineer": [test_jobs[0]],
        "full stack engineer": [test_jobs[1]]
    }

    # Send test email
    results = sender.send_daily_digest(jobs_by_term)
    logger.info(f"Results: {results}")


if __name__ == "__main__":
    main()
