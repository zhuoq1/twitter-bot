"""
Fetches tweets from a Twitter/X account via multiple sources with fallback.

Primary: Twitter's syndication endpoint (syndication.twitter.com)
Fallback: Nitter RSS feeds (multiple public instances, tried in sequence)

The syndication endpoint is the most reliable source, but GitHub Actions IPs
are often rate-limited. Nitter RSS instances provide a free, no-auth fallback.
"""

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Sources ────────────────────────────────────────────────────────────────

SYNDICATION_URL = (
    "https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
)

# Public Nitter instances (tried in order for RSS fallback).
# These can come and go — add/remove as needed.
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
    "https://nitter.net",
]

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds between retries
INITIAL_DELAY = 2  # seconds before first request (helps avoid burst 429s)


# ── Data types ─────────────────────────────────────────────────────────────

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


# ── Helpers ────────────────────────────────────────────────────────────────

def _clean_tweet_text(raw: str) -> str:
    """Remove HTML entities and URLs from tweet text, keep it readable."""
    text = unescape(raw)
    # Remove t.co URLs
    text = re.sub(r"https?://t\.co/\w+", "", text)
    # Remove HTML tags (Nitter RSS descriptions may contain <br>, <a>, etc.)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_twitter_date(date_str: str) -> Optional[datetime]:
    """Parse Twitter's created_at format: 'Wed Oct 29 05:03:08 +0000 2025'"""
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    return None


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RFC 2822 date from RSS feed (e.g. 'Wed, 03 Jun 2026 10:00:00 GMT')."""
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    return None


def _build_headers(extra: Optional[dict] = None) -> dict:
    """Return a browser-like User-Agent header dict."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    if extra:
        headers.update(extra)
    return headers


# ── Source 1: Twitter syndication endpoint ─────────────────────────────────

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


def _fetch_via_syndication(username: str, hours: int) -> FetchResult:
    """Fetch tweets via Twitter's syndication endpoint."""
    url = SYNDICATION_URL.format(username=username)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    headers = _build_headers({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

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

        all_tweets = _extract_tweets_from_html(resp.text, username)

        if not all_tweets:
            logger.warning("No tweets extracted from response")
            continue

        logger.info(f"Extracted {len(all_tweets)} total tweets from timeline")

        recent = [t for t in all_tweets if t.published >= cutoff]
        recent.sort(key=lambda t: t.published, reverse=True)

        logger.info(f"{len(recent)} tweets within the last {hours}h")
        return FetchResult(tweets=recent)

    return FetchResult(
        error=last_error or "Failed to fetch tweets after all retries"
    )


# ── Source 2: Nitter RSS feeds ─────────────────────────────────────────────

def _parse_nitter_rss(xml_text: str, username: str) -> list[Tweet]:
    """Parse Nitter RSS XML into Tweet objects."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"Failed to parse Nitter RSS XML: {e}")
        return []

    tweets = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        description = item.findtext("description", "")
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")

        # Nitter RSS: title is often the tweet text.
        # Some instances put it in description with HTML.
        raw = title or description
        text = _clean_tweet_text(raw)
        if not text or len(text) < 2:
            continue

        published = _parse_rss_date(pub_date)
        if not published:
            continue

        # Extract tweet ID from the link (last path segment)
        tweet_id = ""
        if link:
            tweet_id = link.rstrip("/").split("/")[-1]

        tweets.append(Tweet(
            id=tweet_id,
            text=text,
            published=published,
            link=link or f"https://twitter.com/{username}/status/{tweet_id}",
        ))

    return tweets


def _fetch_via_nitter_rss(username: str, hours: int) -> FetchResult:
    """Try Nitter RSS instances in sequence until one works."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    headers = _build_headers({
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })

    for instance in NITTER_INSTANCES:
        url = f"{instance}/{username}/rss"
        try:
            logger.info(f"Trying Nitter RSS: {url}")
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 429:
                logger.warning(f"Nitter {instance} rate limited (429), trying next...")
                time.sleep(1)
                continue

            if not resp.ok:
                logger.warning(f"Nitter {instance} returned {resp.status_code}, trying next...")
                continue

            tweets = _parse_nitter_rss(resp.text, username)
            if not tweets:
                logger.warning(f"No tweets parsed from {instance}, trying next...")
                continue

            logger.info(f"Got {len(tweets)} tweets from {instance}")

            recent = [t for t in tweets if t.published >= cutoff]
            recent.sort(key=lambda t: t.published, reverse=True)

            logger.info(f"{len(recent)} tweets within the last {hours}h")
            return FetchResult(tweets=recent)

        except requests.RequestException as e:
            logger.warning(f"Nitter {instance} failed: {e}")
            continue

    return FetchResult(error="All Nitter RSS instances failed")


# ── Main entry point ───────────────────────────────────────────────────────

def fetch_recent_tweets(
    username: str = "aleabitoreddit",
    hours: int = 24,
) -> FetchResult:
    """
    Fetch tweets from the last `hours` hours.

    Tries Twitter's syndication endpoint first, falls back to Nitter RSS
    instances if the primary source is rate-limited or unavailable.

    Returns a FetchResult with tweets sorted newest-first.
    """
    # Small initial delay — helps avoid burst-triggered 429s on syndication
    time.sleep(INITIAL_DELAY)

    # 1. Primary: Twitter syndication endpoint
    logger.info("Primary source: Twitter syndication endpoint")
    result = _fetch_via_syndication(username, hours)
    if not result.error:
        return result
    logger.warning(f"Primary source failed: {result.error}")

    # 2. Fallback: Nitter RSS instances
    logger.info("Fallback: trying Nitter RSS instances...")
    nitter_result = _fetch_via_nitter_rss(username, hours)
    if not nitter_result.error:
        logger.info(f"Nitter RSS fallback succeeded ({len(nitter_result.tweets)} tweets)")
        return nitter_result

    # Both failed
    return FetchResult(
        error=f"All sources exhausted. Primary: {result.error}. Nitter: {nitter_result.error}"
    )
