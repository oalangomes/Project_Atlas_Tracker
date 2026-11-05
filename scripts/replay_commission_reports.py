r"""Launch and monitor the Atlas retrospective Technical Commission, using Atlas's API.

Windows:
    py -3 -m scripts.replay_commission_reports
    py -3 -m scripts.replay_commission_reports --list
    py -3 -m scripts.replay_commission_reports --career-id 1 --season-index 0 --yes
    py -3 -m scripts.replay_commission_reports --career-id 1 --job-id <job_id>
    py -3 -m scripts.replay_commission_reports --career-id 1 --season-index 0 --yes --audit-db C:\path\atlas_tracker.sqlite3 --output replay-result.json

Start Atlas first (default local address http://127.0.0.1:8765).
The Atlas server handles ordered replay, caching and resume.
This program does not touch the FC26 save or write directly to SQLite.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.audit_commission_reports import audit_database


FINISHED = {"complete", "complete_with_warnings", "failed", "paused", "paused_offline"}
RUNNING = {"queued", "running"}


class ReplayError(RuntimeError):
    """Clear error for a launcher or local API failure."""


def validate_base_url(value: str) -> str:
    """Constrain the replay launcher to a local Atlas instance only."""
    parsed = urlsplit(value.strip().rstrip("/"))
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ReplayError("Use a local Atlas URL only, e.g. http://127.0.0.1:8765.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ReplayError("Invalid local Atlas port.") from exc
    if port is None or not 1 <= port <= 65535:
        raise ReplayError("Specify the local Atlas port, e.g. http://127.0.0.1:8765.")
    return value.strip().rstrip("/")


@dataclass
class AtlasAPI:
    base_url: str = "http://127.0.0.1:8765"
    timeout: float = 20.0
    start_timeout: float = 600.0

    def __post_init__(self) -> None:
        self.base_url = validate_base_url(self.base_url)

    def request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/api/") or "?" in path or "#" in path:
            raise ReplayError("Invalid Atlas API path.")
        method = "GET" if payload is None else "POST"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            # Task planning on a large workspace can take longer than a status GET.
            # A timeout must never encourage an ambiguous second start request.
            request_timeout = self.start_timeout if payload is not None else self.timeout
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                details = json.loads(exc.read().decode("utf-8")).get("error", "")
            except (ValueError, UnicodeError, OSError):
                details = ""
            raise ReplayError(f"Atlas HTTP {exc.code}: {details or exc.reason}") from exc
        except (OSError, TimeoutError, ValueError) as exc:
            if payload is not None and "timed out" in str(exc).lower():
                raise ReplayError("Atlas start timed out. The replay may still have started; "
                                  "check the job in Atlas before sending another start request.") from exc
            raise ReplayError(f"Cannot reach a valid local Atlas API at {self.base_url}: {exc}") from exc
        if isinstance(parsed, dict) and parsed.get("error"):
            raise ReplayError(str(parsed["error"]))
        return parsed


def seasons_from_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read exact database season_index; display labels are for humans only."""
    by_index: dict[int, dict[str, Any]] = {}
    for snapshot in snapshots:
        try:
            season_index = int(snapshot["season_index"])
        except (ValueError, TypeError, KeyError):
            continue
        season = by_index.setdefault(
            season_index, {"index": season_index, "label": "",
                           "count": 0, "latest_date": "", "latest_sequence": -1},
        )
        season["count"] += 1
        order = int(snapshot.get("import_sequence") or 0)
        if order >= season["latest_sequence"]:
            season["latest_sequence"] = order
            season["label"] = str(snapshot.get("season_label") or f"Índice {season_index}")
            season["latest_date"] = str(snapshot.get("career_date") or "")
    return sorted(by_index.values(), key=lambda item: item["index"], reverse=True)


def choose_number(options: list[dict[str, Any]], key: str, label: str,
                  preselected: int | None, interactive: bool) -> dict[str, Any]:
    if not options:
        raise ReplayError(f"No {label} records found in this Atlas instance.")
    if preselected is not None:
        chosen = next((item for item in options if int(item[key]) == preselected), None)
        if chosen is None:
            raise ReplayError(f"{label} ID/index {preselected} not found in the local Atlas.")
        return chosen
    if not interactive:
        raise ReplayError(f"Select {label} explicitly for automated runs.")
    print(f"\nSelecione {label}:")
    for index, option in enumerate(options, 1):
        print(f"  {index}. {option.get('label', str(option[key]))} [{key}={option[key]}]")
    raw = input("Número da opção (Enter cancela): ").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= len(options):
        raise ReplayError("Selection cancelled or invalid.")
    return options[int(raw) - 1]


