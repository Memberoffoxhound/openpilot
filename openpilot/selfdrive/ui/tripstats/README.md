# tripstats

Trip stats for any car: the drive summary card, Home's `Day` / `Week` row and the Statistics pages.
One recorder in the UI process, one store (the `DriveSummaryLast` param). No qlog scans, no files
under `/data`, no background jobs, no locks.

| File | What |
| --- | --- |
| `recorder.py` | `DriveRecorder`: one drive, frame by frame: meters, engaged meters, best stretch, status timeline. Pure. |
| `store.py` | The store and every number shown from it: `load`, `save`, `add_drive`, `view`, `streaks`. Pure except `load` / `save`. |
| `card.py` | Card formatting: show rule, stat columns, timeline runs, accent color. Pure. |
| `tz.py` | The device zone: offline GPS lookup (`zone_at`), the `Timezone` / `TimezoneOverride` params. |
| `tzgrid.bin` | The lookup table, 190 KB (built by `build_tzgrid.py`, a dev tool, from timezone-boundary-builder via `timezonefinder`). Data © OpenStreetMap contributors, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/); source: [evansiroky/timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder). |
| `__init__.py` | The UI hook: `tick`, `view`, `due_summary`, `missed_trip`, `mark_shown`, `enabled`, `set_enabled`. |
| `tests/` | `pytest selfdrive/ui/tripstats`. No raylib, no build. |

Imports: the standard library (`zoneinfo`, `zlib`), `common/params_compat.py`, `common/time_helpers.py`,
`common/swaglog.py`, and `cereal` (lazily, in `tz.py`, to read the GPS fix).
`card.accent_rgb()` tries the fork's `layouts.settings.common.theme_rgb()` and falls back to comma green.

## Store

```
DriveSummaryLast = {"v": 2, "days": {"2026-10-29": [m, e], ...}, "life": [m, e], "record_m": m,
                    "streak_max": n, "last": drive, "open": [drive, ...]}
```

