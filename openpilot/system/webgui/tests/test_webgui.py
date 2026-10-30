import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from openpilot.system.webgui import webgui as W

GB = 1024**3


class Clock:
  def __init__(self, t=1_000_000.0):
    self.t = t

  def __call__(self):
    return self.t


@pytest.fixture
def env(tmp_path):
  clk, free = Clock(), {"b": 50 * GB}
  app = W.App(tmp_path, wall=clk, free=lambda p: free["b"])
  app.shots.mkdir(parents=True)
  app.rec.dir.mkdir(parents=True)
  srv = W.make_server(app, "127.0.0.1", 0)
  threading.Thread(target=srv.serve_forever, daemon=True).start()
  yield app, clk, free, f"http://127.0.0.1:{srv.server_address[1]}"
  srv.shutdown()


def req(url, method="GET", body=None, raw=False, ctype="application/json"):
  h = {"Content-Type": ctype}
  r = urllib.request.Request(url, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
  try:
    with urllib.request.urlopen(r, timeout=5) as resp:
      data = resp.read()
      return resp.status, (data if raw else json.loads(data or b"{}")), resp.headers
  except urllib.error.HTTPError as e:
    return e.code, json.loads(e.read() or b"{}"), e.headers


def ui_state(app, clk, **kw):
  st = {"recording": True, "name": "a.mp4", "started": clk.t, "max_s": 60, "updated": clk.t, "error": ""} | kw
  app.rec.state_f.write_text(json.dumps(st))


# --- path traversal ---
@pytest.mark.parametrize("name", ["../secret.png", "..%2Fsecret.png", "%2e%2e%2fsecret.png", "a/../../x.png",
                                  ".hidden.png", "x.png/..", "evil.sh", "a.png.sh", "..png", "a..png"])
def test_traversal_rejected(env, name):
  app, _, _, u = env
  (app.data / "x.png").write_bytes(b"secret")
  (app.data / "secret.png").write_bytes(b"secret")
  assert req(u + "/media/shots/" + name)[0] == 404
  assert req(u + "/api/shots/" + name, "DELETE")[0] == 404
  assert (app.data / "secret.png").exists() and (app.data / "x.png").exists()


def test_symlink_rejected(env):
  app, _, _, u = env
  (app.data / "secret.png").write_bytes(b"s")
  os.symlink(app.data / "secret.png", app.shots / "link.png")
  assert req(u + "/media/shots/link.png")[0] == 404
  assert req(u + "/api/shots/link.png", "DELETE")[0] == 404
  assert (app.data / "secret.png").exists()


def test_shot_list_view_delete_range(env):
  app, _, _, u = env
  (app.shots / "2026-10-29--10-00-00.png").write_bytes(b"0123456789")
  (app.shots / "notes.txt").write_text("x")
  _, j, _ = req(u + "/api/shots")
  assert [f["name"] for f in j["items"]] == ["2026-10-29--10-00-00.png"]
  r = urllib.request.Request(u + "/media/shots/2026-10-29--10-00-00.png", headers={"Range": "bytes=2-5"})
  with urllib.request.urlopen(r) as resp:
    assert resp.status == 206 and resp.read() == b"2345" and resp.headers["Content-Range"] == "bytes 2-5/10"
  assert req(u + "/api/shots/2026-10-29--10-00-00.png", "DELETE")[0] == 200
  assert req(u + "/api/shots")[1]["items"] == []


def test_capture_writes_request(env):
  app, *_ = env
  assert app.capture(wait_s=0.2) == {"ok": True, "pending": True}
  assert app.shot_req.read_text() == "1"


# --- recording guards (server half) ---
def test_rec_start_writes_request(env):
  app, _, _, u = env
  code, j, _ = req(u + "/api/rec/start", "POST", {"max_s": 9999, "fps": 99})
  assert code == 200 and j["max_s"] == W.MAX_REC_S
  r = json.loads(app.rec.req.read_text())
  assert r["max_s"] == W.MAX_REC_S and r["fps"] == 30 and r["name"].endswith(".mp4")
  assert req(u + "/api/rec/start", "POST", {})[0] == 409  # pending counts as busy


def test_rec_refuses_low_space_and_bad_input(env):
  app, _, free, u = env
  free["b"] = W.MIN_FREE - 1
  assert req(u + "/api/rec/start", "POST", {})[0] == 507
  free["b"] = 50 * GB
  assert req(u + "/api/rec/start", "POST", {"max_s": "abc"})[0] == 400
  assert not app.rec.req.exists()


def test_rec_busy_stale_and_watchdog(env):
  app, clk, _, u = env
  ui_state(app, clk)
  assert req(u + "/api/rec/start", "POST", {})[0] == 409
  clk.t += 30
  ui_state(app, clk, started=clk.t - 30)
  s = app.rec.status()
  assert s["recording"] and s["elapsed"] == 30 and not app.rec.stop_f.exists()
  clk.t += 60  # past max_s + grace while UI still claims recording
  ui_state(app, clk, started=clk.t - 90)
  assert app.rec.status()["recording"] and app.rec.stop_f.exists()
  clk.t += W.STALE_S + 1  # UI died: state not refreshed
  s = app.rec.status()
  assert not s["recording"] and s["stale"]
  assert req(u + "/api/rec/start", "POST", {})[0] == 200


def test_rec_unclaimed_request_expires(env):
  app, clk, _, _ = env
  assert app.rec.start(30)[0] == 200
  clk.t += W.STALE_S + 1
  s = app.rec.status()
  assert not s["pending"] and "ui process" in s["error"] and not app.rec.req.exists()


def test_rec_stop_and_no_delete_while_recording(env):
  app, clk, _, u = env
  (app.rec.dir / "a.mp4").write_bytes(b"x")
  ui_state(app, clk)
  assert req(u + "/api/recs/a.mp4", "DELETE")[0] == 409
  assert req(u + "/api/rec/stop", "POST", {})[0] == 200 and app.rec.stop_f.exists()
  ui_state(app, clk, recording=False)
  assert req(u + "/api/recs/a.mp4", "DELETE")[0] == 200


def test_mock_stats_labelled(tmp_path):
  app = W.App(tmp_path, mock=True)
  s = app.stats()
  assert s["mock"] and set(s["src"].values()) == {"MOCK"}


def test_param_keys_exist():
  import re
  from pathlib import Path
  from openpilot.system.webgui import stats
  src = (Path(stats.__file__).parents[2] / "common/params_keys.h").read_text()
  keys = set(re.findall(r'\{"(\w+)",', src))
  assert set(stats.PARAMS) <= keys
  used = set(re.findall(r'p\.get(?:_bool)?\("(\w+)"', Path(stats.__file__).read_text()) +
             re.findall(r'_s\(p, "(\w+)"\)', Path(stats.__file__).read_text()))
  assert used and used <= set(stats.PARAMS)


def test_fonts_public_whitelisted(env):
  _, _, _, u = env
  for f in W.FONTS:
    code, body, h = req(u + "/font/" + f, raw=True)
    assert code == 200 and h["Content-Type"] == "font/ttf" and len(body) > 10000
  for bad in ("Inter-Bold.ttf", "..%2Fsecret.png", "../../common/params.py", "TESLA-LICENSE.txt"):
    assert req(u + "/font/" + bad)[0] == 404


def test_no_auth(env):
  _, _, _, u = env
  assert req(u + "/", raw=True)[0] == 200 and req(u + "/api/stats")[0] == 200 and req(u + "/api/rec")[0] == 200


def test_post_requires_json(env):
  app, _, _, u = env
  for path in ("/api/shots", "/api/rec/start", "/api/rec/stop"):
    assert req(u + path, "POST", {}, ctype="text/plain")[0] == 415, path
  assert not app.rec.req.exists() and not app.rec.stop_f.exists() and not app.shot_req.exists()
