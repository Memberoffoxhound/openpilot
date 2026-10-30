import time

import pytest


@pytest.fixture
def tz(monkeypatch):
  """Run in a device zone: the store follows the system zone (TZ / /etc/localtime)."""
  def use(zone: str):
    monkeypatch.setenv("TZ", zone)
    time.tzset()
  yield use
  monkeypatch.undo()
  time.tzset()


@pytest.fixture(autouse=True)
def chicago(tz):
  tz("America/Chicago")
