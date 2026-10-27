# Porting: trip summary card

Any car with an ignition switch, any fork. No car-specific code, no new process, no assets.

**Copy:** `selfdrive/ui/lib/drive_summary.py`, `selfdrive/ui/mici/widgets/{drive_summary_card,trip_row}.py`,
`selfdrive/ui/tests/{test_drive_summary,test_summary_card}.py`.

**Param** (`common/params_keys.h`; without it the history falls back to a raw file in the params dir):
```
{"DriveSummaryLast", {PERSISTENT, JSON}},
```
Always on: no toggle.

**Hooks** (mici only):
1. `main.__init__`: `self._summary = DriveSummaryCard(stats_fn=...)`, passed as `AugmentedRoadView(..., summary=self._summary)`.
   `stats_fn` is optional (`today_m/today_e/week_m/week_e/streak_days`); without it the card uses its own totals.
2. `main._update_state`: `drive_summary.tick(ui_state)`.
3. `main._handle_transitions`:
   ```python
   if ui_state.ignition:
     self._summary.clear()                                   # next drive
   ...
   elif ui_state.ignition or not self._summary.begin():      # offroad edge; card only at key off
     self._scroll_to(self._home_layout)                      # stock
   if self._summary.update(abs(self._onroad_layout.rect.x - self._rect.x) < 1):
     self._scroll_to(self._home_layout)
   ```
4. `AugmentedRoadView._render`, offroad branch: `if not (self._summary and self._summary.render(self._rect)):` before the stock label.

**Behavior:** at key off, if the trip was >= 0.1 mi and 30 s and the car stopped, the card slides in (0.28 s) as the
onroad page's content, holds `SHOW_S` (20 s) or until a tap or swipe, then the stock scroll to home. Swipe back from
home to see it again until the next key on. Short trip or offroad with the key on: stock.

**Theme:** `drive_summary.accent_rgb()` uses `layouts.settings.common.theme_rgb()` if present, else comma green.
