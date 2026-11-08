# AutoCapture post-match stability hotfix (2026-11-06)

## Finding

The available evidence confirms an FC26 process access violation while Live Editor v26.3.5 was injected. It does not prove that a specific Lua call caused the native fault because the dump has no usable symbolized call stack.

- `FC26_MatchStats_pmc_20261106_082055_3db9f60d.partial/20_match_export_summary.csv` reports `complete_participant_export`, 26 participant rows, and trigger `late_match_candidate_event_137.0` at 08:46:22. Its `98_errors.csv` contains only the header.
- The progress log then records repeated `singleton_static_slot` and `singleton_plus_0xAF0` reads through 08:47:03.
- `auto_capture_monitor.csv` detects the completed fixture at 08:47:07. The AutoCapture `post__CareerModeEvent` callback synchronously invokes the full snapshot exporter; the Live Editor log shows it exporting 21,363 players and other career tables from 08:47:08 to 08:47:17. After snapshot success, the same callback immediately rearms MatchStats and performs another offset/memory validation.
- The FC26 minidump is timestamped 08:47:18 local and reports exception `0xC0000005` at `FCLiveEditor.DLL+0x52670C`. This is one second after the monitor reports snapshot completion, during the post-match callback's rearm path.
- The same sequence appears in prior incidents: on 2026-10-19 AutoCapture logged `matchstats_armed; reason=career_event_rearm` at 08:19:25 and an FC26 minidump reports `0xC0000005` at 08:19:26; on 2026-10-28 the monitor logged the same rearm at 17:55:47 and the FC26 minidump has the same exception at 17:55:47. These tight correlations make transition-time MatchStats rearming the leading likely trigger.
- Live Editor reports v26.3.5 and game build `1.0.139.20381`; AutoCapture logged successful core and optional offset validation. There is no evidence in these artifacts of a wrong build or failed offset check.

The strongest current hypothesis is that MatchStats offset validation/rearming occurs in the match-return callback while FC26 is changing career state; the repeated singleton polling and full snapshot callback add work in the same window. The repeated one-second rearm/crash correlations make this the leading likely cause, but the dump cannot distinguish which native API call faulted. It is not a symbolized root-cause proof.

The second package, `FC26_MatchStats_pmc_20261106_085443_eb275c69.partial`, is a new armed capture after restart: it has only startup validation and no final-match summary. Its partial state is expected until another match is captured; it is not evidence that the 08:46 export failed.

## Hotfix behavior

- MatchStats detaches its lifecycle handlers immediately after the final-candidate event 137 capture attempt. A complete package is published atomically then; an incomplete one stays marked incomplete. No repeated singleton reads continue through the hub transition.
- Embedded MatchStats signals the outer monitor at event 137. AutoCapture then suppresses the synchronous post-match full snapshot and automatic MatchStats rearm for the rest of that monitor session, without waiting for the fixture count to update at the hub. Save/confirm the career first; then re-run AutoCapture from the stable hub to start a new session and take a startup snapshot.
- The embedded and standalone snapshot exporters now request `teamlongform` with the same lowercase spelling used by the neighboring fields. The Live Editor log had reported `no field Teamlongform` once per league-team row.

## Validation boundary

The automated tests check source contracts for the hotfix branch only. They do not run Live Editor, exercise the native memory API, prove the AV cannot recur, or homologate post-match capture in FC26. Keep automatic capture paused until a saved-career real-environment validation is performed.

No running game or Live Editor instance, save, SQLite database, or `.partial` package was modified. The capture scripts were not executed.

## Follow-up: Live Editor event-handler API

The next Live Editor log showed a separate Lua API error at 09:35:33 local:
`Expected integer at argument 2 @ ... lua_RemoveEventHandler`. The v1.1.2 hotfix
called `RemoveEventHandler` with only a handler ID while replacing the prior
monitor. Live Editor v26.3.5 requires both the event name and handler ID, as
confirmed by its bundled `lua/libs/v2/tests/event_handlers_test.lua`.

The next capture at 10:46:22 local completed successfully, but the log showed
two more removal errors at final-candidate handling. Its package has
`MATCH_READY`, 30 participant rows, `complete_participant_export`, an empty
`98_errors.csv`, and was moved to `MatchStats/imported`. The remaining issue was
that handler IDs taken from `AddEventHandler` were not guaranteed to be Lua
integers. The included Live Editor event-handler test obtains IDs from
`GetEventHandlers` before calling the removal API.

AutoCapture is now v1.1.4 internally; embedded and standalone MatchStats obtain
new handler IDs from `GetEventHandlers`, normalize them with `math.tointeger`,
and remove only those integer IDs. The follow-up source-contract tests check this
contract. They do not execute Live Editor or FC26.

## Follow-up: 2026-11-08 capture and intermittent ReadShort error

At 00:34:47 local, MatchStats v1.1.1 completed and published capture
`pmc_20261108_001137_d21e36d0` with 30 participants, two team rows and zero
errors. The Atlas importer accepted it as export ID 21 but left it `ambiguous`
because the latest snapshot (ID 57, made at 00:11 before the match) has only 22
completed managed-team fixtures. At 00:34:53 the monitor logged
`post_match_export_suppressed_hotfix`; this is the deliberate safety hold, not
an export exception. After the career is saved, rerun AutoCapture from the stable
Career Hub to create a new startup snapshot. The Atlas watcher will then retry
linking pending MatchStats exports. No game script was run during this audit.

A separate `fixture_check_failed` was logged at 19:02:20 on 2026-11-06:
Live Editor's `MEMORY:ReadShort` wrapper tried to call the global `ReadShort`,
which had become a number. The writer of that global is unidentified. AutoCapture
v1.1.5 captures the native function at startup and uses that binding for fixture
checks and its embedded snapshot. This mitigates a later global reassignment;
the source-contract tests do not establish native runtime behavior.
