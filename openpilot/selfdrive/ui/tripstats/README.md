# tripstats

Trip stats keeps a record of your driving on the comma itself. It works on any car. Nothing is uploaded and nothing extra runs in the background.

## What you see

- **Trip summary card.** When a drive ends, a card shows the distance, how much of it openpilot drove, your day streak, your best engaged stretch and a timeline of the drive. It stays up for 20 seconds or until you tap it. You can swipe back to it until your next drive.
- **Day and Week on Home.** Home shows today's and this week's distance and percent engaged. Tap the row to open Statistics.
- **Statistics.** Weekly and monthly charts, lifetime totals and your best streak.
- **Last trip summary.** Some cars cut power to the comma the moment the car turns off, before the card can show. The next time the comma starts, the same card comes up once with the headline "last trip summary".

Turn it on with the "drive summary" toggle.

## How a drive becomes a stat

1. A drive starts when openpilot goes onroad.
2. While you drive, the recorder adds up the distance, the distance openpilot was engaged, the longest engaged stretch, and a timeline.
3. Every 30 seconds it saves the drive so far. If the power is cut, you lose at most 30 seconds of driving.
4. The drive ends 3 seconds after openpilot goes offroad. The short wait stops a quick on-off blip from splitting one drive into two.
5. The drive is added to its day, and the card comes up if the car has stopped and the trip was at least 0.1 mi and 30 seconds long.

Everything is kept in one place, the `DriveSummaryLast` param. It holds 400 days of daily totals, plus the lifetime totals, best stretch, best streak and last trip, which never expire. Home, the card, Statistics and Highland's web page all read the same numbers from it, so they always agree.

If the comma lost power during a drive, the next start finishes that drive at its last save, on the day it happened.

### The timeline colors

The card's timeline uses the same colors as comma connect: blue when openpilot is not engaged, green when engaged, grey while you override, orange for an alert that asks you to do something, red for a critical alert and yellow for a bookmark.

## How "today" is decided

Day resets at midnight and Week resets on Sunday, in the local time where you are. The comma works out that time zone from GPS:

1. GPS saves the car's last position about once a minute (`LastGPSPosition`).
2. A small built-in map of the world's time zones, `tzgrid.bin`, turns that position into a zone name such as `America/Chicago`. It works offline.
3. The result goes into the `Timezone` param. It is checked 10 seconds after the screen starts and every 5 minutes after that.
4. Until the comma has a GPS fix, it uses its own clock's time zone instead.

There is no way to set the zone by hand. Within about 5 km of a time zone border, the map can pick the zone next door.

A few rules keep the days right:

- **A drive is dated when it ends.** A drive past midnight counts on the day it ends.
- **Old drives never move.** Each drive is saved with the time it ended and the time zone offset at that moment. If you drive into a new zone, only new drives and "today" follow it.
- **A wrong clock waits.** A comma can start up with an old clock until GPS or the internet corrects it. A drive that ends before then waits and is counted once the clock is right. It is never filed on the wrong day.
- **Daylight saving** just changes the offset. A 23 or 25 hour day keeps its date.

## Why Tesla needs Park logic

On most cars, turning off the ignition takes openpilot offroad, which ends the drive and brings up the card.

A Tesla has no ignition switch. The car stays awake in Park, so openpilot would stay onroad and the drive would never end.

The "go offroad in park" toggle (`ParkOffroad`) fixes that. A small process, parkd (`selfdrive/car/park_offroad.py`), reads the gear from the car. Once the car has been in Park for 3 seconds and openpilot is not engaged, the comma goes offroad the normal way and the drive ends. The card comes up as soon as you shift into Park. Shifting to R or D starts a new drive. Park-offroad only reads the gear. It sends nothing to the car and does not change panda safety.

Other cars that stay awake without a normal ignition may need their own version of this. We don't know which cars those are. A car can be added with a `ParkSource` in `park_offroad.py`, and nothing in tripstats has to change. Contributions are welcome.

## Files

