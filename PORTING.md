# Porting TeslaPilot additions to other forks

## Drive summary card (any car, any fork)

Self-contained: no Tesla, TeslaPilot or Jetlink code, no gear detection, no new assets (everything is drawn in code).

### Files (copy as is)
| File | What |
| --- | --- |
| `openpilot/selfdrive/ui/lib/drive_summary.py` | Recorder, timeline buckets, persistence, show rules, formatting. Imports nothing from openpilot except swaglog, plus the optional swap-in below. |
| `openpilot/selfdrive/ui/mici/widgets/drive_summary_card.py` | The home card: opaque, alert-style, 536x240. |
| `openpilot/selfdrive/ui/mici/widgets/card_slide.py` | Card motion (pure, steppable, no imports). |
| `openpilot/selfdrive/ui/mici/widgets/trip_row.py` | The Today/Week row (home) and block (card). |
| `openpilot/selfdrive/ui/tests/test_drive_summary.py` | Tests. Pure Python, no raylib. |

### Params (one place: `common/params_keys.h`)
```
{"DriveSummary", {PERSISTENT, BOOL, "0"}},
{"DriveSummaryLast", {PERSISTENT, JSON}},
```
The keys are read tolerantly: with an older params library, the feature is just off. This fork sets `DriveSummary` from the "Go Offroad in Park" toggle. Elsewhere, add a `BigParamControl("drive summary", "DriveSummary")` toggle, or set the param.

### Hooks (all in the mici main layout, plus imports)
1. Stats at drive end: in `_update_state`, call `drive_summary.tick(ui_state)` once per frame.
   - It records while `ui_state.started` and saves the summary when offroad lasts 3 s. Shorter onroad cycles count as the same drive.
   - It works with any offroad cause: ignition off, park-offroad, onroad cycle, always-offroad.
2. Card: in `__init__`, add `self._drive_summary = DriveSummaryCard(stats_fn=None)`. At the end of `_render`, after `super()._render(...)`, add `self._drive_summary.render(self._rect, self._onroad_layout.rect.x)`: an overlay above the scroller that rides the onroad page once dismissed.
   - `stats_fn` is optional: a callable returning `today_m/today_e/week_m/week_e/streak_days`. TeslaPilot passes its `stats_view`. Without it, the card uses the 14 days of totals it keeps itself.
3. The hop, in `_handle_transitions`. The trip card shows first, then stock's scroll to home:
   ```python
   if ui_state.started:
     self._drive_summary.cancel()                 # onroad wins, nothing pending
     self._onroad_time_delay = rl.get_time()      # stock
   elif not self._drive_summary.hold_home():      # card due: hold the scroll
     self._scroll_to(self._home_layout)           # stock

   if self._drive_summary.release_home():         # card dismissed: stock scroll now
     self._scroll_to(self._home_layout)
   ```
   - Not due (toggle off, short trip, still moving): exactly stock.
   - The offroad branch never pops the nav stack (stock).
4. Tap: add `_handle_mouse_release` with `if self._drive_summary.dismiss_on_tap(): return` before `super()`.
   - Also add `and not self._drive_summary.visible` to the scroller's `set_scrolling_enabled`, so nothing swipes under the card.

### Swap-in (in `drive_summary.py`, try/except import, nothing to do on a fork without them)
- **`accent_rgb()`, theme color:** used by the card's check badge. It returns the fork's theme color from `openpilot.selfdrive.ui.layouts.settings.common.theme_rgb()`, which here is TeslaPilot's theme (Tesla blue or openpilot green). If that import fails (no theme manager), it returns **comma green** `#178645`, connect's engagedGreen, the same as the timeline's engaged color. To use another fork's theme manager, change this one function.

### Behavior
- The card hops in at the onroad -> offroad edge, over the onroad page, before home. Only when it's due:
  - `DriveSummary` is on.
  - The trip was recorded and is at least 0.1 mi and 30 s long.
  - The car is stopped on the last onroad frame. An onroad cycle while moving stays stock.
- Motion and timing:
  - Slides in from the top with a smooth ease-out in `ENTER_S` (0.28 s), with no bounce or overshoot (`widgets/card_slide.py`).
  - After `SHOW_S` (10 s; one constant in `drive_summary.py`) or a tap, the stock scroll to home runs.
    - The card has no exit animation of its own: it rides the onroad page's scroller position (`attached_dx`), so it slides sideways exactly like home coming in today.
    - It stops drawing once home is in place, with a 2 s failsafe if no scroll happens.
    - There's no on-screen timer.
  - Going back onroad removes it at once and cancels the hand-off.
  - If onroad resumes within the 3 s merge window, the trip goes on and the card comes back at the real end.
- The card headline is "trip complete", with the theme check badge to its right.
  - Stat columns are evenly spaced, each value centered over its label.
  - Best stretch drops if the four columns don't fit.
- The timeline is 160 constant-memory time buckets, using comma connect's palette:
  - green #178645 engaged
  - blue #175886 manual
  - yellow #e3d756 override/gas
  - orange #da6f25 userPrompt
  - red #c92231 critical
  - grey #919b95 stopped and disengaged
- Engagement % is distance-based (engaged meters / meters).

## Park-offroad (Tesla; another brand needs one decoder)

| Piece | Where |
| --- | --- |
| State machine, decoders, hooks, `parkd` main | `openpilot/selfdrive/car/park_offroad.py` |
| Swap-in detection | `PARK_SOURCES = {"tesla": ParkSource(addrs, sample)}`. A brand adds `(frames) -> (gear, autopark)`. parkd idles for brands without a source (brand from `CarParamsPersistent`). |
| Onroad condition | hardwared: `onroad_conditions["not_parked"] = park_offroad.not_parked(params)`. This is a no-op unless `ParkOffroad` is on and parkd holds `ParkOffroadActive`. Offroad then goes through the normal transition: route end, NO_OUTPUT with the relay open, uploads. |
| Shutdown timing | hardwared: `off_ts = park_timer.update(...)`. After a park-offroad, the shutdown timer restarts at ignition off. |
| Process | `RestartingPythonProcess("parkd", ..., park_offroad.should_run)`. It runs onroad and offroad while the toggle is on. |
| Params | `ParkOffroad {PERSISTENT, BOOL, "0"}`, `ParkOffroadActive {CLEAR_ON_MANAGER_START, BOOL}`. Do not add CLEAR_ON_IGNITION_ON: manager's ignition-on clear would drop the latch on an ignitionCan blip. |
| Toggles | Both `toggles.py` files, with a warning confirm. They also set `DriveSummary`. |
| Tests | `openpilot/selfdrive/car/tests/test_park_offroad.py`. CAN fixtures, plus a parkd main-loop smoke test with simulated hardwared/manager routes. |

It only ever removes an onroad condition and sends nothing on CAN. Panda safety is unchanged.
