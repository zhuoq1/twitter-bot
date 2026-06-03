"""
Sends the daily Serenity investment summary via Gmail SMTP.
"""

import logging
import os
import re
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
            line-height: 1.7;
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
        .content h3 {{
            margin-top: 24px;
            color: #1d9bf0;
            font-size: 16px;
        }}
        .content ul {{
            padding-left: 20px;
        }}
        .content li {{
            margin-bottom: 6px;
        }}
        .content p {{
            margin: 8px 0;
        }}
        .content strong {{
            color: #0d6efd;
        }}
        .content code {{
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 13px;
        }}
        .content a {{
            color: #1d9bf0;
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
        <h1>🔮 Serenity 投资建议摘要</h1>
        <p>{date_label}</p>
    </div>
    <div class="content">
        {body}
    </div>
    <div class="footer">
        <p>
            由 <a href="https://github.com/zhuoq1/twitter-bot">Serenity Bot</a> 自动生成 ·
            推文来源 <a href="https://x.com/aleabitoreddit">@aleabitoreddit</a>
        </p>
        <p>⚠️ 本文为 AI 从社交媒体自动生成，不构成投资建议。请自行研究后再做决策。</p>
    </div>
</body>
</html>
"""


def _inline_markdown_to_html(text: str) -> str:
    """Convert inline markdown formatting to HTML."""
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)

    # Italic: *text* or _text_ (but not inside words, not **)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", text)

    # Inline code: `text`
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)

    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)

    return text


def _format_body_as_html(markdown_text: str) -> str:
    """Convert markdown to HTML for the email body."""
    lines = markdown_text.split("\n")
    html_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Empty line → close any open list and add spacing
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br>")
            continue

        # Section headings (emoji-prefixed)
        if any(stripped.startswith(e) for e in ["📊", "💰", "🧠", "⚠️", "📈", "📉", "🔍", "💡"]):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(
                f'<h3>{_inline_markdown_to_html(stripped)}</h3>'
            )
            continue

        # Sub-headings (## or ###)
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(
                f'<h4 style="color:#555;">{_inline_markdown_to_html(stripped[4:])}</h4>'
            )
            continue
        if stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(
                f'<h3>{_inline_markdown_to_html(stripped[3:])}</h3>'
            )
            continue

        # Bullet list items: - item or * item
        if re.match(r"^[-*] ", stripped):
            content = _inline_markdown_to_html(re.sub(r"^[-*] ", "", stripped))
            if not in_list:
                html_lines.append('<ul style="padding-left: 20px;">')
                in_list = True
            html_lines.append(f"<li>{content}</li>")
            continue

        # Numbered list items: 1. item
        if re.match(r"^\d+\. ", stripped):
            content = _inline_markdown_to_html(re.sub(r"^\d+\.\s*", "", stripped))
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            # Simple numbered items as styled paragraphs
            html_lines.append(
                f'<p style="margin-left: 20px;">{content}</p>'
            )
            continue

        # Regular paragraph
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        html_lines.append(f"<p>{_inline_markdown_to_html(stripped)}</p>")

    # Close any remaining list
    if in_list:
        html_lines.append("</ul>")

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
        date_label=date.today().strftime("%Y 年 %m 月 %d 日"),
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
