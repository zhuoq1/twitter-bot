"""
Fetches tweets from Serenity (@aleabitoreddit) via Twitter's syndication endpoint.

Twitter's embed widget at syndication.twitter.com returns tweet data as embedded
JSON in a Next.js page. This is the same endpoint Twitter uses for its own embed
widgets — more reliable than third-party Nitter instances.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SYNDICATION_URL = (
    "https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
)
REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds between retries


@dataclass
class Tweet:
    id: str
    text: str  # cleaned plain-text content
    published: datetime
    link: str


@dataclass
class FetchResult:
    tweets: list[Tweet] = field(default_factory=list)
    error: Optional[str] = None


def _clean_tweet_text(raw: str) -> str:
    """Remove HTML entities and URLs from tweet text, keep it readable."""
    # Decode HTML entities
    text = unescape(raw)
    # Remove t.co URLs (keep the text clean)
    text = re.sub(r"https?://t\.co/\w+", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_twitter_date(date_str: str) -> Optional[datetime]:
    """Parse Twitter's created_at format: 'Wed Oct 29 05:03:08 +0000 2025'"""
    try:
        # Twitter dates are in UTC
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    return None


def _extract_tweets_from_html(html: str, username: str) -> list[Tweet]:
    """Parse tweet data out of the syndication page's __NEXT_DATA__ JSON blob."""
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        logger.error("Could not find __NEXT_DATA__ in HTML response")
        return []

    data = json.loads(match.group(1))
    timeline = data.get("props", {}).get("pageProps", {}).get("timeline", {})
    entries = timeline.get("entries", [])

    tweets = []
    for entry in entries:
        if entry.get("type") != "tweet":
            continue

        tweet_data = entry["content"]["tweet"]
        tweet_id = tweet_data.get("id_str", "")
        raw_text = tweet_data.get("full_text") or tweet_data.get("text", "")
        created_at = tweet_data.get("created_at", "")

        published = _parse_twitter_date(created_at)
        if not published or not raw_text:
            continue

        text = _clean_tweet_text(raw_text)
        link = f"https://twitter.com/{username}/status/{tweet_id}"

        tweets.append(Tweet(
            id=tweet_id,
            text=text,
            published=published,
            link=link,
        ))

    return tweets


def fetch_recent_tweets(
    username: str = "aleabitoreddit",
    hours: int = 24,
) -> FetchResult:
    """
    Fetch tweets from the last `hours` hours via Twitter's syndication endpoint.

    Returns a FetchResult with tweets sorted newest-first.
    """
    url = SYNDICATION_URL.format(username=username)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                f"Fetching tweets from syndication endpoint (attempt {attempt}/{MAX_RETRIES})..."
            )
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 429:
                wait = RETRY_DELAY * attempt
                logger.warning(f"Rate limited (429), waiting {wait}s before retry...")
                time.sleep(wait)
                continue

            resp.raise_for_status()

        except requests.RequestException as e:
            last_error = str(e)
            logger.warning(f"HTTP request failed (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            continue

        # Parse tweets from the HTML response
        all_tweets = _extract_tweets_from_html(resp.text, username)

        if not all_tweets:
            logger.warning("No tweets extracted from response")
            # Might be a rendering issue — the embed JS didn't execute.
            # The data is still in the HTML, so this is unexpected.
            continue

        logger.info(f"Extracted {len(all_tweets)} total tweets from timeline")

        # Filter to the recent window
        recent = [t for t in all_tweets if t.published >= cutoff]
        recent.sort(key=lambda t: t.published, reverse=True)

        logger.info(
            f"{len(recent)} of {len(all_tweets)} tweets are within the last {hours}h"
        )

        if not recent:
            # No recent tweets — still a successful fetch, just an empty result
            return FetchResult(tweets=[])

        return FetchResult(tweets=recent)

    return FetchResult(
        error=last_error or "Failed to fetch tweets after all retries"
    )
