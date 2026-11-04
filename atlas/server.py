"""HTTP facade for Project Atlas.

The implementation is split by responsibility; this module retains the public
imports used by launchers and third-party integrations.
"""
from __future__ import annotations

from .server_http import ApiHandler, AtlasHttpServer
from .server_state import AppState
from .server_utils import (
    age_on_date, aggregate_standings, annotate_knockout_progress, as_int, clean_raw,
    competition_format_info, contract_role_label, ea_day_to_iso, fixture_group_value,
    latest_snapshot, parse_fc_date, parse_raw, rows_to_dicts, subtract_months,
    youth_potential_range,
)

__all__ = [
    "ApiHandler", "AppState", "AtlasHttpServer", "age_on_date",
    "aggregate_standings", "annotate_knockout_progress", "as_int", "clean_raw",
    "competition_format_info", "contract_role_label", "ea_day_to_iso",
    "fixture_group_value", "latest_snapshot", "parse_fc_date", "parse_raw",
    "rows_to_dicts", "subtract_months", "youth_potential_range",
]