| File | What it does |
| --- | --- |
| `recorder.py` | Follows one drive: distance, engaged distance, best stretch, timeline. |
| `store.py` | Saves drives and works out every number shown: Day, Week, months, lifetime, streaks. |
| `card.py` | What the card shows and when. |
| `tz.py` | The time zone: looks up the GPS position in `tzgrid.bin`, else the system zone. |
| `tzgrid.bin` | The time zone map, 190 KB, built by `build_tzgrid.py`. |
| `__init__.py` | What the UI calls: `tick`, `view`, `due_summary`, `missed_trip`, `mark_shown`, `enabled`, `set_enabled`. |
| `tests/` | `pytest selfdrive/ui/tripstats`. No build needed. |

The time zone map is built from [timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder) data, © OpenStreetMap contributors, under the [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Keep this credit if you ship the file.

## Porting

`PORTING.md` in the `Highland` branch of [Memberoffoxhound/openpilot](https://github.com/Memberoffoxhound/openpilot) has the one-line command and the hooks. In short, a fork needs:

Params in `common/params_keys.h`:
```
{"DriveSummary", {PERSISTENT, BOOL, "0"}},
{"DriveSummaryLast", {PERSISTENT, JSON}},
{"Timezone", {PERSISTENT, STRING}},
```

Hooks:
1. Every UI frame: `tripstats.tick(ui_state)`.
2. Numbers: `tripstats.view(ui_state.params)`. Another process, such as a web page, can use `store.view(d, d["open"], tz=tz.zone(p))` with `d = store.load(p)`.
3. The card: `begin()` when the trip ends, `begin(last=True)` once after the first frame for "last trip summary", and `clear()` on the next drive.
4. The toggle: `tripstats.set_enabled(params, on)`.

The module only needs the Python standard library, `common/params_compat.py`, `common/time_helpers.py`, `common/swaglog.py`, and cereal to read the GPS position.

## Details

These are for anyone changing the code.

**The store.**
```
DriveSummaryLast = {"v": 2, "days": {"2026-10-29": [m, e], ...}, "life": [m, e], "record_m": m,
                    "streak_max": n, "last": drive, "open": [drive, ...]}
```
`m` is meters driven and `e` meters engaged. Each stored drive has `end` (UTC seconds), `off` (the zone's UTC offset then), `ok` (the clock was valid) and `shown` (its card came up). `open` holds drives not counted yet: the one in progress, or one that ended on a wrong clock. A missing or unreadable store starts fresh, and a single bad entry is dropped on its own.

**Streaks.** A day counts with more than 1 m engaged. `view()` returns `streak_now`, the current run, and `streak_days`, the best run ever. The card and Statistics show the best run.

**Timeline layering.** As in connect (`src/actions/cached.js`, parseEvents), engaged, alert and override are separate events, and the one that started last is drawn on top. A bookmark is 1 second wide and drawn above everything. Stored drives keep one letter per bucket (`recorder.CODES`). The old "s" (stopped) draws blue, since connect has no stopped color.

**The time zone map.** One zone per 0.05 degree cell (about 5.5 km), compressed to 190 KB. A lookup takes about 10 ms on a PC. Checked against the full zone shapes on random land points, 0.23 to 0.29% get a different UTC offset, all within one cell of a border.

| Map | Size | Wrong offset on land |
| --- | --- | --- |
| grid 0.5 deg | 19 KB | 1.9% |
| grid 0.1 deg | 90 KB | 0.45% |
| **grid 0.05 deg (used)** | **186 KB** | **0.23 to 0.29%** |
| grid 0.02 deg | 497 KB | 0.10% |
| tzfpy (simplified shapes) | 4.99 MB | ~0 |
| timezonefinder (full shapes) | 33.8 MB + numpy | 0 |

**Last trip summary timing.** The card comes up 1 second after the first frame, so start-up isn't slower. Measured on a PC: recovery adds 0.65 ms before the first frame. The headline is 54 px instead of 62 px so it clears the badge.
