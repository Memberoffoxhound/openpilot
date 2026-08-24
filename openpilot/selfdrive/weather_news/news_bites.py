#!/usr/bin/env python3
"""Google News RSS bites for Tesla / SpaceX / xAI / Neuralink / Boring / Elon."""

import random
import re
from xml.etree import ElementTree as ET

import requests
from openpilot.common.swaglog import cloudlog

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


def fetch_rss_items(max_items: int = 12, timeout: int = 8) -> list[dict]:
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
    cloudlog.warning(f"weather_news: RSS failed: {e}")
  return items


def make_spoken_bite(item: dict, aggressive: bool = False) -> str:
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


def get_news_cycle(num_bites: int = 2, aggressive: bool = False) -> list[str]:
  items = fetch_rss_items(max_items=10)
  if not items:
    return [random.choice((
      "No fresh headlines came through on the last check. The news wires are quiet for the moment.",
      "Couldn't pull new stories right now. We'll try again next cycle.",
    ))]
  random.shuffle(items)
  return [make_spoken_bite(it, aggressive=aggressive) for it in items[:num_bites]]
