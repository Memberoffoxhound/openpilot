# Porting TeslaPilot additions to other forks

## Drive summary card (any car, any fork)

No Tesla, TeslaPilot or Jetlink code, no gear detection, no assets.

**Copy:** `selfdrive/ui/tripstats/` (recorder, store, card formatting, hook, tests, README), `common/params_compat.py`, `selfdrive/ui/mici/widgets/{drive_summary_card,trip_row}.py`, `selfdrive/ui/tests/test_drive_summary.py`. Optional: `mici/layouts/settings/stats.py` (Statistics) and the Day / Week row in `mici/layouts/home.py`.

**Params** (`common/params_keys.h`; read and written through `common/params_compat.py`, so an older params library without these keys falls back to the raw params files instead of raising):
```
{"DriveSummary", {PERSISTENT, BOOL, "0"}},
{"DriveSummaryLast", {PERSISTENT, JSON}},
{"Timezone", {PERSISTENT, STRING}},          // GPS zone (tripstats.tz); optional: without it, the system zone
{"TimezoneOverride", {PERSISTENT, STRING}},  // optional: set from the web GUI
```
Here the "Go Offroad in Park" toggle sets `DriveSummary`; elsewhere add a `BigParamControl("drive summary", "DriveSummary")`.

**Hooks:**
1. mici main `__init__`: `self._summary = DriveSummaryCard()`, passed as `AugmentedRoadView(..., summary=self._summary)`.
2. main `_update_state`: `tripstats.tick(ui_state)`. Numbers for Home / Statistics: `tripstats.view(ui_state.params)`.
3. main `_handle_transitions`:
   ```python
   if ui_state.ignition and (ui_state.started or not self._summary.last):
     self._summary.clear()                        # without park-offroad: next drive
   ...
   if self._last_trip_at is not None and rl.get_time() >= self._last_trip_at:   # set in _render's first frame + 1 s
     self._last_trip_at = None
     if not ui_state.started and self._summary.drive is None and self._summary.begin(last=True):
       self._scroll_to(self._onroad_layout)       # last trip summary: a power cut at ignition off hid its card
   ...
   else:                                          # offroad edge
     if self._summary.drive is None and not self._summary.begin():
       self._scroll_to(self._home_layout)         # stock
   if self._summary.update(abs(self._onroad_layout.rect.x - self._rect.x) < 1):
     self._scroll_to(self._home_layout)
   ```
4. `AugmentedRoadView._render`, offroad branch: `if not (self._summary and self._summary.render(self._rect)):` before the stock label.

**Theme:** `tripstats.card.accent_rgb()` tries `layouts.settings.common.theme_rgb()`, else comma green.

**Behavior:** at the offroad edge, if the trip is >= 0.1 mi and 30 s and the car stopped, the card is the onroad page's content: slides in over `ENTER_S` (0.28 s), holds the page `SHOW_S` (20 s) or until a tap or swipe, then the stock scroll to home. Swiping back from home shows it again until the next drive. Not due: stock. If the device lost power before the card came up, it comes up once at the next start as "last trip summary" (headline shrunk to 54 px to clear the badge; "trip summary" stays 62).

## Park-offroad (Tesla; another brand needs one decoder)

parkd publishes one param, `ParkOffroadState` (0 none, 1 parking, 2 parked). A param, not a cereal message: no schema change for downstream forks, hardwared already reads params, and it outlives a parkd restart.

| Piece | Where |
| --- | --- |
| State machine, decoders, `parkd` | `selfdrive/car/park_offroad.py`, with `common/params_compat.py`. A brand adds a `ParkSource` to `PARK_SOURCES`; parkd publishes 0 and idles without one. |
| Onroad condition | hardwared: `onroad_conditions["not_parked"] = park_offroad.not_parked(params)`; only state 2 with `ParkOffroad` on. |
| Shutdown timing | hardwared: `off_ts = park_timer.update(...)` restarts the timer at ignition off. |
| Process | `RestartingPythonProcess("parkd", ..., park_offroad.should_run)` while the toggle is on. |
| Params | `ParkOffroad {PERSISTENT, BOOL, "0"}`, `ParkOffroadState {CLEAR_ON_MANAGER_START, INT, "0"}`. No CLEAR_ON_IGNITION_ON: an ignitionCan blip would drop the latch. |
| UI | `selfdrive/ui/lib/park_view.py`: `ui_state.park.parked` from the first Park sample until onroad or ignition off. Card up at Park, the onroad page says "shift to D or R" instead of "can't start", brightness held for `SHOW_S`; `returned` skips `ONROAD_DELAY` and the brightness ramp. Extra main hook: `elif ui_state.park.parked and not self._prev_parked: self._summary.begin()`, and clear only `if ui_state.ignition and not parked`. |
| Toggles | Both `toggles.py`, warning confirm; also sets `DriveSummary`. |
| Tests | `selfdrive/car/tests/test_park_offroad.py`, `selfdrive/ui/tests/test_park_view.py`. |

It only ever removes an onroad condition and sends nothing on CAN. Panda safety is unchanged.
