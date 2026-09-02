#!/usr/bin/env python3
"""LAN UI for S3XYPilot. No auth — bind on the local network only."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

PORT = int(os.environ.get("DEVICEWEB_PORT", "8088"))
STATIC_DIR = Path(__file__).parent / "static"
OPENPILOT_DIR = Path(os.environ.get("OPENPILOT_PATH", "/data/openpilot"))
FONT_PATH = OPENPILOT_DIR / "openpilot/selfdrive/assets/fonts/TESLA.ttf"
SHOT_DIR = Path("/data/media/0/screenshots")
SHOT_REQ = Path("/data/screenshot_request")
SHOT_PLAY = Path("/data/screenshot_play")
TRIP_PATH = Path("/data/trip_meter.json")
WEBRTC_CAMERAS = ("road", "wideRoad", "driver")

_cpu_last: tuple[int, int] | None = None
_live_sm = None


def _params() -> Params:
  return Params()
