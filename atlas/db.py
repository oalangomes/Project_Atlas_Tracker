from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from contextlib import contextmanager

SCHEMA_VERSION = 1


class ClosingConnection(sqlite3.Connection):
    """sqlite connection whose context manager also closes the handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS careers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    fingerprint_candidate TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    manager_name TEXT,
    initial_team_ea_id INTEGER,
    initial_team_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id),
    external_snapshot_id TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    exporter_version TEXT,
    season_index INTEGER NOT NULL,
    career_date TEXT NOT NULL,
    career_date_sort INTEGER NOT NULL,
    managed_team_ea_id INTEGER,
    managed_team_name TEXT,
    managed_completed_fixture_count INTEGER NOT NULL DEFAULT 0,
    global_completed_fixture_count INTEGER NOT NULL DEFAULT 0,
    exported_at_utc TEXT NOT NULL,
    import_sequence INTEGER NOT NULL DEFAULT 0,
    same_day_sequence INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL UNIQUE,
    import_status TEXT NOT NULL,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    capabilities_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_snapshots_career_order
ON snapshots(career_id, season_index, career_date_sort, managed_completed_fixture_count,
             global_completed_fixture_count, exported_at_utc, external_snapshot_id);

CREATE TABLE IF NOT EXISTS import_files (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    file_name TEXT NOT NULL,
    row_count INTEGER,
    byte_size INTEGER,
    status TEXT,
    note TEXT,
    PRIMARY KEY(snapshot_id, file_name)
);

CREATE TABLE IF NOT EXISTS snapshot_metadata (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY(snapshot_id, key)
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id),
    entity_type TEXT NOT NULL,
    ea_id TEXT NOT NULL,
    first_seen_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    last_seen_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    UNIQUE(career_id, entity_type, ea_id)
);
CREATE INDEX IF NOT EXISTS idx_entities_lookup ON entities(career_id, entity_type, ea_id);

CREATE TABLE IF NOT EXISTS player_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    ea_player_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    team_ea_id INTEGER,
    team_name TEXT,
    overall INTEGER,
    potential INTEGER,
    primary_position TEXT,
    nationality_id INTEGER,
    contract_valid_until TEXT,
    height INTEGER,
    weight INTEGER,
    preferred_foot_id INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, ea_player_id)
);
CREATE INDEX IF NOT EXISTS idx_player_states_team ON player_states(snapshot_id, team_ea_id);
CREATE INDEX IF NOT EXISTS idx_player_states_name ON player_states(snapshot_id, display_name);

CREATE TABLE IF NOT EXISTS team_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    ea_team_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,
    league_ea_id INTEGER,
    league_name TEXT,
    overall INTEGER,
    attack INTEGER,
    midfield INTEGER,
    defence INTEGER,
    domestic_prestige INTEGER,
    international_prestige INTEGER,
    profitability INTEGER,
    gender INTEGER,
    club_worth INTEGER,
    stadium_capacity INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, ea_team_id)
);

CREATE TABLE IF NOT EXISTS league_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    ea_league_id INTEGER NOT NULL,
    league_name TEXT NOT NULL,
    country_id INTEGER,
    level INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, ea_league_id)
);

CREATE TABLE IF NOT EXISTS competition_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    competition_object_id INTEGER NOT NULL,
    static_competition_id INTEGER,
    competition_name TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, competition_object_id)
);

CREATE TABLE IF NOT EXISTS roster_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    player_entity_id INTEGER NOT NULL REFERENCES entities(id),
    team_entity_id INTEGER NOT NULL REFERENCES entities(id),
    player_ea_id INTEGER NOT NULL,
    team_ea_id INTEGER NOT NULL,
    jersey_number INTEGER,
    teamsheet_slot_raw INTEGER,
    teamsheet_slot_label TEXT,
    primary_position TEXT,
    form INTEGER,
    injury INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, team_ea_id, player_ea_id)
);
CREATE INDEX IF NOT EXISTS idx_roster_team ON roster_states(snapshot_id, team_ea_id, jersey_number);

CREATE TABLE IF NOT EXISTS team_league_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    team_ea_id INTEGER NOT NULL,
    league_ea_id INTEGER,
    previous_league_ea_id INTEGER,
    current_table_position INTEGER,
    points INTEGER,
    matches_played INTEGER,
    home_wins INTEGER,
    home_draws INTEGER,
    home_losses INTEGER,
    away_wins INTEGER,
    away_draws INTEGER,
    away_losses INTEGER,
    home_goals_for INTEGER,
    home_goals_against INTEGER,
    away_goals_for INTEGER,
    away_goals_against INTEGER,
    champion INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, team_ea_id)
);

CREATE TABLE IF NOT EXISTS season_stat_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    player_ea_id INTEGER NOT NULL,
    represented_team_ea_id INTEGER NOT NULL,
    current_club_ea_id INTEGER,
    competition_object_id INTEGER NOT NULL,
    appearances INTEGER,
    average_rating REAL,
    man_of_the_match INTEGER,
    goals INTEGER,
    assists INTEGER,
    yellow_cards INTEGER,
    second_yellow_cards INTEGER,
    red_cards INTEGER,
    saves INTEGER,
    goals_conceded INTEGER,
    clean_sheets INTEGER,
    display_name TEXT,
    represented_team_name TEXT,
    competition_name TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, player_ea_id, competition_object_id, represented_team_ea_id)
);
CREATE INDEX IF NOT EXISTS idx_season_stats_player ON season_stat_states(snapshot_id, player_ea_id);
CREATE INDEX IF NOT EXISTS idx_season_stats_team ON season_stat_states(snapshot_id, represented_team_ea_id);

CREATE TABLE IF NOT EXISTS fixtures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id),
    fixture_key TEXT NOT NULL,
    competition_object_id INTEGER,
    static_competition_id INTEGER,
    stadium_ea_id INTEGER,
    home_team_ea_id INTEGER,
    away_team_ea_id INTEGER,
    UNIQUE(career_id, fixture_key)
);

CREATE TABLE IF NOT EXISTS fixture_observations (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id),
    fixture_key TEXT NOT NULL,
    competition_name TEXT,
    home_team_name TEXT,
    away_team_name TEXT,
    date TEXT,
    time TEXT,
    is_completed INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    home_penalties INTEGER,
    away_penalties INTEGER,
    managed_team_involved INTEGER,
    managed_team_result TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, fixture_id)
);
CREATE INDEX IF NOT EXISTS idx_fixture_obs_date ON fixture_observations(snapshot_id, date, time);

CREATE TABLE IF NOT EXISTS player_match_performances (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    artificial_key TEXT NOT NULL,
    fixture_key TEXT,
    join_status TEXT,
    player_ea_id INTEGER NOT NULL,
    display_name TEXT,
    date TEXT,
    rating REAL,
    minutes_played INTEGER,
    rating_position_raw INTEGER,
    actual_position TEXT,
    actual_position_source TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, artificial_key)
);

CREATE TABLE IF NOT EXISTS match_stat_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_export_id TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    source_path TEXT,
    career_id INTEGER REFERENCES careers(id),
    fixture_id INTEGER REFERENCES fixtures(id),
    snapshot_id INTEGER REFERENCES snapshots(id),
    export_status TEXT NOT NULL,
    linkage_status TEXT NOT NULL DEFAULT 'pending',
    linkage_confidence REAL,
    team0_ea_id INTEGER,
    team1_ea_id INTEGER,
    participant_rows INTEGER NOT NULL DEFAULT 0,
    team_rows INTEGER NOT NULL DEFAULT 0,
    trigger TEXT,
    pipeline_capture_id TEXT,
    semantic_hash TEXT,
    linkage_method TEXT,
    superseded_by_export_id INTEGER REFERENCES match_stat_exports(id),
    validation_json TEXT NOT NULL DEFAULT '{}',
    imported_at TEXT NOT NULL,
    raw_summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_match_stat_exports_fixture ON match_stat_exports(fixture_id);
CREATE INDEX IF NOT EXISTS idx_match_stat_exports_career ON match_stat_exports(career_id, imported_at);
CREATE INDEX IF NOT EXISTS idx_match_stat_exports_pending ON match_stat_exports(linkage_status, career_id);
CREATE INDEX IF NOT EXISTS idx_match_stat_exports_capture ON match_stat_exports(pipeline_capture_id);
-- Indexes that depend on v0.21.5 columns are created by Database.initialize()
-- after legacy databases have received those columns.  Keeping them here would
-- make SQLite evaluate the indexes before the additive v40 -> v41 migration.

CREATE TABLE IF NOT EXISTS match_player_detailed_stats (
    export_id INTEGER NOT NULL REFERENCES match_stat_exports(id) ON DELETE CASCADE,
    player_ea_id INTEGER NOT NULL,
    team_index INTEGER NOT NULL,
    minutes_played INTEGER,
    game_rating REAL,
    man_of_the_match INTEGER NOT NULL DEFAULT 0,
    npk_expected_goals REAL,
    expected_assists REAL,
    stats_json TEXT NOT NULL,
    PRIMARY KEY(export_id, player_ea_id, team_index)
);
CREATE INDEX IF NOT EXISTS idx_match_player_detailed_player ON match_player_detailed_stats(player_ea_id, export_id);

CREATE TABLE IF NOT EXISTS match_team_detailed_stats (
    export_id INTEGER NOT NULL REFERENCES match_stat_exports(id) ON DELETE CASCADE,
    team_index INTEGER NOT NULL,
    team_ea_id INTEGER,
    stats_json TEXT NOT NULL,
    PRIMARY KEY(export_id, team_index)
);
CREATE INDEX IF NOT EXISTS idx_match_team_detailed_team ON match_team_detailed_stats(team_ea_id, export_id);

CREATE TABLE IF NOT EXISTS contract_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    player_ea_id INTEGER NOT NULL,
    team_ea_id INTEGER,
    wage INTEGER,
    duration_months INTEGER,
    contract_status INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, player_ea_id)
);

CREATE TABLE IF NOT EXISTS loan_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    player_ea_id INTEGER NOT NULL,
    parent_team_ea_id INTEGER NOT NULL,
    loan_team_ea_id INTEGER NOT NULL,
    loan_end_date TEXT,
    is_loan_to_buy INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, player_ea_id, parent_team_ea_id, loan_team_ea_id)
);

CREATE TABLE IF NOT EXISTS youth_player_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    player_ea_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    overall INTEGER,
    potential INTEGER,
    primary_position TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, player_ea_id)
);

CREATE TABLE IF NOT EXISTS player_growth_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    player_ea_id INTEGER NOT NULL,
    display_name TEXT,
    overall INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, player_ea_id)
);

CREATE TABLE IF NOT EXISTS competition_progress_states (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    artificial_key TEXT NOT NULL,
    team_ea_id INTEGER,
    season INTEGER,
    competition_object_id INTEGER,
    stage_id INTEGER,
    has_team_won INTEGER,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, artificial_key)
);

CREATE TABLE IF NOT EXISTS generic_snapshot_rows (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    file_name TEXT NOT NULL,
    row_key TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, file_name, row_key)
);

CREATE TABLE IF NOT EXISTS import_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    level TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    snapshot_external_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);



CREATE TABLE IF NOT EXISTS reference_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT,
    source_hash TEXT,
    source_label TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    team_count INTEGER NOT NULL DEFAULT 0,
    competition_count INTEGER NOT NULL DEFAULT 0,
    kit_count INTEGER NOT NULL DEFAULT 0,
    stadium_count INTEGER NOT NULL DEFAULT 0,
    is_builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reference_teams (
    ea_team_id INTEGER PRIMARY KEY,
    team_name TEXT,
    color1 TEXT,
    color2 TEXT,
    color3 TEXT,
    source_import_id INTEGER REFERENCES reference_imports(id)
);

CREATE TABLE IF NOT EXISTS reference_competitions (
    ea_competition_id INTEGER PRIMARY KEY,
    color1 TEXT,
    color2 TEXT,
    source_import_id INTEGER REFERENCES reference_imports(id)
);

CREATE TABLE IF NOT EXISTS reference_competition_mappings (
    source_object_id INTEGER NOT NULL,
    ea_competition_id INTEGER NOT NULL,
    competition_name TEXT NOT NULL,
    competition_name_key TEXT NOT NULL,
    source_label TEXT NOT NULL DEFAULT 'builtin',
    PRIMARY KEY(source_object_id, ea_competition_id)
);
CREATE INDEX IF NOT EXISTS idx_reference_competition_mapping_name
ON reference_competition_mappings(competition_name_key);

CREATE TABLE IF NOT EXISTS reference_nations (
    nation_id INTEGER PRIMARY KEY,
    nation_name TEXT NOT NULL,
    iso_code TEXT,
    flag_code TEXT
);

CREATE TABLE IF NOT EXISTS reference_leagues (
    ea_league_id INTEGER PRIMARY KEY,
    league_name TEXT NOT NULL,
    country_id INTEGER,
    level INTEGER,
    source_import_id INTEGER REFERENCES reference_imports(id)
);

CREATE TABLE IF NOT EXISTS competition_media_links (
    competition_object_id INTEGER NOT NULL,
    competition_name_key TEXT NOT NULL DEFAULT '',
    competition_name TEXT,
    media_ea_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(competition_object_id, competition_name_key)
);
CREATE INDEX IF NOT EXISTS idx_competition_media_id ON competition_media_links(media_ea_id);

CREATE TABLE IF NOT EXISTS reference_kits (
    ea_kit_id INTEGER PRIMARY KEY,
    ea_team_id INTEGER NOT NULL,
    kit_type INTEGER NOT NULL,
    color1 TEXT,
    color2 TEXT,
    color3 TEXT,
    source_import_id INTEGER REFERENCES reference_imports(id)
);
CREATE INDEX IF NOT EXISTS idx_reference_kits_team ON reference_kits(ea_team_id, kit_type);

CREATE TABLE IF NOT EXISTS reference_stadiums (
    ea_stadium_id INTEGER PRIMARY KEY,
    stadium_name TEXT,
    source_import_id INTEGER REFERENCES reference_imports(id)
);

CREATE TABLE IF NOT EXISTS reference_team_stadiums (
    ea_team_id INTEGER NOT NULL,
    ea_stadium_id INTEGER NOT NULL,
    source_import_id INTEGER REFERENCES reference_imports(id),
    PRIMARY KEY(ea_team_id, ea_stadium_id)
);

CREATE TABLE IF NOT EXISTS media_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    path TEXT NOT NULL,
    recursive INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_scan_at TEXT,
    last_file_count INTEGER NOT NULL DEFAULT 0,
    last_imported_count INTEGER NOT NULL DEFAULT 0,
    last_warning_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_type, path)
);

CREATE TABLE IF NOT EXISTS media_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES media_sources(id),
    media_type TEXT NOT NULL,
    entity_type TEXT,
    ea_id INTEGER,
    season_start INTEGER,
    variant TEXT,
    kit_type INTEGER,
    source_path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    content_hash TEXT,
    source_mtime_ns INTEGER,
    source_size INTEGER,
    original_ext TEXT,
    width INTEGER,
    height INTEGER,
    original_copy_path TEXT,
    cache_path TEXT,
    thumb_path TEXT,
    status TEXT NOT NULL,
    warning TEXT,
    ignored_reason TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    processing_state TEXT NOT NULL DEFAULT 'pending',
    processing_error TEXT,
    processing_started_at TEXT,
    processed_at TEXT,
    conversion_ms INTEGER,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_path, source_hash)
);
CREATE INDEX IF NOT EXISTS idx_media_entity ON media_assets(entity_type, ea_id, media_type, season_start, is_active);
CREATE INDEX IF NOT EXISTS idx_media_status ON media_assets(status, media_type);

CREATE TABLE IF NOT EXISTS media_preferences (
    entity_type TEXT NOT NULL,
    ea_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    season_start INTEGER NOT NULL DEFAULT 0,
    preferred_asset_id INTEGER REFERENCES media_assets(id),
    PRIMARY KEY(entity_type, ea_id, media_type, season_start)
);


CREATE TABLE IF NOT EXISTS manual_seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    season_index INTEGER NOT NULL,
    label TEXT NOT NULL,
    start_year INTEGER NOT NULL,
    end_year INTEGER NOT NULL,
    managed_team_ea_id INTEGER,
    managed_team_name TEXT,
    notes TEXT,
    is_system_overlay INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(career_id, season_index)
);
CREATE INDEX IF NOT EXISTS idx_manual_seasons_career ON manual_seasons(career_id, season_index);

CREATE TABLE IF NOT EXISTS manual_competitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_season_id INTEGER NOT NULL REFERENCES manual_seasons(id) ON DELETE CASCADE,
    competition_type TEXT NOT NULL CHECK(competition_type IN ('league','cup','supercup','playoff','other')),
    competition_object_id INTEGER,
    static_competition_id INTEGER,
    competition_name TEXT NOT NULL,
    final_position INTEGER,
    result_text TEXT,
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manual_competitions_season ON manual_competitions(manual_season_id, sort_order, id);

CREATE TABLE IF NOT EXISTS manual_player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_competition_id INTEGER NOT NULL REFERENCES manual_competitions(id) ON DELETE CASCADE,
    player_ea_id INTEGER,
    player_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    appearances INTEGER NOT NULL DEFAULT 0,
    goals INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    clean_sheets INTEGER NOT NULL DEFAULT 0,
    average_rating REAL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(manual_competition_id, player_key)
);
CREATE INDEX IF NOT EXISTS idx_manual_player_stats_player ON manual_player_stats(player_ea_id, display_name);

CREATE TABLE IF NOT EXISTS manual_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_season_id INTEGER NOT NULL REFERENCES manual_seasons(id) ON DELETE CASCADE,
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('transfer','loan')),
    direction TEXT NOT NULL CHECK(direction IN ('incoming','outgoing')),
    player_ea_id INTEGER,
    player_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    from_team_ea_id INTEGER,
    from_team_name TEXT,
    to_team_ea_id INTEGER,
    to_team_name TEXT,
    fee INTEGER,
    currency TEXT NOT NULL DEFAULT 'EUR',
    transaction_date TEXT,
    loan_end_date TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manual_transactions_season ON manual_transactions(manual_season_id, transaction_type, direction);
CREATE INDEX IF NOT EXISTS idx_manual_transactions_player ON manual_transactions(player_ea_id, display_name);

CREATE TABLE IF NOT EXISTS manual_league_finishes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_season_id INTEGER NOT NULL REFERENCES manual_seasons(id) ON DELETE CASCADE,
    team_ea_id INTEGER,
    team_key TEXT NOT NULL,
    team_name TEXT NOT NULL,
    league_ea_id INTEGER,
    league_name TEXT NOT NULL,
    final_position INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(manual_season_id, team_key)
);
CREATE INDEX IF NOT EXISTS idx_manual_league_finishes_team
ON manual_league_finishes(team_ea_id, team_name, manual_season_id);

CREATE TABLE IF NOT EXISTS manual_player_development (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_season_id INTEGER NOT NULL REFERENCES manual_seasons(id) ON DELETE CASCADE,
    player_ea_id INTEGER NOT NULL,
    player_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('season_start','season_mid','season_end','custom')),
    stage_label TEXT,
    effective_date TEXT NOT NULL,
    overall INTEGER NOT NULL,
    potential INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(manual_season_id, player_key, effective_date)
);
CREATE INDEX IF NOT EXISTS idx_manual_player_development_player
ON manual_player_development(player_ea_id, manual_season_id, effective_date);

CREATE TABLE IF NOT EXISTS manual_season_awards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_season_id INTEGER NOT NULL REFERENCES manual_seasons(id) ON DELETE CASCADE,
    award_key TEXT NOT NULL,
    award_label TEXT NOT NULL,
    player_ea_id INTEGER,
    player_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    related_transaction_id INTEGER REFERENCES manual_transactions(id) ON DELETE SET NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(manual_season_id, award_key)
);
CREATE INDEX IF NOT EXISTS idx_manual_season_awards_season
ON manual_season_awards(manual_season_id, award_key);
CREATE INDEX IF NOT EXISTS idx_manual_season_awards_player
ON manual_season_awards(player_ea_id, display_name);

CREATE TABLE IF NOT EXISTS manual_season_reports (
    manual_season_id INTEGER PRIMARY KEY REFERENCES manual_seasons(id) ON DELETE CASCADE,
    summary_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    occurred_at TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_manual_change_log_career ON manual_change_log(career_id, id DESC);


-- v0.10.0 Financial Core. All finance records belong to Atlas career seasons.
CREATE TABLE IF NOT EXISTS finance_profiles (
    career_id INTEGER PRIMARY KEY REFERENCES careers(id) ON DELETE CASCADE,
    base_currency TEXT NOT NULL CHECK(base_currency IN ('EUR','GBP','USD')),
    financial_start_date TEXT NOT NULL,
    policy_key TEXT NOT NULL CHECK(policy_key IN ('cautious','balanced','ambitious','custom')),
    reserve_months REAL NOT NULL,
    transfer_allocation_rate REAL NOT NULL,
    sales_retention_rate REAL NOT NULL,
    wage_headroom_rate REAL NOT NULL,
    manual_reserve_floor_minor INTEGER NOT NULL DEFAULT 0,
    setup_mode TEXT NOT NULL DEFAULT 'guided',
    setup_completed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS finance_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    season_start_year INTEGER NOT NULL,
    season_label TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('setup','open','closing','closed')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    closing_note TEXT,
    UNIQUE(career_id, season_start_year)
);
CREATE INDEX IF NOT EXISTS idx_finance_periods_career ON finance_periods(career_id, season_start_year);

CREATE TABLE IF NOT EXISTS finance_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    account_class TEXT NOT NULL CHECK(account_class IN ('asset','liability','equity','income','expense')),
    parent_id INTEGER REFERENCES finance_accounts(id),
    system_key TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(career_id, code),
    UNIQUE(career_id, system_key)
);

CREATE TABLE IF NOT EXISTS finance_journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES finance_periods(id),
    booking_date TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('posted','reversed')) DEFAULT 'posted',
    model_version TEXT NOT NULL DEFAULT 'financial-core-1',
    reversal_of_id INTEGER REFERENCES finance_journal_entries(id),
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    posted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finance_journal_period ON finance_journal_entries(period_id, booking_date, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_journal_source
ON finance_journal_entries(career_id, source_type, source_id)
WHERE source_id IS NOT NULL AND reversal_of_id IS NULL;

CREATE TABLE IF NOT EXISTS finance_journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_entry_id INTEGER NOT NULL REFERENCES finance_journal_entries(id) ON DELETE RESTRICT,
    account_id INTEGER NOT NULL REFERENCES finance_accounts(id),
    debit_minor INTEGER NOT NULL DEFAULT 0 CHECK(debit_minor >= 0),
    credit_minor INTEGER NOT NULL DEFAULT 0 CHECK(credit_minor >= 0),
    currency TEXT NOT NULL,
    player_ea_id INTEGER,
    team_ea_id INTEGER,
    competition_ea_id INTEGER,
    cost_center TEXT,
    CHECK((debit_minor > 0 AND credit_minor = 0) OR (credit_minor > 0 AND debit_minor = 0))
);
CREATE INDEX IF NOT EXISTS idx_finance_lines_entry ON finance_journal_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_finance_lines_account ON finance_journal_lines(account_id);

CREATE TABLE IF NOT EXISTS finance_commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES finance_periods(id),
    source_type TEXT NOT NULL,
    source_id TEXT,
    direction TEXT NOT NULL CHECK(direction IN ('receivable','payable')),
    amount_minor INTEGER,
    amount_status TEXT NOT NULL CHECK(amount_status IN ('known','unknown','estimated')),
    commitment_kind TEXT NOT NULL,
    due_date TEXT,
    category_key TEXT NOT NULL,
    condition_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('open','partial','settled','cancelled','carried')) DEFAULT 'open',
    settled_minor INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finance_commitments_due ON finance_commitments(career_id, status, due_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_commitment_source
ON finance_commitments(career_id, source_type, source_id)
WHERE source_id IS NOT NULL AND status <> 'cancelled';

CREATE TABLE IF NOT EXISTS finance_recurring_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT,
    category_key TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('income','expense')),
    amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
    cadence TEXT NOT NULL CHECK(cadence IN ('weekly','monthly','quarterly','seasonal','annual')),
    start_date TEXT NOT NULL,
    end_date TEXT,
    next_due_date TEXT NOT NULL,
    fixed_cost INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finance_recurring_due ON finance_recurring_rules(career_id, active, next_due_date);

CREATE TABLE IF NOT EXISTS finance_budget_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL REFERENCES finance_periods(id) ON DELETE CASCADE,
    budget_type TEXT NOT NULL CHECK(budget_type IN ('transfer','player_wages')),
    approved_limit_minor INTEGER NOT NULL DEFAULT 0,
    occupied_minor INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','active','closed')) DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(period_id, budget_type)
);

CREATE TABLE IF NOT EXISTS finance_budget_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_plan_id INTEGER NOT NULL REFERENCES finance_budget_plans(id) ON DELETE CASCADE,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    reason TEXT NOT NULL,
    reversal_of_id INTEGER REFERENCES finance_budget_events(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finance_budget_events_plan ON finance_budget_events(budget_plan_id, event_date, id);

CREATE TABLE IF NOT EXISTS finance_forecast_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES finance_periods(id) ON DELETE CASCADE,
    scenario TEXT NOT NULL CHECK(scenario IN ('conservative','expected','ambitious')),
    source_type TEXT NOT NULL,
    source_id TEXT,
    direction TEXT NOT NULL CHECK(direction IN ('income','expense')),
    amount_minor INTEGER,
    amount_status TEXT NOT NULL CHECK(amount_status IN ('known','estimated','unknown')) DEFAULT 'estimated',
    probability REAL NOT NULL DEFAULT 1.0,
    due_date TEXT,
    status TEXT NOT NULL CHECK(status IN ('active','realized','cancelled')) DEFAULT 'active',
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finance_forecast_period ON finance_forecast_items(period_id, scenario, status);

CREATE TABLE IF NOT EXISTS finance_unresolved_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    period_id INTEGER REFERENCES finance_periods(id),
    source_type TEXT NOT NULL,
    source_id TEXT,
    event_date TEXT,
    issue_key TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    resolution_status TEXT NOT NULL CHECK(resolution_status IN ('open','ignored','resolved')) DEFAULT 'open',
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(career_id, source_type, source_id, issue_key)
);
CREATE INDEX IF NOT EXISTS idx_finance_unresolved_career ON finance_unresolved_events(career_id, resolution_status, id DESC);

-- v0.11.0 Dynamic Club Revenue. Generated suggestions remain separate from immutable journal entries.
CREATE TABLE IF NOT EXISTS finance_revenue_configs (
    period_id INTEGER PRIMARY KEY REFERENCES finance_periods(id) ON DELETE CASCADE,
    league_profile_key TEXT,
    profile_source TEXT NOT NULL DEFAULT 'automatic',
    media_enabled INTEGER NOT NULL DEFAULT 1,
    matchday_enabled INTEGER NOT NULL DEFAULT 1,
    prize_enabled INTEGER NOT NULL DEFAULT 1,
    merchandising_enabled INTEGER NOT NULL DEFAULT 1,
    wages_enabled INTEGER NOT NULL DEFAULT 1,
    operations_enabled INTEGER NOT NULL DEFAULT 1,
    merchandising_multiplier REAL NOT NULL DEFAULT 1.0,
    operations_multiplier REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS finance_generated_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES finance_periods(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('income','expense')),
    category_key TEXT NOT NULL,
    event_date TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
    amount_status TEXT NOT NULL CHECK(amount_status IN ('known','estimated')),
    competition_ea_id INTEGER,
    competition_name TEXT,
    fixture_id INTEGER REFERENCES fixtures(id),
    model_profile_key TEXT NOT NULL,
    quality_grade TEXT NOT NULL CHECK(quality_grade IN ('official','reconstructed','calibrated','estimated')),
    description TEXT NOT NULL,
    explanation_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('suggested','posted','ignored')) DEFAULT 'suggested',
    journal_entry_id INTEGER REFERENCES finance_journal_entries(id),
    manually_overridden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(career_id, source_key)
);
CREATE INDEX IF NOT EXISTS idx_finance_generated_period
ON finance_generated_events(period_id, status, event_date, id);
CREATE INDEX IF NOT EXISTS idx_finance_generated_fixture
ON finance_generated_events(fixture_id, event_type);

-- Derived player performance data. Imported OVR/POT remain immutable.
CREATE TABLE IF NOT EXISTS player_dynamic_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    player_ea_id INTEGER NOT NULL,
    base_overall INTEGER NOT NULL,
    potential INTEGER NOT NULL,
    dynamic_overall REAL NOT NULL,
    dynamic_delta REAL NOT NULL,
    form_score REAL NOT NULL,
    morale_score REAL NOT NULL,
    fitness_score REAL NOT NULL,
    performance_source TEXT NOT NULL CHECK(performance_source IN ('observed','simulated')),
    confidence REAL NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    breakdown_json TEXT NOT NULL DEFAULT '{}',
    model_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(snapshot_id, player_ea_id)
);
CREATE INDEX IF NOT EXISTS idx_player_dynamic_snapshot
ON player_dynamic_states(snapshot_id, dynamic_delta DESC, dynamic_overall DESC);
CREATE INDEX IF NOT EXISTS idx_player_dynamic_player
ON player_dynamic_states(career_id, player_ea_id, snapshot_id);

-- v0.14.3 Atlas World Simulation. These are derived model states, never imported snapshot facts.
CREATE TABLE IF NOT EXISTS atlas_world_simulation_runs (
    snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    model_version TEXT NOT NULL,
    league_row_count INTEGER NOT NULL DEFAULT 0,
    player_row_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS atlas_league_simulations (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    league_ea_id INTEGER NOT NULL,
    league_name TEXT NOT NULL,
    team_ea_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,
    position INTEGER NOT NULL,
    matches_played INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    draws INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    goals_for INTEGER NOT NULL,
    goals_against INTEGER NOT NULL,
    points INTEGER NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('observed','simulated')),
    confidence REAL NOT NULL,
    model_version TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, league_ea_id, team_ea_id)
);
CREATE INDEX IF NOT EXISTS idx_atlas_league_simulations_table
ON atlas_league_simulations(snapshot_id, league_ea_id, position);

CREATE TABLE IF NOT EXISTS atlas_simulated_player_stats (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    player_ea_id INTEGER NOT NULL,
    team_ea_id INTEGER NOT NULL,
    league_ea_id INTEGER NOT NULL,
    competition_object_id INTEGER,
    competition_name TEXT NOT NULL,
    appearances INTEGER NOT NULL,
    average_rating REAL,
    goals INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    yellow_cards INTEGER,
    red_cards INTEGER,
    saves INTEGER NOT NULL,
    goals_conceded INTEGER NOT NULL,
    clean_sheets INTEGER NOT NULL,
    confidence REAL NOT NULL,
    model_version TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, player_ea_id, league_ea_id)
);
CREATE INDEX IF NOT EXISTS idx_atlas_simulated_player_stats_team
ON atlas_simulated_player_stats(snapshot_id, team_ea_id, league_ea_id);

CREATE TABLE IF NOT EXISTS team_name_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    ea_team_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(career_id, ea_team_id)
);
CREATE INDEX IF NOT EXISTS idx_team_name_overrides_career
ON team_name_overrides(career_id, display_name);


-- Sponsorship and supplier system. Reference profiles remain external CSV; career agreements are stable.
CREATE TABLE IF NOT EXISTS commercial_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    season_start_year INTEGER NOT NULL,
    slot_type TEXT NOT NULL,
    partner_kind TEXT NOT NULL CHECK(partner_kind IN ('sponsor','supplier')),
    partner_id INTEGER NOT NULL,
    partner_name TEXT NOT NULL,
    annual_value_minor INTEGER NOT NULL,
    signing_payment_minor INTEGER NOT NULL DEFAULT 0,
    bonus_max_minor INTEGER NOT NULL DEFAULT 0,
    duration_seasons INTEGER NOT NULL,
    contract_class INTEGER,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    match_score REAL NOT NULL,
    explanation_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('open','accepted','declined','expired')) DEFAULT 'open',
    seed_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(career_id, seed_key)
);
CREATE INDEX IF NOT EXISTS idx_commercial_offers_career
ON commercial_offers(career_id,status,slot_type,season_start_year,id DESC);

CREATE TABLE IF NOT EXISTS commercial_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    slot_type TEXT NOT NULL,
    partner_kind TEXT NOT NULL CHECK(partner_kind IN ('sponsor','supplier')),
    partner_id INTEGER NOT NULL,
    partner_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','future','expired','cancelled')) DEFAULT 'active',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    start_season_start_year INTEGER NOT NULL,
    end_season_start_year INTEGER NOT NULL,
    signed_date TEXT,
    annual_value_minor INTEGER,
    amount_status TEXT NOT NULL CHECK(amount_status IN ('known','estimated','unknown')) DEFAULT 'estimated',
    signing_payment_minor INTEGER,
    bonus_max_minor INTEGER,
    terms_source TEXT NOT NULL CHECK(terms_source IN ('manual','calculated')) DEFAULT 'calculated',
    contract_class INTEGER,
    terms_json TEXT NOT NULL DEFAULT '{}',
    offer_id INTEGER REFERENCES commercial_offers(id) ON DELETE SET NULL,
    existing_at_setup INTEGER NOT NULL DEFAULT 0,
    finance_synced INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commercial_contracts_career
ON commercial_contracts(career_id,slot_type,start_date,end_date,id DESC);

CREATE TRIGGER IF NOT EXISTS immutable_finance_journal_lines_update
BEFORE UPDATE ON finance_journal_lines BEGIN SELECT RAISE(ABORT, 'immutable finance journal line'); END;
CREATE TRIGGER IF NOT EXISTS immutable_finance_journal_lines_delete
BEFORE DELETE ON finance_journal_lines BEGIN SELECT RAISE(ABORT, 'immutable finance journal line'); END;


CREATE TABLE IF NOT EXISTS transfer_pulses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    career_date TEXT NOT NULL,
    career_date_sort INTEGER NOT NULL,
    season_index INTEGER NOT NULL DEFAULT 0,
    managed_team_ea_id INTEGER,
    generated_at_utc TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    source_path TEXT NOT NULL,
    player_count INTEGER NOT NULL DEFAULT 0,
    loan_count INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transfer_pulses_career_date
ON transfer_pulses(career_id,career_date_sort,id);

CREATE TABLE IF NOT EXISTS transfer_world_players (
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    player_ea_id INTEGER NOT NULL,
    team_ea_id INTEGER,
    contract_valid_until TEXT,
    player_join_team_date TEXT,
    last_pulse_id INTEGER NOT NULL REFERENCES transfer_pulses(id) ON DELETE CASCADE,
    last_seen_date TEXT NOT NULL,
    PRIMARY KEY(career_id,player_ea_id)
);
CREATE INDEX IF NOT EXISTS idx_transfer_world_players_team
ON transfer_world_players(career_id,team_ea_id);

CREATE TABLE IF NOT EXISTS transfer_world_loans (
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    player_ea_id INTEGER NOT NULL,
    parent_team_ea_id INTEGER,
    loan_team_ea_id INTEGER,
    loan_end_date TEXT,
    is_loan_to_buy INTEGER NOT NULL DEFAULT 0,
    last_pulse_id INTEGER NOT NULL REFERENCES transfer_pulses(id) ON DELETE CASCADE,
    PRIMARY KEY(career_id,player_ea_id)
);

CREATE TABLE IF NOT EXISTS transfer_market_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    player_ea_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    from_team_ea_id INTEGER,
    to_team_ea_id INTEGER,
    parent_team_ea_id INTEGER,
    detected_date TEXT NOT NULL,
    effective_date TEXT,
    effective_date_earliest TEXT,
    effective_date_latest TEXT,
    season_index INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    confidence TEXT NOT NULL,
    facts_json TEXT NOT NULL DEFAULT '{}',
    estimate_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transfer_market_events_career
ON transfer_market_events(career_id,season_index,effective_date,id DESC);
CREATE INDEX IF NOT EXISTS idx_transfer_market_events_player
ON transfer_market_events(career_id,player_ea_id,id DESC);

CREATE TABLE IF NOT EXISTS transfer_backfill_runs (
    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
    season_index INTEGER NOT NULL,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(career_id,season_index)
);

CREATE TABLE IF NOT EXISTS transfer_calendar_settings (
    career_id INTEGER PRIMARY KEY REFERENCES careers(id) ON DELETE CASCADE,
    summer_start_mmdd TEXT NOT NULL DEFAULT '06-10',
    summer_end_mmdd TEXT NOT NULL DEFAULT '09-01',
    winter_start_mmdd TEXT NOT NULL DEFAULT '01-01',
    winter_end_mmdd TEXT NOT NULL DEFAULT '02-02',
    precontract_months INTEGER NOT NULL DEFAULT 6,
    source TEXT NOT NULL DEFAULT 'atlas_default',
    updated_at TEXT NOT NULL
);


"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # All services in one Atlas process share this Database instance. SQLite
        # permits only one writer at a time; without an application-level mutex,
        # snapshot imports, MatchStats, media workers and manual actions can race
        # each other and turn a harmless short-lived writer lock into an import
        # failure. RLock also lets compound operations (career reset/backup) call
        # normal transactional helpers while holding the same guard.
        self._write_lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def initialize(self) -> None:
        existing_schema_version = 0
        if self.path.is_file() and self.path.stat().st_size:
            probe = sqlite3.connect(self.path, timeout=30.0)
            try:
                table = probe.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'"
                ).fetchone()
                if table:
                    row = probe.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
                    try:
                        existing_schema_version = int(row[0]) if row else 0
                    except (TypeError, ValueError):
                        existing_schema_version = 0
            finally:
                probe.close()
        if 0 < existing_schema_version < SCHEMA_VERSION:
            self.create_backup(label=f"pre_schema_{SCHEMA_VERSION}")

        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            version_row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
            try:
                previous_schema_version = int(version_row[0]) if version_row else 0
            except (TypeError, ValueError):
                previous_schema_version = 0
            # v0.5 media scans use size/mtime as a fast path before hashing large EA-FC folders.
            competition_columns = {row[1] for row in conn.execute("PRAGMA table_info(competition_states)").fetchall()}
            if "static_competition_id" not in competition_columns:
                conn.execute("ALTER TABLE competition_states ADD COLUMN static_competition_id INTEGER")
            manual_season_columns = {row[1] for row in conn.execute("PRAGMA table_info(manual_seasons)").fetchall()}
            if "is_system_overlay" not in manual_season_columns:
                conn.execute("ALTER TABLE manual_seasons ADD COLUMN is_system_overlay INTEGER NOT NULL DEFAULT 0")
            development_columns = {row[1] for row in conn.execute("PRAGMA table_info(manual_player_development)").fetchall()}
            if development_columns and "stage_label" not in development_columns:
                conn.commit()
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.executescript(r"""
                    ALTER TABLE manual_player_development RENAME TO manual_player_development_v10;
                    CREATE TABLE manual_player_development (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        manual_season_id INTEGER NOT NULL REFERENCES manual_seasons(id) ON DELETE CASCADE,
                        player_ea_id INTEGER NOT NULL,
                        player_key TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        stage TEXT NOT NULL CHECK(stage IN ('season_start','season_mid','season_end','custom')),
                        stage_label TEXT,
                        effective_date TEXT NOT NULL,
                        overall INTEGER NOT NULL,
                        potential INTEGER NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(manual_season_id, player_key, effective_date)
                    );
                    INSERT INTO manual_player_development(
                        id,manual_season_id,player_ea_id,player_key,display_name,stage,stage_label,
                        effective_date,overall,potential,notes,created_at,updated_at)
                    SELECT pd.id,pd.manual_season_id,pd.player_ea_id,pd.player_key,pd.display_name,pd.stage,
                           CASE pd.stage WHEN 'season_start' THEN 'Season start' ELSE 'Season end' END,
                           COALESCE(pd.effective_date,CASE pd.stage WHEN 'season_start'
                               THEN printf('%04d-07-01',s.start_year) ELSE printf('%04d-06-30',s.end_year) END),
                           pd.overall,pd.potential,pd.notes,pd.created_at,pd.updated_at
                    FROM manual_player_development_v10 pd JOIN manual_seasons s ON s.id=pd.manual_season_id;
                    DROP TABLE manual_player_development_v10;
                    CREATE INDEX idx_manual_player_development_player
                    ON manual_player_development(player_ea_id, manual_season_id, effective_date);
                """)
                conn.execute("PRAGMA foreign_keys = ON")
            team_columns = {row[1] for row in conn.execute("PRAGMA table_info(team_states)").fetchall()}
            team_migrations = {
                "domestic_prestige": "INTEGER",
                "international_prestige": "INTEGER",
                "profitability": "INTEGER",
                "gender": "INTEGER",
            }
            for column, declaration in team_migrations.items():
                if column not in team_columns:
                    conn.execute(f"ALTER TABLE team_states ADD COLUMN {column} {declaration}")
            team_league_columns = {row[1] for row in conn.execute("PRAGMA table_info(team_league_states)").fetchall()}
            team_league_migrations = {
                "home_wins": "INTEGER",
                "home_draws": "INTEGER",
                "home_losses": "INTEGER",
                "away_wins": "INTEGER",
                "away_draws": "INTEGER",
                "away_losses": "INTEGER",
                "home_goals_for": "INTEGER",
                "home_goals_against": "INTEGER",
                "away_goals_for": "INTEGER",
                "away_goals_against": "INTEGER",
            }
            for column, declaration in team_league_migrations.items():
                if team_league_columns and column not in team_league_columns:
                    conn.execute(f"ALTER TABLE team_league_states ADD COLUMN {column} {declaration}")
            match_stat_export_columns = {row[1] for row in conn.execute("PRAGMA table_info(match_stat_exports)").fetchall()}
            match_stat_export_migrations = {
                "pipeline_capture_id": "TEXT",
                "semantic_hash": "TEXT",
                "linkage_method": "TEXT",
                "superseded_by_export_id": "INTEGER REFERENCES match_stat_exports(id)",
                "validation_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for column, declaration in match_stat_export_migrations.items():
                if match_stat_export_columns and column not in match_stat_export_columns:
                    conn.execute(f"ALTER TABLE match_stat_exports ADD COLUMN {column} {declaration}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_match_stat_exports_capture ON match_stat_exports(pipeline_capture_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_match_stat_exports_semantic ON match_stat_exports(semantic_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_match_stat_exports_active_fixture ON match_stat_exports(fixture_id,superseded_by_export_id)")
            season_stat_columns = {row[1] for row in conn.execute("PRAGMA table_info(season_stat_states)").fetchall()}
            if "second_yellow_cards" not in season_stat_columns:
                conn.execute("ALTER TABLE season_stat_states ADD COLUMN second_yellow_cards INTEGER")
            fixture_columns = {row[1] for row in conn.execute("PRAGMA table_info(fixtures)").fetchall()}
            if "static_competition_id" not in fixture_columns:
                conn.execute("ALTER TABLE fixtures ADD COLUMN static_competition_id INTEGER")
            if "stadium_ea_id" not in fixture_columns:
                conn.execute("ALTER TABLE fixtures ADD COLUMN stadium_ea_id INTEGER")
            media_columns = {row[1] for row in conn.execute("PRAGMA table_info(media_assets)").fetchall()}
            if "source_mtime_ns" not in media_columns:
                conn.execute("ALTER TABLE media_assets ADD COLUMN source_mtime_ns INTEGER")
            if "source_size" not in media_columns:
                conn.execute("ALTER TABLE media_assets ADD COLUMN source_size INTEGER")
            media_migrations = {
                "content_hash": "TEXT",
                "processing_state": "TEXT NOT NULL DEFAULT 'pending'",
                "processing_error": "TEXT",
                "processing_started_at": "TEXT",
                "processed_at": "TEXT",
                "conversion_ms": "INTEGER",
            }
            for column, declaration in media_migrations.items():
                if column not in media_columns:
                    conn.execute(f"ALTER TABLE media_assets ADD COLUMN {column} {declaration}")
            # v0.5.2/0.5.3 introduced a real crosswalk between career competition objects
            # and static EA media IDs.  Remove only older automatic guesses; manual
            # mappings remain authoritative and are never discarded.
            if previous_schema_version < 6:
                conn.execute("DELETE FROM competition_media_links WHERE source<>'manual'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_processing ON media_assets(processing_state,media_type,is_active)")
            conn.execute("""UPDATE media_assets SET processing_state=CASE
                WHEN status<>'assigned' THEN 'not_required'
                WHEN cache_path IS NOT NULL THEN 'ready'
                ELSE 'pending' END
                WHERE processing_state IS NULL OR processing_state='' OR processing_state='processing'""")
            immutable_tables = (
                "player_states", "team_states", "league_states", "competition_states",
                "roster_states", "team_league_states", "season_stat_states",
                "fixture_observations", "player_match_performances", "contract_states",
                "loan_states", "youth_player_states", "player_growth_states",
                "competition_progress_states", "generic_snapshot_rows", "import_files",
                "snapshot_metadata",
            )
            for table in immutable_tables:
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_update "
                    f"BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'immutable snapshot state'); END"
                )
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_delete "
                    f"BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'immutable snapshot state'); END"
                )
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def backup_dir(self) -> Path:
        path = self.path.parent / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_backup(self, label: str = "manual") -> Path:
        # Keep in-process writers out while the backup snapshot is established.
        # SQLite backup itself is online-safe; this guard mainly prevents Atlas'
        # own background workers from racing reset/backup operations.
        with self.write_guard():
            safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip()) or "manual"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = self.backup_dir() / f"atlas_core_{stamp}_{safe_label}.sqlite3"
            suffix = 1
            while target.exists():
                target = self.backup_dir() / f"atlas_core_{stamp}_{safe_label}_{suffix}.sqlite3"
                suffix += 1
            source = sqlite3.connect(self.path, timeout=30.0)
            destination = sqlite3.connect(target)
            try:
                source.execute("PRAGMA busy_timeout = 30000")
                destination.execute("PRAGMA busy_timeout = 30000")
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            return target

    def list_backups(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for path in sorted(self.backup_dir().glob("atlas_core_*.sqlite3"), reverse=True):
            stat = path.stat()
            result.append({
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            })
        return result[:100]

    @contextmanager
    def write_guard(self) -> Iterator[None]:
        """Serialize writers that originate inside this Atlas process."""
        with self._write_lock:
            yield

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        # BEGIN IMMEDIATE intentionally claims the SQLite writer slot up front.
        # The Python guard avoids needless contention between Atlas background
        # services before SQLite itself has to arbitrate the write.
        with self.write_guard():
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
