#!/usr/bin/env python3
"""
Serenity Bot — Daily Investment Advice Summarizer

1. Fetches Serenity's tweets from the last 24 hours via Twitter syndication
2. Summarizes investment advice using DeepSeek API
3. Emails the summary via Gmail SMTP

Usage:
    python main.py                    # uses env vars
    python main.py --dry-run          # print summary to stdout, don't email
"""

import argparse
import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv

from fetcher import fetch_recent_tweets
from summarizer import summarize_tweets
from mailer import send_email

# Load .env from workspace root (fallback to local)
load_dotenv(os.path.expanduser("~/workspace/.env"))
load_dotenv()  # also try local .env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("serenity-bot")


def main():
    parser = argparse.ArgumentParser(description="Serenity Investment Bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary to stdout instead of sending email",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours of tweets to fetch (default: 24)",
    )
    args = parser.parse_args()

    today_str = date.today().strftime("%Y-%m-%d")
    logger.info(f"=== Serenity Bot — {today_str} ===")

    # 1. Fetch tweets
    logger.info(f"Step 1/3: Fetching tweets from last {args.hours}h (syndication → Nitter RSS fallback)...")
    result = fetch_recent_tweets(username="aleabitoreddit", hours=args.hours)

    if result.error and not result.tweets:
        logger.error(f"Tweet fetch failed: {result.error}")
        if not args.dry_run:
            _send_error_email(f"Tweet fetch failed: {result.error}")
        sys.exit(1)

    logger.info(f"Got {len(result.tweets)} tweets")

    # 2. Summarize
    logger.info("Step 2/3: Summarizing with DeepSeek...")
    tweet_texts = [t.text for t in result.tweets]

    try:
        summary = summarize_tweets(tweet_texts)
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        # Fallback: send raw tweet dump
        summary = f"""⚠️ **Summarization failed** — showing raw tweets instead.

{chr(10).join(f'- {t}' for t in tweet_texts)}"""

    # 3. Send email
    subject = f"🔮 Serenity 投资建议摘要 — {today_str}"

    if args.dry_run:
        print("\n" + "=" * 60)
        print(f"SUBJECT: {subject}")
        print("=" * 60 + "\n")
        print(summary)
        print("\n" + "=" * 60)
        print(f"({len(tweet_texts)} tweets processed, dry run — no email sent)")
        return

    logger.info("Step 3/3: Sending email...")
    to_email = os.environ.get("TO_EMAIL", os.environ.get("GMAIL_USER", ""))

    try:
        send_email(
            subject=subject,
            body_markdown=summary,
            to_email=to_email,
        )
        logger.info(f"✅ Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")
        sys.exit(1)

    logger.info("=== Done ===")


def _send_error_email(error_msg: str):
    """Send a notification that the bot encountered an error."""
    subject = f"⚠️ Serenity Bot Error — {date.today().strftime('%Y-%m-%d')}"
    body = f"""**Serenity Bot encountered an error while fetching tweets.**

**Error:** {error_msg}

This is an automated notification. The bot will retry on its next scheduled run.
"""
    try:
        to_email = os.environ.get("TO_EMAIL", os.environ.get("GMAIL_USER", ""))
        send_email(subject=subject, body_markdown=body, to_email=to_email)
    except Exception:
        logger.error("Could not send error email — check credentials")


if __name__ == "__main__":
    main()
