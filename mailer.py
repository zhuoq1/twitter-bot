"""
Sends the daily Serenity investment summary via Gmail SMTP.
"""

import logging
import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 640px;
            margin: 0 auto;
            padding: 20px;
            color: #1a1a1a;
            line-height: 1.6;
        }}
        .header {{
            background: linear-gradient(135deg, #1d9bf0, #1a8cd8);
            color: white;
            padding: 24px;
            border-radius: 12px;
            margin-bottom: 24px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 22px;
        }}
        .header p {{
            margin: 4px 0 0 0;
            opacity: 0.85;
            font-size: 14px;
        }}
        .content {{
            background: #f8f9fa;
            padding: 24px;
            border-radius: 12px;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #888;
            margin-top: 24px;
        }}
        .footer a {{
            color: #1d9bf0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔮 Serenity's Investment Advice</h1>
        <p>{date_label}</p>
    </div>
    <div class="content">
        {body}
    </div>
    <div class="footer">
        <p>
            Generated automatically by <a href="https://github.com">Serenity Bot</a> ·
            Tweets sourced from <a href="https://nitter.net/aleabitoreddit">@aleabitoreddit</a>
        </p>
        <p>⚠️ This is AI-generated content from social media. Not financial advice.</p>
    </div>
</body>
</html>
"""


def _format_body_as_html(markdown_text: str) -> str:
    """Convert simple markdown to HTML for the email body."""
    # Handle markdown headings
    lines = markdown_text.split("\n")
    html_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            html_lines.append("<br>")
        elif stripped.startswith("📊") or stripped.startswith("💰") or stripped.startswith("🧠") or stripped.startswith("⚠️"):
            html_lines.append(f'<h3 style="margin-top: 20px; color: #1d9bf0;">{stripped}</h3>')
        elif stripped.startswith("- "):
            html_lines.append(f'<li style="margin-left: 16px;">{stripped[2:]}</li>')
        elif stripped.startswith("Tweet "):
            html_lines.append(f'<p style="color: #1d9bf0; margin-top: 12px;"><em>{stripped}</em></p>')
        else:
            html_lines.append(f"<p>{stripped}</p>")

    return "\n".join(html_lines)


def send_email(
    subject: str,
    body_markdown: str,
    to_email: str,
    gmail_user: Optional[str] = None,
    gmail_password: Optional[str] = None,
) -> bool:
    """
    Send an email via Gmail SMTP.

    Args:
        subject: Email subject line.
        body_markdown: Email body in markdown (will be converted to HTML).
        to_email: Recipient email address.
        gmail_user: Gmail address for auth. Falls back to GMAIL_USER env var.
        gmail_password: Gmail app password. Falls back to GMAIL_APP_PASSWORD env var.

    Returns:
        True if sent successfully, False otherwise.
    """
    user = gmail_user or os.environ.get("GMAIL_USER", "")
    password = gmail_password or os.environ.get("GMAIL_APP_PASSWORD", "")

    if not user or not password:
        raise ValueError("GMAIL_USER and GMAIL_APP_PASSWORD must be set")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email

    html_body = HTML_TEMPLATE.format(
        date_label=date.today().strftime("%B %d, %Y"),
        body=_format_body_as_html(body_markdown),
    )
    msg.attach(MIMEText(html_body, "html"))

    logger.info(f"Sending email to {to_email}...")
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())
        logger.info("Email sent successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise
