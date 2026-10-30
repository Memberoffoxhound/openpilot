"""
Jetlink's hooks into hardwared's hardware_thread, one object so hardwared.py
carries one-line call sites. Ported from zoompilot develop 632b0b0
(sunnypilot/system/hardware/hardwared_ext.py:15-68): the accelerator alert and
the power-off; zoompilot's stock-ECU hand-back and forced offroad are not
Jetlink's and stay out.

An accelerator on its own supply outlives the comma, so a shutdown asks it to
power off (jetlink's shutdown_step, which asks once and keeps its own
deadline) and DoShutdown waits until jetlink says it may, or
ACCELERATOR_OFF_WAIT_T has passed. hardware_thread keeps publishing
deviceState through that wait, and no drive may start under the power-off that
follows (powering_off is a startup condition). With the Jetlink setting off,
none of this imports jetlink (jetlink_adapter's setting gate).
"""
import time
from collections.abc import Callable

from openpilot.selfdrive import jetlink_adapter

# the longest a shutdown waits on the accelerator: jetlink's own deadline
# (SHUTDOWN_TIMEOUT) and 5 s, so a jetlink regression never keeps a comma on
ACCELERATOR_OFF_WAIT_T = 25.0 + 5.0


class JetlinkPower:
  def __init__(self, now: Callable[[], float] = time.monotonic, log=None) -> None:
    self.now = now
    self.log = log
    self.accelerator_off_ts: float | None = None
    self._alert_error: str | None = None

  @property
  def powering_off(self) -> bool:
    return self.accelerator_off_ts is not None

  def alerts(self, set_offroad_alert: Callable[..., None]) -> None:
    # an enabled accelerator that cannot come up is otherwise silently absent.
    # Highland: never takes hardwared down (a params library older than the key)
    try:
      accelerator_error = jetlink_adapter.reason()
      set_offroad_alert(jetlink_adapter.OFFROAD_ALERT, accelerator_error is not None, extra_text=accelerator_error)
      self._alert_error = None
    except Exception as e:
      if self.log is not None and self._alert_error != (text := f"{type(e).__name__}: {e}"):
        self._alert_error = text
        self.log.exception(f"jetlink: offroad alert failed: {text}")

  def shutdown_ready(self, should_shutdown: bool, off_ts: float | None) -> bool:
    """True once hardwared may put DoShutdown. From the first should_shutdown on, the power
    monitor is not consulted again."""
    if should_shutdown and self.accelerator_off_ts is None:
      if self.log is not None:
        self.log.warning(f"shutting device down, offroad since {off_ts}")
      self.accelerator_off_ts = self.now()
    wanted = self.accelerator_off_ts is not None
    # every loop from boot: the first also clears a request an earlier hardwared left
    ready = jetlink_adapter.shutdown_step(wanted, f"comma shutting down, offroad since {off_ts}")
    return wanted and (ready or self.now() - self.accelerator_off_ts >= ACCELERATOR_OFF_WAIT_T)
