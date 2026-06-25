"""Grok X/Twitter search — daily opportunity scanner.

Uses xAI Grok API to search X for posts about:
- passive income, micro SaaS, AI wrappers
- DeFi yield, staking, airdrops
- automation bots, side project launches
- indie hacker revenue reports

Outputs JSON lines to stdout, one RawItem per line.
Pipeline can ingest via: python scripts/grok_search.py | python run.py ingest-stdin
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import httpx

API = "https://api.x.ai/v1/chat/completions"

SEARCH_QUERIES = [
    # Money-making signals
    "passive income revenue MRR ARR $/month site:x.com",
    "micro saas launch shipped indie hacker site:x.com",
    "ai wrapper gpt wrapper built revenue site:x.com",
    "side hustle make money online 2026 site:x.com",
    "solopreneur solo founder revenue report site:x.com",

    # Crypto/DeFi signals
    "defi yield farming APY staking reward site:x.com",
    "airdrop claim free tokens crypto site:x.com",
    "trading bot automated profit site:x.com",

    # Demand gap signals
    "wish there was tool alternative cheaper site:x.com",
    "someone should build bot automate site:x.com",

    # Automation/bots
    "telegram bot discord bot revenue site:x.com",
    "scraper automation pipeline passive site:x.com",
]

SYSTEM_PROMPT = """You are a search assistant analyzing X/Twitter for business opportunities.

For each query, search X and return relevant posts. Focus on:
- Posts showing real revenue numbers (MRR, ARR, $X/month)
- Product launches with actual traction
- Money-making methods or case studies
- DeFi strategies with real APY/APR
- Automation tools that generate income
- Demand signals (people asking for tools that don't exist)

Return a JSON array of objects with these fields:
- id: tweet ID (string)
- author: username (string)
- text: full tweet text (string)
- url: tweet URL (string)
- created_at: ISO timestamp (string)
- likes: number of likes (int)
- retweets: number of retweets (int)
- query: which search query found this (string)

Return ONLY valid JSON. No markdown, no explanation. Max 15 results per query.
Skip retweets, pure opinions, and posts without substance."""


def search_grok(api_key: str, query: str) -> list[dict]:
    """Call Grok API to search X for a query."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "grok-2-1212",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Search X for: {query}"},
        ],
        "temperature": 0.3,
        "max_tokens": 4000,
    }

    try:
        with httpx.Client(timeout=60) as client:
            r = client.post(API, json=payload, headers=headers)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return parse_response(content, query)
    except Exception as e:
        print(f"[grok] error for query '{query[:40]}...': {e}", file=sys.stderr)
        return []


def parse_response(content: str, query: str) -> list[dict]:
    """Parse Grok's JSON response into tweet objects."""
    import re

    json_match = re.search(r"\[.*\]", content, re.DOTALL)
    if not json_match:
        return []

    try:
        tweets = json.loads(json_match.group())
    except json.JSONDecodeError:
        return []

    # Add query field to each tweet
    for tw in tweets:
        tw["query"] = query
    return tweets


def tweet_to_raw_item(tw: dict) -> dict:
    """Convert a tweet dict to RHR RawItem format."""
    tw_id = str(tw.get("id", ""))
    author = tw.get("author", "")
    url = tw.get("url") or f"https://x.com/{author}/status/{tw_id}"

    return {
        "source": "x_via_grok",
        "source_item_id": f"x:{tw_id}",
        "url": url,
        "title": tw.get("text", "")[:120],
        "body_text": tw.get("text"),
        "author": author,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "published_at": tw.get("created_at"),
        "points": tw.get("likes"),
        "comments_count": tw.get("retweets"),
    }


def main():
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        print("[grok] XAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    all_items = []
    seen_ids: set[str] = set()

    for query in SEARCH_QUERIES:
        tweets = search_grok(api_key, query)
        for tw in tweets:
            item = tweet_to_raw_item(tw)
            if item["source_item_id"] not in seen_ids:
                seen_ids.add(item["source_item_id"])
                all_items.append(item)

    # Output as JSON lines to stdout
    for item in all_items:
        print(json.dumps(item, ensure_ascii=False))

    print(f"[grok] found {len(all_items)} unique items from {len(SEARCH_QUERIES)} queries", file=sys.stderr)


if __name__ == "__main__":
    main()
