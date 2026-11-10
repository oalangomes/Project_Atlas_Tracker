# PROJECT ATLAS - DATABASE MAP

## Global Settings (app_settings)
Used for installation-wide preferences and infrastructure keys.
- Table: `app_settings`
- Columns:
    - `key` (TEXT, PRIMARY KEY): Unique identifier for the setting.
    - `value` (TEXT): JSON string containing the setting value.
- Key examples:
    - `llm_config`: `{ "provider": "gemini", "keys": { "gemini": "AIza..." } }`

## Career Management (careers, snapshots, workspaces)
- `careers`: Basic career identity and metadata.
- `snapshots`: Versioned snapshots of a career state.
- `workspaces`: Logical groupings (branches/sandboxes) of career data.

## Reference Data
- `reference_teams`, `reference_competitions`, etc. (Internal tables managed by ReferenceImporter).

## Media Library
- `media_assets`: Indexed media files and their processing state.
- `media_sources`: Folders tracked by the media watcher.

## Technical Commission (AI Analysis)
- `commission_reports`: Cached AI analysis results.
- `fixture_observations`: Facts derived from match data.
