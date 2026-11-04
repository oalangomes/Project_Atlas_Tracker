"""Composable read-side API query mixins."""
from __future__ import annotations

from .server_query_base import QueryBaseMixin
from .server_query_analysis import AnalysisQueryMixin
from .server_query_competitions import CompetitionQueryMixin
from .server_query_dashboard import DashboardQueryMixin
from .server_query_entities import EntityQueryMixin
from .server_query_history import HistoryQueryMixin
from .server_query_management import ManagementQueryMixin
from .server_query_matches import MatchQueryMixin


class QueryApiMixin(
    QueryBaseMixin,
    AnalysisQueryMixin,
    DashboardQueryMixin,
    MatchQueryMixin,
    EntityQueryMixin,
    CompetitionQueryMixin,
    ManagementQueryMixin,
    HistoryQueryMixin,
):
    """Combined read-side implementation used by the HTTP handler."""

