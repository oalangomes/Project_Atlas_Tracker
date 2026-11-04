# Project Atlas Tracker 1.2.7

## v1.2.7 hotfix

- Serializes Atlas-internal SQLite writers so snapshot imports, MatchStats and media background work no longer race for the single SQLite writer slot.
- Career reset now holds the same writer guard for the complete reset/restore operation.
- A transient `database is locked` / `database is busy` during snapshot import is retried instead of moving a valid snapshot to `failed`.
- Snapshot packages that v1.2.5 moved to `failed` solely because of a SQLite lock are automatically returned to `ready` and retried.


## v1.2.5 large-career reset performance hotfix

- Replaces the reset entity-lifetime N+1 query loop with four bulk chronological state scans. On real careers with tens of thousands of players and many full snapshots, the old implementation could perform billions of row checks and appear stuck on `Resetting…`.
- The hard-reset safety model is unchanged: backup first, mutate a temporary copy, validate it, then write the validated copy back to the live database.
- v1.2.4 Windows temporary-file handle fix remains included.

# Project Atlas Tracker v1.2.5

## v1.2.5 Windows reset temp-file hotfix

- Fixes `WinError 32` when starting a career reset on Windows. `tempfile.mkstemp()` returns an open file handle; v1.2.3 attempted to delete that temporary SQLite path before closing the handle. v1.2.5 closes it immediately and lets SQLite populate the existing empty temp file.
- Temporary reset database cleanup is now best-effort so a short-lived Windows Defender/indexer handle cannot turn an otherwise successful reset into a false failure after the live database has already been replaced.
- The transactional safety model is unchanged: backup first, mutate a temporary database, validate it, then copy it over the live database.

## v1.2.3 snapshot reset hotfix

- Fixes hard reset for careers where an **older in-game snapshot was imported later in real time**. Entity first/last-seen pointers are now rebuilt from chronological snapshot state instead of trusting historical import order.
- Snapshot imports now keep entity lifetimes aligned whenever a newly imported folder causes the career history to be resequenced.
- Creates a SQLite backup before every reset, mutates and validates a temporary copy, and only then replaces the live career database.
- Keeps the selected full snapshot and all earlier snapshots, while removing later snapshot state, later MatchStats, transfer pulses and derived transfer state.
- Reset failures are now shown explicitly in the UI and recorded as `career_reset_failed` import events instead of silently returning to the normal button state.
- Removed raw export packages are moved to `Documents\FC26 Export\ResetArchive` by default; the optional permanent-delete switch deletes them instead.


## v1.2.1 AutoCapture / MatchStats hotfix

- Fixes a post-match AutoCapture deadlock where a newly completed fixture could remain pending forever if no second CareerModeEvent occurred at least four seconds later. A genuine increase in completed managed-team fixtures now triggers the paired snapshot immediately.
- MatchStats packages that Atlas has consumed are moved from `MatchStats\ready` to `MatchStats\imported`; malformed packages are moved to `MatchStats\failed` when possible.
- `scan_now_windows.bat` / `run.py --scan` now scans MatchStats as well as snapshots.
- Bundled AutoCapture is `FC26_AutoCapture_v1.1.1.lua`; standalone Snapshot and MatchStats exporters remain v1.1.0 because their capture format did not change.


## v1.2.0 tracking-focused release cleanup

- Removed the standalone **Finance** and **Sponsors & kit supplier** sections from the Tracker UI. Player/squad contract values and clearly labelled estimates used by normal tracking views remain available where relevant.
- Removed the unsupported `FC form x/10` presentation from Squad and Player Profile. The snapshot still preserves FC26's raw `teamplayerlinks.form` value, but Tracker no longer invents a 1–10 semantic scale for it.
- Transfer and loan source labels are now consistently English (`Derived`, `Observed`, `Imported`, `Manual`). Legacy German labels are translated defensively when older migrated data is displayed.
- Youth tracking now shows the directly imported **OVR** and **POT** values without a separate estimated-potential range.
- Season Report and Analysis received an English-language and spelling cleanup, including labels, award names, league positions and detailed-match coverage text.
- Media setup no longer exposes sponsor/supplier source types in this tracking-only edition.
- Snapshot and MatchStats hot-folder import remains automatic. With the default configuration Tracker watches `%USERPROFILE%\Documents\FC26 Export\Snapshots\ready` and the sibling `MatchStats\ready` folder while it is running.

