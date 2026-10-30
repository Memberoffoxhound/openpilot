"""selfdrived's catch-all comm check: services not up yet since start read as "System Initializing",
a real comm issue (after they were up, while engaged, or STARTUP_MAX_S on) keeps its alert.
Runs the block from selfdrived.py against fakes; selfdrived itself needs msgq."""
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = (Path(__file__).resolve().parents[1] / "selfdrived.py").read_text()
BLOCK = textwrap.dedent(SRC[SRC.index("    all_checks = self.sm.all_checks()"):SRC.index("      logs = {")])
DT_CTRL = 0.01
STARTUP_MAX_S = float(SRC.split("STARTUP_MAX_S = ")[1].split()[0])


class SM:
  def __init__(self, ok, alive=True, frame=100):
    self.ok, self.alive, self.frame = ok, alive, frame

  def all_checks(self):
    return self.ok

  def all_alive(self):
    return self.alive

  def all_freq_ok(self):
    return True


def check(sd, sm):
  sd.sm, events = sm, []
  env = {"self": sd, "no_system_errors": True, "big_model_settling": False, "DT_CTRL": DT_CTRL,
         "STARTUP_MAX_S": STARTUP_MAX_S, "EventName": SimpleNamespace(selfdriveInitializing="init", commIssue="comm",
                                                                    commIssueAvgFreq="freq")}
  sd.events = SimpleNamespace(add=events.append)
  exec(BLOCK, env)
  return events


@pytest.fixture
def sd():
  return SimpleNamespace(services_up=False, enabled=False)


def test_late_model_reads_initializing(sd):
  # route 00000053: engage at 18.9 s, modeld's first outputs at 17.9 s, everything valid at 19.2 s
  assert check(sd, SM(ok=False, frame=1885)) == ["init"]
  assert check(sd, SM(ok=True, frame=1916)) == []
  assert sd.services_up


def test_comm_issue_after_services_were_up(sd):
  check(sd, SM(ok=True))
  assert check(sd, SM(ok=False, alive=False)) == ["comm"]


def test_comm_issue_while_engaged(sd):
  sd.enabled = True
  assert check(sd, SM(ok=False)) == ["comm"]       # soft disable path unchanged


def test_comm_issue_if_never_up(sd):
  assert check(sd, SM(ok=False, frame=int(STARTUP_MAX_S / DT_CTRL) + 1)) == ["comm"]


def test_initializing_alert_text():
  ev = (Path(__file__).resolve().parents[1] / "events.py").read_text()
  assert 'EventName.selfdriveInitializing: {\n    ET.NO_ENTRY: NoEntryAlert("System Initializing"),' in ev
