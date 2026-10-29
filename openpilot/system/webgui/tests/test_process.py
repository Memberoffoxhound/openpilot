import importlib
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from openpilot.system.webgui import webgui as W


def test_process_config_always_runs_on_device(monkeypatch):
  import openpilot.common.hardware as hw
  import openpilot.system.manager.process_config as pc
  from openpilot.system.manager.process import RestartingPythonProcess
  monkeypatch.setattr(hw, "PC", False)
  try:
    p = next(x for x in importlib.reload(pc).procs if x.name == "webgui")
    assert p.enabled and isinstance(p, RestartingPythonProcess)  # restarts if it ever dies
    assert p.should_run(False, None, None) and p.should_run(True, None, None)  # offroad and onroad, no flag file
    assert callable(importlib.import_module(p.module).main)
  finally:
    monkeypatch.undo()
    importlib.reload(pc)


def test_bind_retries_until_port_free(tmp_path):
  busy = socket.socket()
  busy.bind(("127.0.0.1", 0))
  busy.listen()
  port = busy.getsockname()[1]
  got = []
  th = threading.Thread(target=lambda: got.append(W.serve(W.App(tmp_path), "127.0.0.1", port, retry_s=0.05)), daemon=True)
  th.start()
  time.sleep(0.3)
  assert not got
  busy.close()
  th.join(5)
  assert got and got[0].server_address[1] == port
  got[0].server_close()


def test_standalone_start_creates_dirs_and_serves(tmp_path):
  s = socket.socket()
  s.bind(("127.0.0.1", 0))
  port = s.getsockname()[1]
  s.close()
  env = {**os.environ, "WEBGUI_DATA": str(tmp_path), "WEBGUI_HOST": "127.0.0.1", "WEBGUI_PORT": str(port)}
  proc = subprocess.Popen([sys.executable, "-m", "openpilot.system.webgui.webgui"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  try:
    for _ in range(50):
      try:
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read()
        break
      except OSError:
        time.sleep(0.1)
    assert b"TESLA" in page
    assert urllib.request.urlopen(f"http://127.0.0.1:{port}/api/rec", timeout=2).status == 200
    assert urllib.request.urlopen(f"http://127.0.0.1:{port}/font/TESLA.ttf", timeout=2).status == 200
    assert (tmp_path / "media/0/screenshots").is_dir() and (tmp_path / "media/0/screenrecords").is_dir()
  finally:
    proc.kill()
    proc.wait()
