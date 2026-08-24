#!/usr/bin/env python3
"""
Elon Musk companies news bites for the alpha.
Fetches recent headlines via Google News RSS (no key) focused on
Tesla, SpaceX, xAI, Neuralink, The Boring Company, X.
Produces short detailed spoken bites. Randomized order/selection.
"""

import random
import re
from typing import List, Dict
from xml.etree import ElementTree as ET
import requests

QUERIES = [
    "Tesla",
    "SpaceX",
    "xAI",
    "Neuralink",
    "Boring Company",
    "Elon Musk",
]

BLOCK_KEYWORDS = ["stock price", "shares", "nasdaq", "sec filing", "lawsuit update"]


def clean_title(title: str) -> str:
    title = re.sub(r"\s+-\s+[^-]+$", "", title)
    title = title.strip()
    return title


def fetch_rss_items(max_items: int = 12, timeout: int = 8) -> List[Dict]:
    items = []
    q = ' OR '.join([f'"{x}"' if ' ' in x else x for x in QUERIES])
    url = (
        "https://news.google.com/rss/search"
        f"?q={requests.utils.quote(q)}"
        "&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "S3XYPilotWeatherNews/0.2"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:max_items * 2]:
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            if title_el is None or not title_el.text:
                continue
            title = clean_title(title_el.text)
            if any(b.lower() in title.lower() for b in BLOCK_KEYWORDS):
                continue
            desc = ""
            if desc_el is not None and desc_el.text:
                desc = re.sub(r"<[^>]+>", "", desc_el.text)[:220]
            items.append({
                "title": title,
                "desc": desc,
                "link": link_el.text if link_el is not None else "",
                "pub": pub_el.text if pub_el is not None else "",
            })
            if len(items) >= max_items:
                break
    except Exception as e:
        print(f"[news_bites] fetch failed: {e}")
    return items


def make_spoken_bite(item: Dict, aggressive: bool = False) -> str:
    title = item["title"]
    desc = item.get("desc", "")

    if aggressive:
        intros = [
            "Hot off the press, you degenerates:",
            "Listen up, more Elon empire bullshit:",
            "Your daily dose of rocket-powered chaos:",
            "Fresh MF'n news from the Tesla-SpaceX-xAI circus:",
        ]
        outros = [
            "Don't say I never told you.",
            "Now go touch grass or something.",
            "You're welcome, you news junkies.",
        ]
        body = f"{title}."
        if desc and len(desc) > 40:
            body += f" {desc[:160]}..."
        return f"{random.choice(intros)} {body} {random.choice(outros)}"
    else:
        intros = [
            "In Elon Musk company news,",
            "Quick update from the Tesla and SpaceX world,",
            "Here's a recent development worth knowing,",
            "From the broader Elon portfolio,",
        ]
        body = f"{title}."
        if desc and len(desc) > 40:
            body += f" {desc[:180]}"
        return f"{random.choice(intros)} {body}"


def get_news_cycle(num_bites: int = 2, aggressive: bool = False) -> List[str]:
    items = fetch_rss_items(max_items=10)
    if not items:
        fallbacks = [
            "No fresh headlines came through on the last check. The news wires are quiet for the moment.",
            "Couldn't pull new stories right now. We'll try again next cycle.",
        ]
        return [random.choice(fallbacks)]

    random.shuffle(items)
    chosen = items[:num_bites]
    return [make_spoken_bite(it, aggressive=aggressive) for it in chosen]


if __name__ == "__main__":
    print("=== PERSONABLE NEWS ===")
    for b in get_news_cycle(2, aggressive=False):
        print(b)
        print("---")
    print("\n=== AGGRESSIVE NEWS ===")
    for b in get_news_cycle(2, aggressive=True):
        print(b)
        print("---")