def career_options(careers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in careers:
        latest = item.get("latestSnapshot") or {}
        result.append({
            "id": int(item["id"]),
            "label": (str(item.get("display_name") or "Carreira")
                      + " · " + str(latest.get("managed_team_name") or "clube não identificado")
                      + f" · {int(item.get('snapshot_count') or 0)} snapshots"),
            "team": str(latest.get("managed_team_name") or ""),
        })
    return result


def job_path(career_id: int, job_id: str) -> str:
    if len(job_id) != 32 or any(ch not in "0123456789abcdef" for ch in job_id.lower()):
        raise ReplayError("Job ID inválido: esperado identificador hexadecimal de 32 caracteres.")
    return f"/api/careers/{career_id}/commission/retroactive-report-jobs/{job_id.lower()}"


def watch_job(api: AtlasAPI, career_id: int, job_id: str, poll_seconds: float = 3.0,
              sleeper: Any = time.sleep, printer: Any = print) -> dict[str, Any]:
    """Poll without starting/restarting work; Ctrl+C never cancels the server task."""
    path = job_path(career_id, job_id)
    previous = None
    last_update = 0.0
    while True:
        data = api.request(path)
        if not isinstance(data, dict):
            raise ReplayError("Unexpected job response from Atlas.")
        status = str(data.get("status") or "unknown")
        signature = (status, data.get("completed_tasks"), data.get("current_task"),
                     data.get("failed"), data.get("review_required"))
        now = time.monotonic()
        if signature != previous or now - last_update >= 30:
            total = int(data.get("total_tasks") or 0)
            completed = int(data.get("completed_tasks") or 0)
            percent = round(100 * completed / total, 1) if total else 100.0
            printer(f"[{status}] {completed}/{total} ({percent:.1f}%) | "
                    f"gerados {data.get('generated', 0)} | reutilizados {data.get('reused', 0)} | "
                    f"revisão {data.get('review_required', 0)} | falhas {data.get('failed', 0)} | "
                    f"sem dados {data.get('skipped_missing_data', 0)}")
            if data.get("current_task"):
                printer(f"  Etapa: {str(data['current_task'])[:180]}")
            previous = signature
            last_update = now
        if status in FINISHED:
            return data
        if status not in RUNNING:
            raise ReplayError(f"Unknown replay state from Atlas: {status}")
        sleeper(max(1.0, poll_seconds))


def write_result(path: Path | None, result: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")
    print(f"Relatório de execução: {path.resolve()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disparar e acompanhar os relatórios retroativos do Atlas.")
    parser.add_argument("--url", default="http://127.0.0.1:8765",
                        help="Instância local Atlas (padrão: http://127.0.0.1:8765)")
    parser.add_argument("--list", action="store_true",
                        help="Listar carreiras e índices de temporada sem iniciar nada")
    parser.add_argument("--career-id", type=int, help="ID da carreira do Atlas; obrigatório com --yes")
    parser.add_argument("--season-index", type=int, help="Índice interno exato da temporada")
    parser.add_argument("--job-id", help="Apenas acompanhar um replay existente; nunca inicia outro")
    parser.add_argument("--yes", action="store_true", help="Confirmar disparo não-interativo")
    parser.add_argument("--dry-run", action="store_true", help="Pré-visualizar seleção sem POST")
    parser.add_argument("--no-watch", action="store_true", help="Disparar e imprimir job ID sem aguardar")
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--http-timeout", type=float, default=20.0)
    parser.add_argument("--audit-db", type=Path,
                        help="Auditar relatórios depois do replay (arquivo SQLite desta mesma carreira/workspace)")
    parser.add_argument("--output", type=Path, help="Gravar resumo estruturado JSON")
    args = parser.parse_args(argv)
    if args.audit_db and args.no_watch:
        parser.error("--audit-db requer acompanhamento; remova --no-watch.")
    if args.job_id and args.season_index is not None:
        parser.error("--season-index não é usado ao acompanhar --job-id.")
    if args.job_id and args.dry_run:
        parser.error("--dry-run não é usado ao acompanhar --job-id.")
    if args.yes and args.career_id is None:
        parser.error("--career-id é obrigatório com --yes para evitar outra carreira.")
    if args.yes and args.season_index is None and not args.job_id:
        parser.error("--season-index é obrigatório com --yes para evitar outra temporada.")

    api = AtlasAPI(args.url, max(5.0, min(args.http_timeout, 60.0)))
    if args.list:
        options = career_options(api.request("/api/careers"))
        if not options:
            print("Nenhuma carreira cadastrada neste Atlas.")
            return 0
        for item in options:
            print(f"{item['label']} (career_id={item['id']})")
            seasons = seasons_from_snapshots(api.request(f"/api/careers/{item['id']}/snapshots"))
            for season in seasons:
                print(f"  season_index={season['index']} | {season['label']} | "
                      f"{season['count']} snapshots | data {season['latest_date']}")
        return 0

    if args.job_id:
        if args.career_id is None:
            raise ReplayError("Informe --career-id para acompanhar um job existente.")
        chosen_id = args.career_id
        # Validate against currently selected workspace, without creating a new replay.
        api.request(f"/api/careers/{chosen_id}")
        job_id = args.job_id.lower()
        job_path(chosen_id, job_id)
        result = {"job_id": job_id, "career_id": chosen_id, "operation": "monitor"}
    else:
        careers = career_options(api.request("/api/careers"))
        career = choose_number(careers, "id", "carreira", args.career_id, not args.yes)
        chosen_id = career["id"]
        seasons = seasons_from_snapshots(api.request(f"/api/careers/{chosen_id}/snapshots"))
        if args.season_index is None and args.dry_run and seasons:
            season = seasons[0]
        else:
            season = choose_number(seasons, "index", "temporada", args.season_index, not args.yes)
        print(f"\nCarreira: {career['label']}\nTemporada: {season['label']} "
              f"(season_index={season['index']}, snapshots={season['count']})")
        if args.dry_run:
            print("Pré-visualização concluída. Nenhuma chamada de geração ou escrita executada.")
            return 0
        if not args.yes:
            confirmation = input("Digite GERAR para iniciar o replay: ").strip()
            if confirmation != "GERAR":
                print("Cancelado, sem iniciar o replay.")
                return 0
        started = api.request(
            f"/api/careers/{chosen_id}/commission/retroactive-report-jobs",
            {"season_index": season["index"]},
        )
        if not isinstance(started, dict) or not started.get("job_id"):
            raise ReplayError("Atlas did not return a replay job ID.")
        job_id = str(started["job_id"]).lower()
        job_path(chosen_id, job_id)
        print(f"\nReplay iniciado: {job_id} | contrato v{started.get('report_version', '?')} | "
              f"modelo {started.get('model', '?')}")
        if started.get("backup_path"):
            print(f"Backup preexistente associado ao job: {started['backup_path']}")
        else:
            print("Nenhum backup automático criado.")
        print(f"Retomar acompanhamento: py -3 -m scripts.replay_commission_reports "
              f"--career-id {chosen_id} --job-id {job_id}")
        result = {"job_id": job_id, "career_id": chosen_id, "season_index": season["index"],
                  "operation": "started", "started": started}

    if args.no_watch:
        write_result(args.output, result)
        return 0
    try:
        final = watch_job(api, chosen_id, job_id, args.poll_seconds)
    except KeyboardInterrupt:
        print(f"\nAcompanhamento interrompido. O job CONTINUA no servidor Atlas: {job_id}")
        print(f"Retome com: py -3 -m scripts.replay_commission_reports "
              f"--career-id {chosen_id} --job-id {job_id}")
        write_result(args.output, result | {"status": "monitor_detached"})
        return 130
    result["final"] = final
    if final.get("errors"):
        print("\nErros registrados pelo Atlas (primeiros 5):")
        for error in final["errors"][:5]:
            print(f"  {error}")
    print(f"\nStatus final: {final.get('status')} | "
          f"gerados={final.get('generated', 0)}, reutilizados={final.get('reused', 0)}, "
          f"revisão={final.get('review_required', 0)}")

    if args.audit_db:
        quality = audit_database(args.audit_db, career_id=chosen_id, limit=50000)
        result["audit"] = quality
        print("\nAuditoria dos relatórios salvos:")
        print(f"  {quality.get('scanned', 0)} relatórios examinados; flags: "
              f"{json.dumps(quality.get('flags', {}), ensure_ascii=False)}")
        if not quality.get("scanned"):
            print("  ATENÇÃO: nenhum relatório desta carreira encontrado no banco indicado.")
    write_result(args.output, result)
    # Warnings must not be silently reported as a clean run.
    return 0 if final.get("status") == "complete" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReplayError, FileNotFoundError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
