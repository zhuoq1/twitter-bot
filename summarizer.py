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

SYSTEM_PROMPT = """你是一名金融分析师助手。你的任务是阅读加密货币/交易领域 KOL Serenity (@aleabitoreddit) 的推文，并仅提取与投资相关的建议和市场评论。

忽略以下内容：
- 个人轶事、笑话、表情包和非金融闲聊
- 互动诱导（"点赞转发"、"扣个👋" 等）
- 没有实质内容的模糊表述

提取并总结：
- 提到的具体代币、股票代码（含代码）
- 价格预测、进出场点位或交易策略
- 宏观市场评论（BTC 方向、整体市场情绪）
- 风险管理建议或策略技巧

请用以下格式回复，所有内容使用中文：

📊 **市场情绪**
[一句话概括整体氛围：看涨 / 看跌 / 中性 / 谨慎]

💰 **涉及的资产与代码**
- $代码 — 相关评论摘要

🧠 **关键投资洞察**
- 最重要的建议或分析要点

⚠️ **免责声明**
本文为 AI 从社交媒体内容自动生成，不构成投资建议。投资前请务必自行研究。"""


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
        return "_今天没有新的推文需要总结。_"

    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY not set")

    client = OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL)

    # Build the user message — number tweets for reference
    numbered_tweets = "\n\n---\n\n".join(
        f"推文 {i+1}:\n{t}" for i, t in enumerate(tweets_text)
    )

    user_prompt = f"""以下是 Serenity 过去 24 小时的推文。
请总结其中的投资建议、交易思路或市场评论。

如果这些推文中没有任何投资相关内容，请直接回复：
"今天的推文中未发现投资建议。"

推文列表：
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
