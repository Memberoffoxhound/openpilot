# Porting TeslaPilot additions to other forks

## Drive summary card + engaged-streak icon (any car, any fork)

Self-contained: no Tesla, TeslaPilot or Jetlink code, no gear detection, no new assets (everything is drawn in code).

### Files (copy as is)
| File | What |
| --- | --- |
| `openpilot/selfdrive/ui/lib/drive_summary.py` | Recorder, timeline buckets, persistence, show rules, formatting. Imports nothing from openpilot except swaglog, plus the two optional swap-ins below. |
| `openpilot/selfdrive/ui/mici/widgets/drive_summary_card.py` | The home card: opaque, alert-style, 536x240. |
| `openpilot/selfdrive/ui/mici/widgets/card_slide.py` | Card motion (pure, steppable). Needs `openpilot.common.filter_simple.BounceFilter` (stock). |
| `openpilot/selfdrive/ui/mici/widgets/trip_row.py` | The Today/Week row (home) and block (card). |
| `openpilot/selfdrive/ui/mici/onroad/streak_icon.py` | The 50 px STREAK circle, bottom-right of the camera view. |
| `openpilot/selfdrive/ui/tests/test_drive_summary.py` | Tests. Pure Python, no raylib. |

### Params (one place: `common/params_keys.h`)
```
{"DriveSummary", {PERSISTENT, BOOL, "0"}},
{"DriveSummaryLast", {PERSISTENT, JSON}},
```
The keys are read tolerantly: with an older params library, the feature is just off. This fork sets `DriveSummary` from the "Go Offroad in Park" toggle. Elsewhere, add a `BigParamControl("drive summary", "DriveSummary")` toggle, or set the param.

### Hooks (4 lines of call sites, plus imports)
1. Stats at drive end: in the mici main layout's `_update_state`, call `drive_summary.tick(ui_state)` once per frame.
   - It records while `ui_state.started` and saves the summary when offroad lasts 3 s. Shorter onroad cycles count as the same drive.
   - It works with any offroad cause: ignition off, park-offroad, onroad cycle, always-offroad.
2. Render hook: in the mici home layout, add the card to `__init__` and draw it at the end of `_render`:
   - `__init__`: `self._drive_summary = DriveSummaryCard(stats_fn=None)`
   - end of `_render`: `self._drive_summary.render(self.rect)`
   - `stats_fn` is optional: a callable returning `today_m/today_e/week_m/week_e/streak_days`. TeslaPilot passes its home `stats_view`. Without it, the card uses the 14 days of totals it keeps itself.
3. Tap: at the top of the home `_handle_mouse_release`, add `if self._drive_summary.dismiss_on_tap(): return`.
4. Streak icon: in `AugmentedRoadView`, construct a `StreakIcon()` and call `self._streak_icon.render(self._content_rect)` right after the HUD render, inside the scissor. The content rect excludes the confidence-ball side panel.

### Swap-ins (in `drive_summary.py`, try/except imports, nothing to do on a fork without them)
- **`accent_rgb()`, theme color:** used by the card's check badge and the streak ring. It returns the fork's theme color from `openpilot.selfdrive.ui.layouts.settings.common.theme_rgb()`, which here is TeslaPilot's theme (Tesla blue or openpilot green). If that import fails (no theme manager), it returns **comma green** `#178645`, connect's engagedGreen, the same as the timeline's engaged color. To use another fork's theme manager, change this one function.
- **`fork_record_m()`, streak record:** the lifetime longest engaged stretch, in meters. Here it is `trip_stats.load_stats()["max_streak_m"]`. Without it the value is 0, and the record `drive_summary` keeps itself (`DriveSummaryLast.record_m`, the max best stretch of saved drives) is used.

### Behavior
- The card shows once per drive (the `shown` flag lives in the param, so screen sleep or a UI restart can't repeat it).
  - Only within 10 min of the drive's end.
  - Only for drives of at least 0.1 mi and 30 s.
  - Slides in from the top with the onroad alerts' bounce (`BounceFilter`, rc 0.1; `widgets/card_slide.py`).
  - After `SHOW_S` (10 s; one constant in `drive_summary.py`) or a tap, it slides back up to reveal the home screen. There's no on-screen timer.
  - Going back onroad removes it at once.
- The card headline is "trip complete", with the theme check badge to its right.
  - Stat columns are evenly spaced, each value centered over its label.
  - Best stretch drops if the four columns don't fit.
- Streak icon:
  - The number is the current engaged stretch in the user's unit: one decimal under 10 (floored), whole numbers from 10.
  - The ring shows progress toward the streak record, filled in the accent color, and is full once the record is reached or beaten.
  - With no record yet (under 1 m), only the neutral track shows, never a misleading full ring.
  - On disengage, everything is grey for 3 s, then it fades.
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
