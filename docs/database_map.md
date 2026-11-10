# PROJECT ATLAS — DATABASE MAP

> Where the app data actually lives: `%LOCALAPPDATA%\ProjectAtlasTracker\workspaces\<workspace_id>\atlas_tracker.sqlite3`
> (registry: `%LOCALAPPDATA%\ProjectAtlasTracker\workspaces.json`, global prefs: `global_settings.json`).
> The `atlas.db` in the repository root is not the live career database.

## Global Settings (`app_settings`)
Installation-scoped key/value settings used by the server.
- Table: `app_settings`
- Columns:
    - `key` (TEXT, PRIMARY KEY): unique setting name.
    - `value` (TEXT): JSON-encoded value.
- Created automatically in `AppState.__post_init__` (`atlas/server_state.py`).
- Keys:
    - `llm_config`: `{"provider": "gemini", "keys": {"gemini": "<api-key>", "groq": "<api-key>"}, "model": ""}`
        - `provider`: `ollama` (default) | `gemini` | `groq`.
        - `keys`: per-provider API keys, written by `POST /api/llm/config`. The
          endpoint **merges** keys, so saving Groq keeps the Gemini key and vice
          versa; `{"remove": ["groq"]}` deletes only that provider's key.
        - `model`: optional override; empty means the server default per provider.
        - `GET /api/llm/config` also returns `configured` and `key_hints` so the
          Setup screen can show which providers already have a saved key.
        - Read by `atlas.commission.resolve_report_model()` for **every** report
          (match, match-player, player, next-match, team identity, auto-queued and
          retroactive replay), so the Setup choice is always the active provider.

## Career Management (`careers`, `snapshots`, `workspaces`)
- `careers`: career identity/metadata (`display_name`, `manager_name`, team ids).
- `snapshots`: versioned career states (`import_sequence`, `season_index`, `career_date`).
- `workspaces`: registry metadata mirrored from `workspaces.json`.

## Reference Data
- `reference_teams`, `reference_competitions`, ... managed by `ReferenceImporter`.

## Media Library
- `media_assets`: indexed media files and processing state.
- `media_sources`: folders tracked by the media watcher.

## Technical Commission (AI Analysis)
- `technical_commission_report_cache`: persisted AI reports.
    - Columns: `career_id`, `snapshot_id`, `mode`, `scope_key`, `model`, `source_hash`,
      `payload_json`, `generated_at`; PK `(career_id, snapshot_id, mode, scope_key, model)`.
    - `model` holds the **resolved provider model** (e.g. `qwen3.5:9b`,
      `gemini-flash-latest`, `llama-3.1-8b-instant`). Changing the provider in Setup
      therefore creates a new cache namespace; old rows stay ignored until refreshed.
- `technical_commission_cache`: deterministic metric payload cache (no LLM).
- `technical_commission_ai_cache`: legacy local-Ollama signal cache (`get_ollama_analysis`).
- `technical_commission_replay_runs` / `technical_commission_replay_tasks`:
  retroactive report queue.
- `fixture_observations`: facts derived from match data (read-only evidence source).

## Provider defaults (`atlas/commission.py`)
- `ollama` → `ATLAS_OLLAMA_MODEL` env or `qwen3.5:9b`.
- `gemini` → `gemini-flash-latest`, with automatic fallback through
  `gemini-3.6-flash` → `gemini-3.8-flash` → lite → `gemini-2.5-flash`.
- `groq` → `llama-3.1-8b-instant`, with fallback through
  `llama-3.3-70b-versatile` → `openai/gpt-oss-20b`.

## Runtime limits for AI reports
- `ATLAS_CLOUD_REPORT_DEADLINE_SECONDS` (default `100`): hard cap for one cloud
  report, covering the whole model-fallback chain. When the budget runs out the
  report returns a clear timeout message instead of queueing for minutes.
- `ATLAS_CLOUD_ATTEMPT_TIMEOUT_SECONDS` (default `25`): timeout of a single HTTP
  attempt; each model alias gets at most two attempts.
- `ATLAS_REPORT_WORKERS` (default `3`, max `6`): report jobs that may run in
  parallel. Local Ollama calls are serialised by a lock, so they never hit the
  GPU concurrently.
- Cloud quota: a model that answers `429` is skipped for as long as the provider
  says (`retry in 19h…`) or for 60 minutes when the message mentions a daily
  limit. Gemini's free tier is per model per day (20 requests for flash models),
  so the fallback chain can still answer through the lite models after the flash
  models run out.
- `ATLAS_OLLAMA_TIMEOUT_SECONDS` (default `240`): timeout for one local report.
