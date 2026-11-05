from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .server_queries import QueryApiMixin
from .server_state import AppState
from .media_utils import season_start_from_date
from .server_utils import as_int, career_clock, input_bool, latest_snapshot, parse_raw, rows_to_dicts
from .paths import write_snapshot_root, log_dir


class ApiHandler(QueryApiMixin, BaseHTTPRequestHandler):
    server_version = f"ProjectAtlas/{__version__}"

    @property
    def state(self) -> AppState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    _performance_log_lock = threading.Lock()

    @classmethod
    def _log_slow_request(cls, method: str, path: str, elapsed: float) -> None:
        if elapsed < 0.75:
            return
        try:
            target = log_dir() / "atlas_performance.log"
            line = f"{datetime.now().isoformat(timespec='milliseconds')}\t{method}\t{elapsed:.3f}s\t{path}\n"
            with cls._performance_log_lock:
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except OSError:
            pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        started = time.perf_counter()
        try:
            media_match = re.fullmatch(r"/api/media/files/(\d+)/(cache|thumb|original)", parsed.path)
            if media_match:
                try:
                    self._serve_media(int(media_match.group(1)), media_match.group(2))
                except ValueError as exc:
                    self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                return
            if parsed.path.startswith("/api/"):
                try:
                    self._api_get(parsed.path, parse_qs(parsed.query))
                except ValueError as exc:
                    self._json({"error": str(exc), "type": type(exc).__name__}, HTTPStatus.NOT_FOUND)
                except Exception as exc:  # pragma: no cover - defensive boundary
                    self._json({"error": str(exc), "type": type(exc).__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._serve_static(parsed.path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        finally:
            if parsed.path.startswith("/api/"):
                self._log_slow_request("GET", self.path, time.perf_counter() - started)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        started = time.perf_counter()
        try:
            try:
                self._api_post(parsed.path, self._read_json())
            except Exception as exc:
                self._json({"error": str(exc), "type": type(exc).__name__}, HTTPStatus.BAD_REQUEST)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        finally:
            if parsed.path.startswith("/api/"):
                self._log_slow_request("POST", self.path, time.perf_counter() - started)

    def _api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/status":
            self._json(self.state.status())
            return
        if path == "/api/workspaces":
            self._json(self.state.workspaces.overview())
            return
        if path == "/api/settings":
            self._json(self.state.settings.get())
            return
        if path == "/api/media/status":
            self._json(self.state.media.status())
            return
        if path == "/api/media/progress":
            self._json(self.state.media.progress())
            return
        if path == "/api/media/assets":
            status = (query.get("status") or [None])[0]
            media_type = (query.get("type") or [None])[0]
            limit = as_int((query.get("limit") or [500])[0]) or 500
            self._json(self.state.media.assets(status=status, media_type=media_type, limit=limit))
            return
        if path == "/api/media/competition-mappings":
            snapshot_id = as_int((query.get("snapshotId") or [None])[0])
            if snapshot_id is None:
                raise ValueError("Snapshot ID is missing.")
            self._json(self.state.media.competition_mappings(snapshot_id))
            return
        if path == "/api/reference/status":
            self._json(self.state.reference.status())
            return
        if path == "/api/ollama/models":
            from .commission import ollama_models
            self._json(ollama_models())
            return
        match = re.fullmatch(r"/api/careers/(\d+)/commission/report-cache", path)
        if match:
            career_id = int(match.group(1))
            snapshot_id = as_int((query.get("snapshot_id") or query.get("snapshotId") or [None])[0])
            mode = str((query.get("mode") or [""])[0])
            fixture_id = as_int((query.get("fixture_id") or query.get("fixtureId") or [None])[0])
            player_ea_id = as_int((query.get("player_ea_id") or query.get("playerEaId") or [None])[0])
            model = str((query.get("model") or [""])[0]).strip() or None
            if snapshot_id is None:
                raise ValueError("Snapshot ID is missing.")
            from .commission import get_cached_commission_report
            with self.state.database.connect() as conn:
                self._json(get_cached_commission_report(conn, career_id, snapshot_id, mode, fixture_id, player_ea_id, model))
            return
        match = re.fullmatch(r"/api/careers/(\d+)/commission/report-jobs/([a-f0-9]{32})", path)
        if match:
            from .commission import get_commission_report_job
            self._json(get_commission_report_job(int(match.group(1)), match.group(2)))
            return
        match = re.fullmatch(r"/api/careers/(\d+)/commission/retroactive-report-jobs/([a-f0-9]{32})", path)
        if match:
            from .commission import get_retroactive_commission_report_job
            self._json(get_retroactive_commission_report_job(self.state.database, int(match.group(1)), match.group(2)))
            return
        if path == "/api/careers":
            with self.state.database.connect() as conn:
                rows = conn.execute(
                    """SELECT c.*,COUNT(s.id) snapshot_count,MAX(s.import_sequence) latest_sequence
                       FROM careers c LEFT JOIN snapshots s ON s.career_id=c.id
                       GROUP BY c.id ORDER BY c.updated_at DESC"""
                ).fetchall()
                result: list[dict[str, Any]] = []
                for row in rows:
                    item = dict(row)
                    latest = latest_snapshot(conn, row["id"])
                    item["latestSnapshot"] = dict(latest) if latest else None
                    result.append(self.state.club_names.apply_payload(item, int(row["id"])))
            self._json(result)
            return

        match = re.fullmatch(r"/api/careers/(\d+)", path)
        if match:
            career_id = int(match.group(1))
            with self.state.database.connect() as conn:
                career = conn.execute("SELECT * FROM careers WHERE id=?", (career_id,)).fetchone()
                if not career:
                    raise ValueError("Career not found.")
                latest = latest_snapshot(conn, career_id)
            self._json({"career": dict(career), "latestSnapshot": dict(latest) if latest else None})
            return

        match = re.fullmatch(r"/api/careers/(\d+)/clock", path)
        if match:
            career_id = int(match.group(1))
            with self.state.database.connect() as conn:
                if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
                    raise ValueError("Career not found.")
                latest = latest_snapshot(conn, career_id)
                if not latest:
                    self._json({"careerDate": None, "source": None, "snapshotDate": None, "pulseDate": None, "stalenessDays": 0, "recentPulses": []})
                    return
                clock = career_clock(conn, career_id)
                pulse_count = int(conn.execute("SELECT COUNT(*) FROM transfer_pulses WHERE career_id=?", (career_id,)).fetchone()[0])
                pulses = rows_to_dicts(conn.execute(
                    "SELECT id,public_id,career_date,season_index,managed_team_ea_id,player_count,loan_count,generated_at_utc,imported_at "
                    "FROM transfer_pulses WHERE career_id=? ORDER BY career_date_sort DESC,id DESC LIMIT 20",
                    (career_id,),
                ).fetchall())
            self._json({**clock, "pulseCount": pulse_count, "recentPulses": pulses})
            return

        match = re.fullmatch(r"/api/careers/(\d+)/snapshots", path)
        if match:
            career_id = int(match.group(1))
            with self.state.database.connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC",
                    (career_id,),
                ).fetchall()
                season_numbers = self._career_season_numbers(conn, career_id)
            items = rows_to_dicts(rows)
            for item in items:
                start_year = season_start_from_date(item.get("career_date"))
                item["season_start_year"] = start_year
                item["season_label"] = f"{start_year}/{str(start_year + 1)[-2:]}" if start_year is not None else "Unknown season"
                item["career_season_number"] = season_numbers.get(start_year) if start_year is not None else None
                item["ea_season_index"] = item.get("season_index")
            self._json(items)
            return

        match = re.fullmatch(r"/api/careers/(\d+)/finance", path)
        if match:
            period_id = as_int((query.get("period_id") or [None])[0])
            self._json(self.state.finance_core.overview(int(match.group(1)), period_id))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/club-names", path)
        if match:
            self._json(self.state.club_names.list(int(match.group(1))))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/commercial", path)
        if match:
            snapshot_id = as_int((query.get("snapshotId") or [None])[0])
            self._json(self.state.commercial.overview(int(match.group(1)), snapshot_id))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/manual-data", path)
        if match:
            self._json(self.state.manual.overview(int(match.group(1))))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/players/search", path)
        if match:
            text = (query.get("q") or [""])[0].strip()
            limit = as_int((query.get("limit") or [40])[0]) or 40
            self._json(self.state.manual.search_players(int(match.group(1)), text, limit))
            return

        if path == "/api/backups":
            self._json(self.state.database.list_backups())
            return

        match = re.fullmatch(r"/api/careers/(\d+)/compare", path)
        if match:
            from_id = as_int((query.get("from") or [None])[0])
            to_id = as_int((query.get("to") or [None])[0])
            if from_id is None or to_id is None:
                raise ValueError("Two snapshot IDs are required for comparison.")
            self._json(self._compare(int(match.group(1)), from_id, to_id))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/chronology", path)
        if match:
            snapshot_id = as_int((query.get("snapshot_id") or [None])[0])
            self._json(self._chronology(int(match.group(1)), snapshot_id))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/analysis", path)
        if match:
            career_id = int(match.group(1))
            snapshot_id = as_int((query.get("snapshot_id") or [None])[0])
            season_index = as_int((query.get("season_index") or [None])[0])
            if season_index is not None and season_index < 0:
                season_index = None
            if snapshot_id is None:
                with self.state.database.connect() as conn:
                    latest = latest_snapshot(conn, career_id)
                if not latest:
                    raise ValueError("Analysis requires at least one snapshot.")
                snapshot_id = int(latest["id"])
            self._json(self._analysis(career_id, snapshot_id, season_index))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/commission", path)
        if match:
            career_id = int(match.group(1))
            snapshot_id = as_int((query.get("snapshot_id") or [None])[0])
            season_index = as_int((query.get("season_index") or [None])[0])
            if snapshot_id is None:
                with self.state.database.connect() as conn:
                    latest = conn.execute(
                        "SELECT id FROM snapshots WHERE career_id=? AND (? IS NULL OR season_index=?) ORDER BY import_sequence DESC LIMIT 1",
                        (career_id, season_index, season_index),
                    ).fetchone()
                if not latest:
                    raise ValueError("Commission analysis requires at least one snapshot.")
                snapshot_id = int(latest["id"])
            from .commission import get_commission
            with self.state.database.connect() as conn:
                self._json(get_commission(conn, career_id, snapshot_id))
            return

        match = re.fullmatch(r"/api/snapshots/(\d+)/dashboard", path)
        if match:
            self._json(self._dashboard(int(match.group(1))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/coverage", path)
        if match:
            self._json(self._coverage(int(match.group(1))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/squad", path)
        if match:
            self._json(self._squad(int(match.group(1))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/matches", path)
        if match:
            self._json(self._matches(int(match.group(1))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/matches/(\d+)", path)
        if match:
            self._json(self._match_detail(int(match.group(1)), int(match.group(2))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/players/(\d+)", path)
        if match:
            self._json(self._player(int(match.group(1)), int(match.group(2))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/clubs/(\d+)/squad", path)
        if match:
            club = self._club(int(match.group(1)), int(match.group(2)))
            self._json({"snapshot": club.get("snapshot"), "team": club.get("team"), "summary": club.get("summary"), "squad": club.get("squad") or []})
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/clubs/(\d+)", path)
        if match:
            self._json(self._club(int(match.group(1)), int(match.group(2))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/competitions", path)
        if match:
            self._json(self._competitions(int(match.group(1))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/world-leagues/(\d+)", path)
        if match:
            self._json(self.state.player_dynamics.world.league_table(int(match.group(1)), int(match.group(2))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/competitions/(\d+)", path)
        if match:
            self._json(self._competition(int(match.group(1)), int(match.group(2))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/contracts", path)
        if match:
            self._json(self._contracts(int(match.group(1))))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/loans", path)
        if match:
            season_index = as_int((query.get("season_index") or [None])[0])
            self._json(self._loans(int(match.group(1)), season_index))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/transfers", path)
        if match:
            season_index = as_int((query.get("season_index") or [None])[0])
            self._json(self._transfers(int(match.group(1)), season_index))
            return
        match = re.fullmatch(r"/api/snapshots/(\d+)/youth", path)
        if match:
            self._json(self._youth(int(match.group(1))))
            return

        if path == "/api/search":
            snapshot_raw = (query.get("snapshot_id") or [""])[0]
            text = (query.get("q") or [""])[0].strip()
            if not snapshot_raw or not text:
                self._json([])
                return
            self._json(self._search(int(snapshot_raw), text))
            return

        if path == "/api/imports":
            with self.state.database.connect() as conn:
                rows = conn.execute("SELECT * FROM import_events ORDER BY id DESC LIMIT 200").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["details"] = parse_raw(item.pop("details_json", None))
                result.append(item)
            self._json(result)
            return

        self._json({"error": f"API endpoint not found: {self.command} {path}"}, 404)

    def _api_post(self, path: str, payload: dict[str, Any]) -> None:
        match = re.fullmatch(r"/api/careers/(\d+)/finance/(setup|journal/post|journal/reverse|commitments/save|commitments/settle|recurring/save|recurring/run|budgets/adjust|forecasts/save|unresolved/resolve|periods/close|revenue/config|revenue/post|revenue/post-due|revenue/ignore|revenue/override)", path)
        if match:
            career_id = int(match.group(1))
            action = match.group(2)
            service = self.state.finance_core
            if action == "setup":
                self._json(service.setup(career_id, payload))
            elif action == "journal/post":
                self._json(service.post_manual(career_id, payload))
            elif action == "journal/reverse":
                entry_id = as_int(payload.get("entryId"))
                if entry_id is None:
                    raise ValueError("Journal entry ID is missing.")
                self._json(service.reverse_entry(career_id, entry_id, str(payload.get("reason") or "")))
            elif action == "commitments/save":
                self._json(service.save_commitment(career_id, payload))
            elif action == "commitments/settle":
                commitment_id = as_int(payload.get("commitmentId"))
                if commitment_id is None:
                    raise ValueError("Commitment ID is missing.")
                self._json(service.settle_commitment(career_id, commitment_id, payload))
            elif action == "recurring/save":
                self._json(service.save_recurring(career_id, payload))
            elif action == "recurring/run":
                self._json(service.run_due(career_id, payload.get("throughDate")))
            elif action == "budgets/adjust":
                self._json(service.adjust_budget(career_id, payload))
            elif action == "forecasts/save":
                self._json(service.save_forecast(career_id, payload))
            elif action == "unresolved/resolve":
                event_id = as_int(payload.get("eventId"))
                if event_id is None:
                    raise ValueError("Conflict ID is missing.")
                self._json(service.resolve_unresolved(career_id, event_id, str(payload.get("status") or "resolved")))
            elif action == "periods/close":
                self._json(service.close_period(career_id, payload))
            elif action == "revenue/config":
                self._json(service.save_revenue_config(career_id, payload))
            elif action == "revenue/post":
                event_id = as_int(payload.get("eventId"))
                if event_id is None:
                    raise ValueError("Automatic transaction ID is missing.")
                self._json(service.post_generated_event(career_id, event_id))
            elif action == "revenue/post-due":
                self._json(service.post_due_generated(career_id, payload))
            elif action == "revenue/ignore":
                event_id = as_int(payload.get("eventId"))
                if event_id is None:
                    raise ValueError("Automatic transaction ID is missing.")
                self._json(service.ignore_generated_event(career_id, event_id))
            elif action == "revenue/override":
                event_id = as_int(payload.get("eventId"))
                if event_id is None:
                    raise ValueError("Automatic transaction ID is missing.")
                self._json(service.override_generated_event(career_id, event_id, payload.get("amount")))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/commercial/(contracts/existing|offers/generate|offers/accept|offers/decline|contracts/cancel)", path)
        if match:
            career_id = int(match.group(1)); action = match.group(2)
            if action == "contracts/existing":
                self._json(self.state.commercial.save_existing_contract(career_id, payload))
            elif action == "offers/generate":
                self._json(self.state.commercial.generate_offers(career_id, payload))
            elif action == "offers/accept":
                offer_id = as_int(payload.get("offerId"))
                if offer_id is None: raise ValueError("Offer ID is missing.")
                self._json(self.state.commercial.accept_offer(career_id, offer_id))
            elif action == "offers/decline":
                offer_id = as_int(payload.get("offerId"))
                if offer_id is None: raise ValueError("Offer ID is missing.")
                self._json(self.state.commercial.decline_offer(career_id, offer_id))
            else:
                contract_id = as_int(payload.get("contractId"))
                if contract_id is None: raise ValueError("Contract ID is missing.")
                self._json(self.state.commercial.cancel_contract(career_id, contract_id))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/reset", path)
        if match:
            career_id = int(match.group(1))
            snapshot_id = as_int(payload.get("snapshotId"))
            if snapshot_id is None:
                raise ValueError("Snapshot ID is missing.")
            delete_raw = input_bool(payload.get("deleteRawFiles"), "Permanently delete raw files", default=False)
            # Prevent the hot-folder watcher from immediately re-importing a package
            # while the database is being reset and raw folders are being archived.
            self.state.watcher.stop()
            try:
                try:
                    result = self.state.career_reset.reset_to_snapshot(
                        career_id, snapshot_id, delete_raw_files=delete_raw
                    )
                except Exception as exc:
                    try:
                        with self.state.database.transaction() as conn:
                            conn.execute(
                                "INSERT INTO import_events(occurred_at,level,code,message,snapshot_external_id,details_json) VALUES(?,?,?,?,?,?)",
                                (datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "error", "career_reset_failed",
                                 f"Career reset failed for snapshot {snapshot_id}: {exc}",
                                 None, json.dumps({"careerId": career_id, "snapshotId": snapshot_id, "error": str(exc)}, separators=(",", ":"))),
                            )
                    except Exception:
                        pass
                    raise
            finally:
                self.state.watcher.start()
            self._json(result)
            return

        match = re.fullmatch(r"/api/careers/(\d+)/match-stats/link", path)
        if match:
            career_id = int(match.group(1))
            linked = self.state.match_stats.link_export(career_id, payload)
            try:
                from .commission import queue_auto_commission_reports
                queue_auto_commission_reports(self.state.database, career_id, int(linked["fixtureId"]))
            except (KeyError, ValueError):
                pass
            self._json(linked)
            return

        match = re.fullmatch(r"/api/careers/(\d+)/club-names/(save|delete)", path)
        if match:
            career_id = int(match.group(1))
            if match.group(2) == "save":
                self._json(self.state.club_names.save(career_id, payload))
            else:
                team_id = as_int(payload.get("eaTeamId"))
                if team_id is None:
                    raise ValueError("Club ID is missing.")
                self._json(self.state.club_names.delete(career_id, team_id))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/manual-data/(seasons|competitions|stats|transactions|league-finishes|development|awards)/(save|delete)", path)
        if match:
            career_id = int(match.group(1))
            entity = match.group(2)
            action = match.group(3)
            service = self.state.manual
            if action == "save":
                handlers = {
                    "seasons": service.save_season,
                    "competitions": service.save_competition,
                    "stats": service.save_stat,
                    "transactions": service.save_transaction,
                    "league-finishes": service.save_league_finish,
                    "development": service.save_development,
                    "awards": service.save_season_award,
                }
                self._json(handlers[entity](career_id, payload))
            else:
                entity_id = as_int(payload.get("id"))
                if entity_id is None:
                    raise ValueError("Record ID is missing.")
                handlers = {
                    "seasons": service.delete_season,
                    "competitions": service.delete_competition,
                    "stats": service.delete_stat,
                    "transactions": service.delete_transaction,
                    "league-finishes": service.delete_league_finish,
                    "development": service.delete_development,
                    "awards": service.delete_season_award,
                }
                self._json(handlers[entity](career_id, entity_id))
            return
        match = re.fullmatch(r"/api/careers/(\d+)/commission/ollama", path)
        if match:
            career_id = int(match.group(1))
            snapshot_id = as_int(payload.get("snapshot_id") or payload.get("snapshotId"))
            if snapshot_id is None:
                raise ValueError("Snapshot ID is missing.")
            model = str(payload.get("model") or "").strip() or None
            from .commission import get_ollama_analysis
            with self.state.database.connect() as conn:
                self._json(get_ollama_analysis(conn, career_id, snapshot_id, model))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/commission/report", path)
        if match:
            career_id = int(match.group(1))
            snapshot_id = as_int(payload.get("snapshot_id") or payload.get("snapshotId"))
            if snapshot_id is None:
                raise ValueError("Snapshot ID is missing.")
            mode = str(payload.get("mode") or "").strip()
            fixture_id = as_int(payload.get("fixture_id") or payload.get("fixtureId"))
            player_ea_id = as_int(payload.get("player_ea_id") or payload.get("playerEaId"))
            model = str(payload.get("model") or "").strip() or None
            force_refresh = input_bool(payload.get("force_refresh") or payload.get("forceRefresh"), "Force new Ollama analysis", default=False)
            clarifications = payload.get("clarifications")
            from .commission import get_commission_report
            with self.state.database.connect() as conn:
                self._json(get_commission_report(conn, career_id, snapshot_id, mode, fixture_id, player_ea_id,
                                                  model, force_refresh, clarifications=clarifications))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/commission/report-jobs", path)
        if match:
            career_id = int(match.group(1))
            snapshot_id = as_int(payload.get("snapshot_id") or payload.get("snapshotId"))
            if snapshot_id is None:
                raise ValueError("Snapshot ID is missing.")
            mode = str(payload.get("mode") or "").strip()
            fixture_id = as_int(payload.get("fixture_id") or payload.get("fixtureId"))
            player_ea_id = as_int(payload.get("player_ea_id") or payload.get("playerEaId"))
            model = str(payload.get("model") or "").strip() or None
            force_refresh = input_bool(payload.get("force_refresh") or payload.get("forceRefresh"), "Force new Ollama analysis", default=False)
            clarifications = payload.get("clarifications")
            from .commission import get_commission_report, start_commission_report_job

            def work() -> dict[str, Any]:
                with self.state.database.connect() as conn:
                    return get_commission_report(conn, career_id, snapshot_id, mode, fixture_id, player_ea_id,
                                                 model, force_refresh, clarifications=clarifications)

            self._json(start_commission_report_job(career_id, work))
            return

        match = re.fullmatch(r"/api/careers/(\d+)/commission/retroactive-report-jobs", path)
        if match:
            career_id = int(match.group(1))
            from .commission import (REPORT_VERSION, _find_resumable_replay, ollama_models,
                                     start_retroactive_commission_reports)
            from .settings import application_language
            selected_model = os.environ.get("ATLAS_OLLAMA_MODEL") or "qwen3.5:9b"
            selected_language = application_language()
            available = ollama_models(timeout=3.0)
            if not available.get("available") or selected_model not in available.get("models", []):
                raise ValueError("Ollama está offline ou o modelo configurado não está instalado.")
            with self.state.database.connect() as conn:
                if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
                    raise ValueError("Carreira não encontrada.")
                # Index 0 is a valid first season; never treat it as missing.
                season_value = payload["season_index"] if "season_index" in payload else payload.get("seasonIndex")
                season = as_int(season_value)
                if season is None:
                    latest = conn.execute("SELECT season_index FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC,id DESC LIMIT 1",
                                          (career_id,)).fetchone()
                    season = int(latest["season_index"]) if latest else None
                if season is None:
                    raise ValueError("A season with imported snapshots is required.")
                resumable = _find_resumable_replay(conn, career_id, season, selected_model)
            backup_path = str(resumable.get("backup_path") or "") if resumable else ""
            backup_created = False
            if not backup_path:
                backup_path = str(self.state.database.create_backup(label="pre_commission_retroactive_reports"))
                backup_created = True
            started = start_retroactive_commission_reports(
                self.state.database, career_id, season, selected_model, selected_language, backup_path)
            self._json(started | {"season_index": season, "model": selected_model,
                                  "report_version": REPORT_VERSION, "backup_path": backup_path,
                                  "backup_created": backup_created})
            return

        match = re.fullmatch(r"/api/careers/(\d+)/commission/backfill", path)
        if match:
            career_id = int(match.group(1))
            from .commission import backfill_commission, METRIC_VERSION
            with self.state.database.connect() as conn:
                count = backfill_commission(conn, career_id)
                self._json({"ok": True, "career_id": career_id, "snapshots": count, "metric_version": METRIC_VERSION})
            return

        match = re.fullmatch(r"/api/careers/(\d+)/manual-data/season-report/save", path)
        if match:
            self._json(self.state.manual.save_season_report_note(int(match.group(1)), payload))
            return
        if path == "/api/backups/create":
            label = str(payload.get("label") or "manual").strip()
            self._json(self.state.manual.create_backup(label))
            return

        if path == "/api/media/sources":
            source_type = str(payload.get("sourceType") or "").strip()
            raw_path = str(payload.get("path") or "").strip()
            self._json(self.state.media.add_source(source_type, raw_path, recursive=input_bool(payload.get("recursive"), "Unterordner durchsuchen", default=True)))
            return
        if path == "/api/media/sources/pick":
            source_type = str(payload.get("sourceType") or "").strip()
            selected = self._pick_folder("Select EA FC media folder")
            if selected:
                source = self.state.media.add_source(source_type, selected, recursive=True)
                self._json({"ok": True, "source": source})
            else:
                self._json({"ok": False, "cancelled": True})
            return
        if path == "/api/media/sources/remove":
            source_id = as_int(payload.get("sourceId"))
            if source_id is None:
                raise ValueError("Media source ID is missing.")
            self.state.media.remove_source(source_id)
            self._json({"ok": True})
            return
        if path == "/api/media/scan":
            self._json(self.state.media.start_scan(), HTTPStatus.ACCEPTED)
            return
        if path == "/api/media/pause":
            self.state.media.pause_processing()
            self._json({"ok": True, "progress": self.state.media.progress()})
            return
        if path == "/api/media/resume":
            self.state.media.resume_processing()
            self._json({"ok": True, "progress": self.state.media.progress()})
            return
        if path == "/api/media/cancel":
            self.state.media.cancel_scan()
            self._json({"ok": True, "progress": self.state.media.progress()})
            return
        if path == "/api/media/assign":
            asset_id = as_int(payload.get("assetId")); ea_id = as_int(payload.get("eaId"))
            if asset_id is None or ea_id is None:
                raise ValueError("Media item and EA ID are required.")
            self._json(self.state.media.assign(asset_id, str(payload.get("entityType") or ""), ea_id, payload.get("mediaType")))
            return
        if path == "/api/media/competition-mappings":
            snapshot_id = as_int(payload.get("snapshotId")); competition_object_id = as_int(payload.get("competitionObjectId"))
            media_ea_id = as_int(payload.get("mediaCompetitionId"))
            if snapshot_id is None or competition_object_id is None:
                raise ValueError("Snapshot and competition object ID are required.")
            self._json(self.state.media.set_competition_mapping(snapshot_id, competition_object_id, media_ea_id))
            return
        if path == "/api/media/competition-mappings/rebuild":
            snapshot_id = as_int(payload.get("snapshotId"))
            if snapshot_id is None:
                raise ValueError("Snapshot ID is missing.")
            self._json(self.state.media.rebuild_competition_mappings(snapshot_id))
            return
        if path == "/api/reference/pick-main-db":
            selected = self._pick_file("Select EA FC main database", "Excel-Dateien (*.xlsx)|*.xlsx")
            if selected:
                self._json({"ok": True, "status": self.state.reference.import_xlsx(Path(selected))})
            else:
                self._json({"ok": False, "cancelled": True})
            return
        if path == "/api/workspaces/create":
            self._json(self.state.workspaces.create_empty(str(payload.get("name") or "")), HTTPStatus.CREATED)
            return
        if path == "/api/workspaces/clone":
            self._json(self.state.workspaces.clone_current(str(payload.get("name") or "")), HTTPStatus.CREATED)
            return
        if path == "/api/workspaces/binding/approve":
            workspace = self.state.workspaces.approve_pending_binding(str(payload.get("workspaceId") or ""))
            results = self.state.watcher.scan_once()
            self._json({"workspace": workspace, "imports": [result.__dict__ for result in results]})
            return
        if path == "/api/workspaces/binding/cancel":
            self._json(self.state.workspaces.cancel_pending_binding(str(payload.get("workspaceId") or "")))
            return
        if path == "/api/workspaces/archive":
            self._json(self.state.workspaces.set_archived(str(payload.get("workspaceId") or ""), bool(payload.get("archived", True))))
            return
        if path == "/api/workspaces/rename":
            self._json(self.state.workspaces.rename(str(payload.get("workspaceId") or ""), str(payload.get("name") or "")))
            return
        if path == "/api/workspaces/activate":
            result = self.state.workspaces.select_for_next_start(str(payload.get("workspaceId") or ""))
            self._json(result)
            if result.get("restartRequired") and bool(payload.get("restart", True)):
                self.state.shutdown_event.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/workspaces/delete":
            self._json(self.state.workspaces.delete(str(payload.get("workspaceId") or "")))
            return
        if path == "/api/settings":
            self._json(self.state.settings.save(payload))
            return
        if path == "/api/config/snapshot-root":
            raw = str(payload.get("path") or "").strip()
            if not raw:
                raise ValueError("No folder path was provided.")
            root = write_snapshot_root(raw)
            self.state.watcher.trigger()
            self._json({"ok": True, "path": str(root)})
            return
        if path == "/api/config/pick-folder":
            selected = self._pick_folder()
            if selected:
                root = write_snapshot_root(selected)
                self.state.watcher.trigger()
                self._json({"ok": True, "path": str(root)})
            else:
                self._json({"ok": False, "cancelled": True})
            return
        if path == "/api/import/scan":
            results = self.state.watcher.scan_once()
            self._json([result.__dict__ for result in results])
            return
        if path == "/api/shutdown":
            self._json({"ok": True})
            self.state.shutdown_event.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._json({"error": f"API endpoint not found: {self.command} {path}"}, 404)

    @staticmethod
    def _pick_folder(description: str = "Select snapshot root folder") -> str | None:
        if os.name != "nt":
            return None
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description='" + description.replace("'", "''") + "'; $d.ShowNewFolderButton=$true; "
            "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Write-Output $d.SelectedPath}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        return result.stdout.strip() or None

    @staticmethod
    def _pick_file(title: str, file_filter: str) -> str | None:
        if os.name != "nt":
            return None
        safe_title = title.replace("'", "''")
        safe_filter = file_filter.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d=New-Object System.Windows.Forms.OpenFileDialog; "
            f"$d.Title='{safe_title}'; $d.Filter='{safe_filter}'; $d.Multiselect=$false; "
            "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Write-Output $d.FileName}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
        return result.stdout.strip() or None

    def _serve_media(self, asset_id: int, kind: str) -> None:
        path, content_type = self.state.media.file_path(asset_id, kind)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        requested = "index.html" if path in ("/", "") else path.lstrip("/")
        candidate = (self.state.static_dir / requested).resolve()
        static_root = self.state.static_dir.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self.send_error(403)
            return
        if not candidate.is_file():
            candidate = self.state.static_dir / "index.html"
        data = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix == ".js":
            content_type = "application/javascript"
        self.send_response(200)
        self.send_header(
            "Content-Type",
            content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type == "application/javascript" else ""),
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if requested.startswith("flags/") else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def _json(self, payload: Any, status: int | HTTPStatus = 200) -> None:
        career_id = None
        career_match = re.search(r"/api/careers/(\d+)", self.path)
        if career_match:
            career_id = int(career_match.group(1))
        else:
            snapshot_match = re.search(r"/api/snapshots/(\d+)", self.path)
            if snapshot_match:
                with self.state.database.connect() as conn:
                    row = conn.execute("SELECT career_id FROM snapshots WHERE id=?", (int(snapshot_match.group(1)),)).fetchone()
                    career_id = int(row["career_id"]) if row else None
        snapshot_id = None
        snapshot_match = re.search(r"/api/snapshots/(\d+)", self.path)
        if snapshot_match:
            snapshot_id = int(snapshot_match.group(1))
        else:
            query = parse_qs(urlparse(self.path).query)
            snapshot_id = as_int((query.get("snapshot_id") or query.get("snapshotId") or [None])[0])
        payload = self.state.club_names.apply_payload(payload, career_id)
        payload = self.state.settings.apply_payload(payload, career_id=career_id, snapshot_id=snapshot_id)
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class AtlasHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: AppState):
        super().__init__(address, ApiHandler)
        self.state = state
        self._atlas_serve_started = threading.Event()
        self._atlas_serve_finished = threading.Event()
        self._atlas_shutdown_requested = threading.Event()

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        # A few lightweight contract tests can finish before their freshly spawned
        # server thread is scheduled. Remember an early shutdown request so such a
        # thread exits immediately instead of entering an orphaned serve loop.
        self._atlas_serve_started.set()
        if self._atlas_shutdown_requested.is_set():
            self._atlas_serve_finished.set()
            return
        try:
            super().serve_forever(poll_interval=poll_interval)
        finally:
            self._atlas_serve_finished.set()

    def shutdown(self) -> None:
        self._atlas_shutdown_requested.set()
        if not self._atlas_serve_started.wait(timeout=1.0):
            return
        if self._atlas_serve_finished.is_set():
            return

        # ``socketserver.BaseServer.shutdown`` waits without a timeout. A bounded
        # wait keeps application shutdown and short-lived integration tests from
        # deadlocking if the serve loop is still starting or has failed unusually.
        setattr(self, "_BaseServer__shutdown_request", True)
        stopped = getattr(self, "_BaseServer__is_shut_down", None)
        if stopped is not None:
            stopped.wait(timeout=5.0)
