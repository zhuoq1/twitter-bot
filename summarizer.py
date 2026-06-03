"""
Summarizes tweets using the DeepSeek API.
Extracts and condenses investment-related advice from raw tweet text.
"""

import logging
import os
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """You are a financial analyst assistant. Your job is to read tweets from
a crypto/trading influencer named Serenity (@aleabitoreddit) and extract ONLY the
investment-related advice and market commentary.

Ignore:
- Personal anecdotes, jokes, memes, and non-financial chatter
- Engagement bait ("like and retweet", "drop a 👋", etc.)
- Vague statements with no actionable substance

Extract and summarize:
- Specific coins, tokens, or stocks mentioned (with tickers)
- Price predictions, entry/exit points, or trade setups
- Macro market commentary (BTC direction, overall market sentiment)
- Risk management advice or strategy tips

Format your response as:

📊 **MARKET SENTIMENT**
[One-line overall vibe: bullish / bearish / neutral / cautious]

💰 **ASSETS & TICKERS MENTIONED**
- $TICKER — what was said about it

🧠 **KEY INVESTMENT INSIGHTS**
- Bullet points of the most important advice or analysis

⚠️ **DISCLAIMER**
This is an AI-generated summary of social media content. Not financial advice.
Always do your own research before investing."""


def summarize_tweets(tweets_text: list[str], api_key: Optional[str] = None) -> str:
    """
    Send tweets to DeepSeek and return a structured investment summary.

    Args:
        tweets_text: List of cleaned tweet bodies.
        api_key: DeepSeek API key. Falls back to DEEPSEEK_API_KEY env var.

    Returns:
        Markdown-formatted summary string.
    """
    if not tweets_text:
        return "_No tweets to summarize today._"

    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY not set")

    client = OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL)

    # Build the user message — number tweets for reference
    numbered_tweets = "\n\n---\n\n".join(
        f"Tweet {i+1}:\n{t}" for i, t in enumerate(tweets_text)
    )

    user_prompt = f"""Here are Serenity's tweets from the last 24 hours.
Summarize any investment advice, trade ideas, or market commentary.

If there is NO investment-related content in any of these tweets, simply say:
"No investment advice found in today's tweets."

TWEETS:
{numbered_tweets}"""

    logger.info(f"Sending {len(tweets_text)} tweets to DeepSeek for summarization...")

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,  # lower temp for more faithful extraction
            max_tokens=1500,
        )
        summary = response.choices[0].message.content or ""
        logger.info(f"Summarization complete ({len(summary)} chars)")
        return summary.strip()

    except Exception as e:
        logger.error(f"DeepSeek API call failed: {e}")
        raise
