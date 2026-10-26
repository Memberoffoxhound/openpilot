# Porting TeslaPilot additions to other forks

## Drive summary card (any car, any fork)

No Tesla, TeslaPilot or Jetlink code, no gear detection, no assets.

**Copy:** `selfdrive/ui/lib/drive_summary.py`, `selfdrive/ui/mici/widgets/{drive_summary_card,card_slide,trip_row}.py`, `selfdrive/ui/tests/test_drive_summary.py`.

**Params** (`common/params_keys.h`; read tolerantly, so an older params library just turns the feature off):
```
{"DriveSummary", {PERSISTENT, BOOL, "0"}},
{"DriveSummaryLast", {PERSISTENT, JSON}},
```
Here the "Go Offroad in Park" toggle sets `DriveSummary`; elsewhere add a `BigParamControl("drive summary", "DriveSummary")`.

**Hooks** (mici main layout):
1. `_update_state`: `drive_summary.tick(ui_state)`.
2. `__init__`: `self._drive_summary = DriveSummaryCard()`. Optional `stats_fn` (returns `today_m/today_e/week_m/week_e/streak_days`; default: the card's own 14-day totals) and `early_fn` (returns `"show"`/`"cut"`/`None` while onroad; TeslaPilot passes `park_card.early_event`).
3. End of `_render`, after `super()._render(...)`: `self._drive_summary.render(self._rect, self._onroad_layout.rect.x)`.
4. `_handle_transitions`:
   ```python
   if ui_state.started:
     self._drive_summary.cancel()
     self._onroad_time_delay = rl.get_time()      # stock
   elif not self._drive_summary.hold_home():
     self._scroll_to(self._home_layout)           # stock

   if self._drive_summary.release_home():
     self._scroll_to(self._home_layout)
   ```
5. `_handle_mouse_release`: `if self._drive_summary.dismiss_on_tap(): return` before `super()`, and add `and not self._drive_summary.visible` to the scroller's `set_scrolling_enabled`.

**Theme:** `drive_summary.accent_rgb()` tries `layouts.settings.common.theme_rgb()`, else comma green. Change that one function for another theme manager.

**Behavior:** shows at the offroad edge when the toggle is on, the trip is >= 0.1 mi and 30 s, and the car is stopped. Slides in over `ENTER_S` (0.28 s), stays `SHOW_S` (10 s) or until a tap, then leaves with the stock scroll to home. Onroad again removes it at once; onroad within 3 s continues the same trip. Not due: exactly stock.

## Park-offroad (Tesla; another brand needs one decoder)

| Piece | Where |
| --- | --- |
| State machine, decoders, `parkd` | `selfdrive/car/park_offroad.py`. A brand adds a `ParkSource` to `PARK_SOURCES`; parkd idles without one. |
| Onroad condition | hardwared: `onroad_conditions["not_parked"] = park_offroad.not_parked(params)`. No-op unless `ParkOffroad` is on and parkd holds `ParkOffroadActive`. |
| Shutdown timing | hardwared: `off_ts = park_timer.update(...)` restarts the timer at ignition off. |
| Process | `RestartingPythonProcess("parkd", ..., park_offroad.should_run)`, onroad and offroad while the toggle is on. |
| Params | `ParkOffroad {PERSISTENT, BOOL, "0"}`, `ParkOffroadActive {CLEAR_ON_MANAGER_START, BOOL}`. No CLEAR_ON_IGNITION_ON: an ignitionCan blip would drop the latch. |
| Toggles | Both `toggles.py`, warning confirm; also sets `DriveSummary`. |
| Card at Park, fast return, brightness | `selfdrive/ui/lib/park_card.py`: `early_event` puts the card up on the first Park frame. `ParkReturn` skips `ONROAD_DELAY` and jumps brightness to the camera on R/D, and holds brightness while the card is up parked offroad. |
| Tests | `selfdrive/car/tests/test_park_offroad.py`, `selfdrive/ui/tests/test_park_card.py`. |

It only ever removes an onroad condition and sends nothing on CAN. Panda safety is unchanged.
