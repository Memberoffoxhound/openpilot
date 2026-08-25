#!/usr/bin/env python3
"""RSS: Elon-world, new Aptera Motors, CNN world."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests
from openpilot.common.swaglog import cloudlog

USER_AGENT = "S3XYPilot-WeatherNews/0.7"
ELON_QUERIES = ("Tesla", "SpaceX", "xAI", "Neuralink", "Boring Company", "Elon Musk")
APTERA_QUERY = '"Aptera Motors" OR Aptera solar EV'
CNN_WORLD = (
  "http://rss.cnn.com/rss/cnn_world.rss",
  "https://rss.cnn.com/rss/cnn_world.rss",
  "https://news.google.com/rss/search?q=site:cnn.com+world&hl=en-US&gl=US&ceid=US:en",
)
APTERA_MAX_AGE_S = 72 * 3600
BLOCK_KEYWORDS = ("stock price", "shares", "nasdaq", "sec filing", "lawsuit update")


def clean_title(title: str) -> str:
  return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def _is_new(pub: str, max_age_s: int = APTERA_MAX_AGE_S) -> bool:
  if not pub:
    return True
  try:
    dt = parsedate_to_datetime(pub)
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() <= max_age_s
  except Exception:
    return True


def _parse_items(xml: bytes, source: str, max_items: int, *, require_new: bool = False) -> list[dict]:
  items: list[dict] = []
  root = ET.fromstring(xml)
  for item in root.findall(".//item"):
    title_el = item.find("title")
    if title_el is None or not title_el.text:
      continue
    title = clean_title(title_el.text)
    if any(b in title.lower() for b in BLOCK_KEYWORDS):
      continue
    pub_el = item.find("pubDate")
    pub = pub_el.text if pub_el is not None and pub_el.text else ""
    if require_new and not _is_new(pub):
      continue
    desc_el = item.find("description")
    desc = ""
    if desc_el is not None and desc_el.text:
      desc = re.sub(r"<[^>]+>", "", desc_el.text)[:220]
    link_el = item.find("link")
    items.append({
      "source": source,
      "title": title,
      "desc": desc,
      "link": link_el.text if link_el is not None else "",
      "pub": pub,
    })
    if len(items) >= max_items:
      break
  return items


def _get(url: str, timeout: int = 8) -> bytes | None:
  try:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.content
  except Exception as e:
    cloudlog.warning(f"weather_news: RSS {url}: {e}")
    return None


def _google_rss(query: str) -> str:
  return (
    "https://news.google.com/rss/search"
    f"?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
  )


def fetch_rss_items(max_items: int = 12, timeout: int = 8) -> list[dict]:
  out: list[dict] = []

  aptera_xml = _get(_google_rss(APTERA_QUERY), timeout=timeout)
  if aptera_xml:
    out.extend(_parse_items(aptera_xml, "aptera", 2, require_new=True))

  for url in CNN_WORLD:
    cnn_xml = _get(url, timeout=timeout)
    if cnn_xml:
      world = _parse_items(cnn_xml, "cnn", 1)
      out.extend(world)
      break

  q = " OR ".join([f'"{x}"' if " " in x else x for x in ELON_QUERIES])
  elon_xml = _get(_google_rss(q), timeout=timeout)
  if elon_xml:
    elon = _parse_items(elon_xml, "elon", max_items)
    seen = {i["title"].lower() for i in out}
    for it in elon:
      if it["title"].lower() not in seen:
        out.append(it)
        seen.add(it["title"].lower())

  return out