The bundled LUA exporters remain at v1.1.0 because their export contract did not need to change for this UI release.

## v1.1.2 workspace discovery hotfix

- Migration now recursively scans the original `FC26CareerTracker` app-data root, including `workspaces\ws_*\atlas_core.sqlite3`.
- Custom legacy roots that contain a root Atlas database now also have their `workspaces` subtree scanned.
- Every discovered workspace database remains an explicit selectable migration candidate.


Project Atlas Tracker is a free, local, community-focused statistics companion for EA SPORTS FC 26 Manager Career on Windows. It imports read-only career snapshots and optional detailed match statistics produced by the included Live Editor LUA scripts.

This community edition is independent from the private Project Atlas version line. It does not perform transfers, contract renewals, negotiations, scouting actions, youth creation, or other writes to an FC26 career.

## Optional Technical Commission reports

The Tracker can use a local Ollama installation for evidence-based match, player, and team-style reports. Reports are tied to the selected career and source facts, saved locally, and reused while those facts remain unchanged. New completed matches are analyzed in the background when their data is available; historical match and player reports can also be generated from the Technical Commission page. Historical generation creates a database backup first. If Ollama is offline, Tracker continues to show its recorded statistics and the reports can be retried later.

The interface and generated reports support Brazilian Portuguese, British English, and Spanish. Ollama is optional; all career tracking and statistics pages work without it. FC26 career data remains local, and the included LUA exporters read game data without changing the save.



## v1.1.1 migration hotfix

- Private Atlas migration now discovers both `.sqlite` and `.sqlite3` databases, including per-career workspace files such as `workspaces\ws_*\atlas_core.sqlite`.
- Automatic discovery always shows the discovered career databases with career/team metadata, snapshot count, update timestamp and full path before anything is copied.
- A wrong previous migration can be safely replaced: the current Tracker database is backed up first, then the selected source is migrated into a clean target after explicit `REPLACE` confirmation.
- The migration never merges two career databases implicitly.

## v1.1.0 production exporter cleanup

- MatchStats exports now publish only the three canonical Tracker data CSVs plus compact progress/error/summary logs and the ready marker.
- Probe-era correlation tables, raw getter dumps, service/vtable dumps, rating matrices and binary memory windows are no longer written in production builds.
- The validated read-only build checks, direct player-ID resolution, xG/xA reads, MatchEventTracker joins, Man of the Match and game-rating reads remain active.
- Large post-export diagnostic memory captures are disabled, reducing export noise and unnecessary read overhead.
- AutoCapture embeds the same cleaned v1.1.0 Snapshot and MatchStats engines.

## v1.0.1 media and competition fixes

- Reconciles previously unresolved player portraits after snapshot identities become available; existing media folders do not need to be re-copied.
- Re-checks unresolved media on startup, after snapshot imports, and after media scans.
- Competition names now override contradictory runtime/static-ID heuristics, preventing neighbouring competitions from borrowing the wrong logo after FC26 title updates.
- League-format detection now also uses stable league names and participant league data, preventing domestic leagues such as the Bundesliga from falling back to knockout format when runtime IDs drift.

## Included

- Fixtures, results, tables and competition pages
- Deep Simulation competitions and Atlas World Simulation leagues
- Player, squad, club and career statistics
- Detailed per-match player and team statistics when exported
- Transfer and loan history from imported FC26 data
- Read-only FC26-confirmed youth-player overview
- Clearly labelled Tracker estimates for values FC26 does not expose reliably
- Local media library for player, club, competition, trophy, stadium and kit assets
- Isolated career workspaces for multiple saves

## Requirements

- Windows 10 or 11
- EA SPORTS FC 26 on PC
- FC 26 Live Editor with LUA support
- Python 3.11 or newer

No cloud service, API key or internet connection is required. Ollama is optional and runs locally when configured.

## Importing a career from the private Project Atlas build

Close both Atlas applications, then double-click `migrate_private_atlas.bat`.
The migration utility scans the private Atlas root and its workspace folders under
`%LOCALAPPDATA%` for `atlas_tracker.sqlite3`, `atlas_core.sqlite3`,
`atlas_tracker.sqlite`, and `atlas_core.sqlite`. Before copying anything it lists
every discovered database with readable career/team metadata, snapshot count,
update time, and full path. Select the source database that contains the career you
want to continue.

