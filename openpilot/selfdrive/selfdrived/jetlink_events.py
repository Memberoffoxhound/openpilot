"""
Jetlink's onroad events in selfdrived: a big model that joins mid-drive.
Ported from zoompilot develop 632b0b0
(sunnypilot/selfdrive/selfdrived/accelerator_events.py:32-70) onto Highland's
native events (log.capnp jetlinkBigModelAvailable/Lost/Active and the existing
bigModelLoading NO_ENTRY). Highland has no modelDataV2SP, so jetlink's tracker
reads the joining model's state off modeld's runtime record itself
(hooks.SwapTracker, a few times a second).

Nothing here disengages: the offer and the chime are prompts, the link lost a
warning while the small model drives on, and no_entry only refuses an
engagement in the second after a swap. With the Jetlink setting off at
selfdrived's start, swap_events() is None, jetlink is never imported, and
update() is a no-op.
"""
from openpilot.cereal import log
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive import jetlink_adapter

EventName = log.OnroadEvent.EventName

# jetlink's lengths (events.OFFER_S, HANDBACK_S, SWITCHING_S) in selfdrived's
# ticks, for the tests; written out, as selfdrived starts without jetlink
OFFER_TICKS = round(3. / DT_CTRL)
HANDBACK_TICKS = round(5. / DT_CTRL)
SWITCHING_TICKS = round(1. / DT_CTRL)


class JetlinkEvents:
  # An accelerator is optional: its daemon exiting costs the big model, never
  # engagement. Without this a dead link owner would be processNotRunning
  OPTIONAL_PROCESSES = frozenset({jetlink_adapter.OWNER})

  def __init__(self):
    # jetlink's tracker, behind the hooks' net; None with the link off or without jetlink
    self.swap = jetlink_adapter.swap_events(DT_CTRL)

  @property
  def settling(self) -> bool:
    """Within a second of the big model swapping in or handing back."""
    return self.swap is not None and self.swap.settling

  def update(self, sm, in_control: bool, events) -> None:
    """`in_control`: openpilot is engaged (selfdrived's enabled), the rule the
    adapter's swap gate waits on (Stock.engaged)."""
    if self.swap is None:
      return
    fresh = sm.seen['modelV2'] and sm.alive['modelV2'] and sm.valid['modelV2']
    big = sm.alive['modelV2'] and sm.valid['modelV2'] and sm['modelV2'].big
    flags = self.swap.update(fresh, big, in_control)
    if flags.offer:
      events.add(EventName.jetlinkBigModelAvailable)
    if flags.link_lost:
      events.add(EventName.jetlinkBigModelLost)
    if flags.no_entry:
      # upstream's no-entry for a big model that is not ready to drive
      events.add(EventName.bigModelLoading)
    if flags.chime:
      events.add(EventName.jetlinkBigModelActive)
