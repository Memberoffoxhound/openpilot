#!/usr/bin/env python3
"""Topic RSS plus a live world-breaking pass. Aliases: npr, cnn, comma, reddit[:sub], x[:query]. Else Google News."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests
from openpilot.common.swaglog import cloudlog

USER_AGENT = "S3XYPilot-WeatherNews/0.9"
ATOM = "{http://www.w3.org/2005/Atom}"
NPR = ("https://feeds.npr.org/1004/rss.xml", "https://feeds.npr.org/1001/rss.xml")
CNN = (
  "http://rss.cnn.com/rss/cnn_world.rss",
  "https://news.google.com/rss/search?q=site:cnn.com+world+when:12h&hl=en-US&gl=US&ceid=US:en",
)
COMMA_BLOG = (
  "https://news.google.com/rss/search?q=site:blog.comma.ai&hl=en-US&gl=US&ceid=US:en",
)
BREAKING = (
  ("bbc", "https://feeds.bbci.co.uk/news/world/rss.xml"),
  ("google-world", "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"),
  ("google-live", "https://news.google.com/rss/search?q=when:8h+world&hl=en-US&gl=US&ceid=US:en"),
  ("npr", "https://feeds.npr.org/1001/rss.xml"),
)
BREAKING_MAX_AGE_S = 8 * 3600
INTEREST_MAX_AGE_S = 18 * 3600
BLOCK = ("stock price", "shares", "nasdaq", "sec filing")


def clean_title(title: str) -> str:
  title = re.sub(r"\s+-\s+[^-]+$", "", title).strip()
  return re.sub(r"\s+", " ", title)


def _age_s(pub: str) -> float | None:
  if not pub:
    return None
  try:
    dt = parsedate_to_datetime(pub)
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()
  except Exception:
    return None


def _is_new(pub: str, max_age_s: float) -> bool:
  age = _age_s(pub)
  if age is None:
    return True
  return 0 <= age <= max_age_s


def _text(el) -> str:
  if el is None:
    return ""
  if el.text:
    return el.text
  return "".join(el.itertext())


def _parse_items(xml: bytes, source: str, max_items: int, *, max_age_s: float | None = None) -> list[dict]:
  items: list[dict] = []
  root = ET.fromstring(xml)
  nodes = list(root.findall(".//item")) or list(root.findall(f".//{ATOM}entry"))
  for node in nodes:
    title = clean_title(_text(node.find("title") if node.find("title") is not None else node.find(f"{ATOM}title")))
    if not title or any(b in title.lower() for b in BLOCK):
      continue
    pub = _text(node.find("pubDate")) or _text(node.find(f"{ATOM}updated")) or _text(node.find(f"{ATOM}published"))
    if max_age_s is not None and not _is_new(pub, max_age_s):
      continue
    desc_el = node.find("description") if node.find("description") is not None else node.find(f"{ATOM}summary")
    desc = re.sub(r"<[^>]+>", "", _text(desc_el))[:220]
    link_el = node.find("link")
    link = ""
    if link_el is not None:
      link = (link_el.get("href") or _text(link_el)).strip()
    age = _age_s(pub)
    items.append({
      "source": source, "title": title, "desc": desc, "link": link, "pub": pub,
      "age_s": None if age is None else int(age),
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


def _google(query: str) -> str:
  return (
    "https://news.google.com/rss/search"
    f"?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
  )


def _from_urls(urls: tuple[str, ...], source: str, n: int, timeout: int, *, max_age_s: float | None = None) -> list[dict]:
  for url in urls:
    raw = _get(url, timeout=timeout)
    if raw:
      items = _parse_items(raw, source, n, max_age_s=max_age_s)
      if items:
        return items
  return []


def _topic_items(topic: str, timeout: int) -> list[dict]:
  t = topic.strip()
  key = t.lower()
  age = INTEREST_MAX_AGE_S
  if key in ("npr", "world", "npr world"):
    return _from_urls(NPR, "npr", 3, timeout, max_age_s=age)
  if key in ("cnn", "cnn world"):
    return _from_urls(CNN, "cnn", 2, timeout, max_age_s=age)
  if key in ("comma", "comma.ai", "blog.comma.ai"):
    return _from_urls(COMMA_BLOG, "comma", 2, timeout, max_age_s=age)
  if key == "reddit" or key.startswith("reddit:") or key.startswith("r/"):
    sub = "commaai"
    if ":" in t:
      sub = t.split(":", 1)[1].strip().lstrip("r/").strip("/") or sub
    elif key.startswith("r/"):
      sub = t.split("/", 1)[1].strip().strip("/") or sub
    urls = (
      f"https://www.reddit.com/r/{sub}/.rss",
      f"https://old.reddit.com/r/{sub}/.rss",
      _google(f"site:reddit.com/r/{sub}"),
    )
    return _from_urls(urls, f"reddit/{sub}", 2, timeout, max_age_s=age)
  if key in ("x", "twitter") or key.startswith("x:") or key.startswith("@"):
    q = "openpilot OR comma.ai"
    if key.startswith("x:"):
      q = t.split(":", 1)[1].strip() or q
    elif key.startswith("@"):
      q = t
    return _from_urls((_google(f"site:x.com {q}"),), "x", 2, timeout, max_age_s=age)
  return _from_urls((_google(f"{t} when:18h"), _google(t)), t, 2, timeout, max_age_s=age)


def _dedupe(items: list[dict], skip: set[str] | None, limit: int) -> list[dict]:
  out: list[dict] = []
  seen: set[str] = {s.lower() for s in (skip or set())}
  ranked = sorted(items, key=lambda it: it.get("age_s") if it.get("age_s") is not None else 10**9)
  for it in ranked:
    k = it["title"].lower()
    if k in seen:
      continue
    seen.add(k)
    out.append(it)
    if len(out) >= limit:
      break
  return out


def fetch_rss_items(topics: list[str] | None = None, timeout: int = 8,
                    skip: set[str] | None = None, limit: int = 8) -> list[dict]:
  pooled: list[dict] = []
  for topic in (topics or ["npr"]):
    pooled.extend(_topic_items(topic, timeout))
  return _dedupe(pooled, skip, limit)


def fetch_breaking_news(timeout: int = 8, skip: set[str] | None = None, limit: int = 5) -> list[dict]:
  pooled: list[dict] = []
  for source, url in BREAKING:
    raw = _get(url, timeout=timeout)
    if not raw:
      continue
    pooled.extend(_parse_items(raw, source, 8, max_age_s=BREAKING_MAX_AGE_S))
  return _dedupe(pooled, skip, limit)