The source database is opened read-only and is never changed. If Tracker already
contains data from an earlier migration, the utility can replace that copy after an
explicit `REPLACE` confirmation; it creates a timestamped backup first. Sources are
never merged implicitly. An explicit source can also be supplied from a command
prompt:

```text
py -3 migrate_private_atlas.py --source "C:\path\to\atlas_tracker.sqlite3"
```

## Quick setup

1. Extract the complete release folder.
2. Start `start_windows.bat`.
3. Load a Manager Career in FC26 and open Live Editor.
4. Run one of the LUA scripts from the `exporter` folder.
5. Keep Tracker running. It scans the shared export folders automatically; **Scan now** is available only as an immediate manual trigger.

The scripts and Tracker use this shared location by default:

```text
%USERPROFILE%\Documents\FC26 Export
├── Snapshots
│   ├── incoming
│   ├── ready
│   ├── imported
│   └── failed
└── MatchStats
    ├── incoming
    ├── ready
    ├── imported
    └── failed
```

You normally do not need to configure an export path. Tracker performs a complete scan on startup and then polls the configured snapshot root every few seconds. MatchStats is discovered automatically from the sibling `MatchStats\ready` folder.

## LUA scripts

### `FC26_AutoCapture_v1.1.0.lua` — recommended

Run it once after loading a career. It creates a startup snapshot, monitors the next normally played match, and publishes a paired full snapshot plus detailed MatchStats package after each newly completed match. Leave the Live Editor LUA session running.

### `FC26_MatchStatsExport_v1.1.0.lua`

Use this when you only want detailed statistics for one match. Run it once in the Career Hub before a new normally played match, play the match, and return to the Career Hub. The completed package is written to `MatchStats\ready`.

### `FC26_Snapshot_v1.1.0.lua`

Use this when you only want a single full career snapshot. Load the career and run the script once. The completed package is written to `Snapshots\ready`.

All three scripts are read-only: they read FC26 career data and do not modify the game database or memory.

A normal v1.1.0 MatchStats package is intentionally compact:

```text
16_match_participants_wide.csv
18_match_teams_wide.csv
20_match_export_summary.csv
00_progress.log
98_errors.csv
99_summary.txt
MATCH_READY
```

The progress/error files are retained for troubleshooting but are not imported as match data.

## Multiple career saves

Create a separate Tracker career profile for every FC26 save. The first full snapshot detected for a new profile must be confirmed in **Setup**. Tracker stores each profile in an isolated local database while all active profiles use the same community LUA hot-folder. Only the currently active profile consumes new exports, and career-identity checks prevent snapshots from different saves from being mixed.

## Data and estimates

Snapshot data is stored locally under `%LOCALAPPDATA%\ProjectAtlasTracker`. Imported source packages are moved from `ready` to `imported`; invalid packages are moved to `failed` with an error record.

FC26 does not currently expose reliable market values and wages for every player through this export route. Values calculated by Tracker are explicitly marked as estimates and never written back to FC26.

## September 2026 FC26 update

Tracker resolves competitions by stable names and reference data when FC26 changes runtime object IDs. In the supplied post-update snapshot, Bundesliga object IDs `1016` and `1019` correctly map to league/media IDs `19` and `20`. They are shown as separate league competitions with the correct Bundesliga and 2. Bundesliga logos.

## Troubleshooting

- **No snapshot appears:** confirm that FC26 is in a loaded Manager Career, the LUA completed without an error, and a folder with a `READY` marker exists below `Documents\FC26 Export\Snapshots\ready`.
- **No detailed match data appears:** use AutoCapture or run MatchStatsExport before a new match, then return to the Career Hub after the final whistle.
- **Wrong career detected:** open **Setup**, select the intended career profile, restart Tracker, and confirm the pending first snapshot.
- **Port already in use:** close the other Tracker window/process and start again.
- **Optional media conversion is unavailable:** run `install_optional_dependencies.bat`.

## Community use

You may inspect and adapt this release and its LUA scripts for community stat-tracking work. If you redistribute a modified build, use a distinct name/version and document your changes so users can distinguish it from this release.