- `m` is meters driven, `e` meters engaged.
- `days` keeps 400 days. `life` (Total / Engaged), `record_m` (best stretch) and `streak_max` outlive that.
- Every stored drive is stamped: `end` (UTC seconds), `off` (the zone's UTC offset then, seconds), `ok`
  (the clock was valid), and `shown` (its card came up).
- `open` holds drives not counted in `days` yet: the one in progress (saved, and stamped, every 30 s, so
  a UI restart or a power cut loses at most 30 s and the web GUI sees it), or one that ended on a stale clock.
- A missing, older-version or unreadable param starts a fresh store. A single bad entry is dropped on its own.

Everything shown comes from `store.view()`: Day, Week, the week's seven days, six months, lifetime,
engaged %, streaks and the best stretch. The UI's `tripstats.view(params)` adds the drive in progress,
so Home and the card count it before it is stored, and the numbers don't change when it is stored.

## Days, weeks, streaks

- **Local day.** A drive counts on the local date of its stamp, `end + off`. A zone change (a trip
  abroad, a corrected zone) never moves stored drives; only new ones and "today" follow the new zone.
  DST is just another offset (23 and 25 h days keep their date).
- **The zone** (`tz.py`, read every 10 s): `TimezoneOverride` if set (the web GUI's "Use this phone's
  time zone", from the browser's `Intl` zone), else `Timezone` (from GPS), else the system zone
  (`TZ` / `/etc/localtime`). A name this device's tzdata doesn't know is skipped. Nothing is hard-coded.
- **GPS zone.** 10 s after the UI's first tick, then every 5 min, a daemon thread reads `LastGPSPosition`
  (ubloxd saves it once a minute with a fix), looks the point up in `tzgrid.bin` and writes `Timezone` if
  it changed. Fully offline: no network, nothing at boot, nothing on the UI thread.
- **The table.** One zone per 0.05 degree cell (about 5.5 km), run-length coded, zlib: 190 KB, about 10 ms
  per lookup on a PC (650 KB unpacked, freed after). Against the full polygons on random land points:
  0.48% get a different zone name and 0.23 to 0.29% a different UTC offset (108k and 50k points), all
  within a cell of a zone border. Options measured:

  | Table | Size | Wrong offset on land |
  | --- | --- | --- |
  | grid 0.5 deg | 19 KB | 1.9% |
  | grid 0.1 deg | 90 KB | 0.45% |
  | **grid 0.05 deg (used)** | **186 KB** | **0.23 to 0.29%** |
  | grid 0.02 deg | 497 KB | 0.10% |
  | tzfpy (simplified polygons, Rust .so) | 4.99 MB | ~0 |
  | timezonefinder data (full polygons) | 33.8 MB + numpy | 0 |

  Near a border, the web GUI override fixes it.
- **A drive is dated when it ends.** By then the clock has normally synced. A drive over midnight counts
  on the day it ends.
- **Stale clock.** A device can boot with a months-old clock until GPS or NTP sets it. If
  `system_time_valid()` is false when a drive ends, it stays in `open` and is counted on the first
  frame with a valid clock, on that day. A drive is never stored on a wrong day.
- **Power cut.** A drive left in `open` by the last run (power cut, UI crash) closes at its last stamp
  on the next start, on that stamp's local day, even before this boot's clock is valid. One stamped
  on a stale clock waits for a valid clock, as above.
- **Week** runs Sunday to Saturday.
- **Streak.** A day counts with more than 1 m engaged. `view()` returns `streak_now`, the current run
  ending today, or yesterday until today counts, and `streak_days`, the best run ever. The card's
  "day streak" and Statistics' "N Day Streak" show `streak_days`, as before this rewrite.

## How a drive ends: ignition, or Park on a Tesla

The recorder is brand-free. A drive runs while `ui_state.started`. It ends once `started` has been false
for `MERGE_S` (3 s), so a ~1 s onroad cycle doesn't split it. Then it is stored. The card is due while
the drive is still open, stopped, at least 0.1 mi and 30 s, with `DriveSummary` on.

**Standard ignition (every other car).** Ignition off drops `started` (hardwared's `ignition`
condition). The card comes up at that offroad edge.

**Tesla (Park).** A Tesla has no ignition switch. `ignitionCan` stays on in Park while the car is
awake, so `started` doesn't drop when the driver parks. With the `ParkOffroad` toggle,
parkd (`selfdrive/car/park_offroad.py`) reads `DI_gear` from the car's CAN and publishes
`ParkOffroadState`. After Park is held 3 s and the car is not engaged, hardwared's `not_parked` condition takes the
device offroad the normal way, and the drive ends like any other. Only R or D comes back onroad, as a new
drive. The UI's `ParkView` (`selfdrive/ui/lib/park_view.py`) puts the card up at the first Park sample,
while the device is still onroad. Park-offroad only removes an onroad condition. It sends nothing, and
panda safety is unchanged.

**Other cars without a normal ignition.** Some cars (other EVs, push-button cars that stay awake) may need their own
version, a decoder that turns gear or power state into an offroad condition. We don't know which cars these are. A
brand adds a `ParkSource` to `PARK_SOURCES` in `park_offroad.py`; nothing in tripstats changes.
Contributions are welcome.

**Devices that lose power at ignition off.** The drive's last save survives (power cut, above), but
the card never came up. At the next start, 1 s after the UI's first frame, if offroad, `DriveSummary`
is on and that trip is long enough, the same card comes up once with the headline "last trip summary"
(shrunk from 62 to 54 px so it clears the badge), with Day
and Week as of that trip. It holds while the car starts (ignition on, not yet onroad) and goes
when onroad. `shown` in the store makes it once: the normal card sets it (stored at once), and so does
this one. The Tesla Park path always shows its card before power-down, so it never gets here.
Measured (PC, xvfb, 14 runs each): UI start to first frame 0.72 s median without and 0.74 s with a
trip to recover (min 0.66 s both, the spread is noise); recovery adds 0.65 ms before the first frame,
and the card's `begin` (1.1 ms) runs 1.0 s after it.

## Integration

Params (`common/params_keys.h`):
```
{"DriveSummary", {PERSISTENT, BOOL, "0"}},
{"DriveSummaryLast", {PERSISTENT, JSON}},
{"Timezone", {PERSISTENT, STRING}},
{"TimezoneOverride", {PERSISTENT, STRING}},
```

Hooks:
1. Every UI frame (mici `MiciMainLayout._update_state`): `tripstats.tick(ui_state)`.
2. Numbers: `tripstats.view(ui_state.params)` returns `today_m/e`, `week_m/e`, `week_days`, `months`,
   `life_m/e`, `pct`, `today_pct`, `week_pct`, `streak_days`, `streak_now` and `longest_m`. Another process
   (the web GUI) uses `store.view(d, d["open"], tz=tz.zone(p))` with `d = store.load(p)`.
3. Card (`mici/widgets/drive_summary_card.py`): `begin()` when the trip ends, `begin(last=True)` once
   after the first frame, `clear()` on the next drive. See `MiciMainLayout._handle_transitions` and `PORTING.md`.
4. Toggle: `tripstats.set_enabled(params, on)`.
5. Zone override: `tz.set_override(params, name)` (`""` clears); the web GUI's `POST /api/timezone {"tz": name}`.

Presentation files that use it: `mici/widgets/drive_summary_card.py`, `mici/widgets/trip_row.py`,
`mici/layouts/home.py`, `mici/layouts/settings/stats.py`, `system/webgui/stats.py`.
