"""Deterministic Markdown presentation for monthly_reports structured data."""
from __future__ import annotations

from typing import Any


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/d"
    if isinstance(value, float):
        return f"{value:.{digits}f}".replace(".", ",")
    return str(value)


def _clean(value: Any) -> str:
    return str(value or "n/d").replace("|", "\\|").replace("\n", " ")


def _delta(value: Any, suffix: str = "") -> str:
    return "n/d" if value is None else f"{value:+g}".replace(".", ",") + suffix


def _metric(stats: dict[str, Any] | None, field: str) -> str:
    return _fmt(stats.get(field)) if stats else "n/d"


def _performance_context(item: dict[str, Any] | None) -> str:
    if not item:
        return "n/d"
    return ("{} contra {} ({}, {}–{}), nota {} em {} min".format(
        _fmt(item.get("date")), _clean(item.get("opponent")),
        _clean(item.get("competition")), _fmt(item.get("goalsFor")),
        _fmt(item.get("goalsAgainst")), _fmt(item.get("rating")),
        _fmt(item.get("minutes"))))


def _player_evaluation(player: dict[str, Any]) -> str:
    mins = player["minutes"]
    if mins is None:
        return "Sem minutagem verificável neste mês; avaliação de campo n/d."
    if mins == 0:
        return "Sem atuação rastreada neste mês; avaliação de campo n/d."
    parts = [f"{mins} min rastreados em {player['matchesWithMinutes']} jogo(s)"]
    if player["averageRating"] is not None:
        parts.append(f"nota {_fmt(player['averageRating'])} em {player['matchesWithRating']} jogo(s) com nota")
    if player["detailedMatches"]:
        role = player["role"]
        relevant = {"GK": ("saves", "goals_conceded"),
                    "DEF": ("tackles", "interceptions"),
                    "MID": ("passes", "key_passes"),
                    "ATT": ("npk_goals", "npk_expected_goals", "key_passes")}[role]
        labels = {"saves": "defesas", "goals_conceded": "gols sofridos", "tackles": "desarmes",
                  "interceptions": "interceptações", "passes": "passes", "key_passes": "passes-chave",
                  "npk_goals": "gols sem pênaltis no export", "npk_expected_goals": "NPK-xG"}
        measures = [f"{labels[field]} {_fmt(player['detailedStats'][field])}"
                    for field in relevant if player["detailedStats"].get(field) is not None]
        if measures:
            parts.append(f"{', '.join(measures)} em {player['detailedMatches']} export(s)")
    parts.append(player["sample"].lower())
    return "; ".join(parts) + "."


def _sporting_judgment(player: dict[str, Any]) -> str:
    minutes = player["minutes"]
    if minutes is None or minutes == 0:
        return "Sem evidência de campo suficiente para avaliar o mês."
    parts = []
    if minutes < 300 or player["matchesWithRating"] < 3:
        parts.append("Amostra curta; a nota e as taxas não sustentam conclusão firme")
    else:
        parts.append("Amostra de minutos e notas utilizável para comparação mensal")
    comparison = player["comparison"] or {}
    rating_delta = comparison.get("ratingDelta")
    minutes_delta = comparison.get("minutesDelta")
    if rating_delta is not None:
        parts.append("nota média {} frente ao mês anterior".format(
            ("subiu " + _delta(rating_delta)) if rating_delta > 0 else
            ("caiu " + _delta(rating_delta)) if rating_delta < 0 else "ficou estável"))
    if minutes_delta is not None:
        parts.append("uso rastreado {}".format(
            ("aumentou " + _delta(minutes_delta) + " min") if minutes_delta > 0 else
            ("diminuiu " + _delta(minutes_delta) + " min") if minutes_delta < 0 else "ficou estável"))
    stats = player["detailedStats"]
    if player["detailedMatches"]:
        if player["role"] == "GK" and stats.get("saves") is not None:
            parts.append("as {} defesas referem-se somente aos {} jogos exportados".format(
                _fmt(stats["saves"]), player["detailedMatches"]))
        elif player["role"] == "DEF" and stats.get("tackles") is not None:
            parts.append("{} desarmes rastreados descrevem volume, não eficiência defensiva isolada".format(
                _fmt(stats["tackles"])))
        elif player["role"] == "MID" and stats.get("key_passes") is not None:
            parts.append("{} passes-chave rastreados indicam participação na criação no recorte coberto".format(
                _fmt(stats["key_passes"])))
        elif player["role"] == "ATT" and stats.get("npk_expected_goals") is not None:
            parts.append("NPK-xG de {} mede chances sem pênaltis apenas nos jogos exportados".format(
                _fmt(stats["npk_expected_goals"])))
    sentence = "; ".join(parts)
    return sentence[:1].upper() + sentence[1:] + "."


def _five_findings(month: dict[str, Any], previous: dict[str, Any] | None) -> list[str]:
    games = month["matches"]
    findings = [f"Campanha: {len(games)} partidas, {_fmt(month['goalsFor'])} gol(s) pró e "
                f"{_fmt(month['goalsAgainst'])} contra; {_fmt(month['pointsPct'])}% dos pontos possíveis "
                f"em {month['resultCoverage']} jogo(s) com placar."]
    if previous and all(x is not None for x in (month["goalsFor"], month["goalsAgainst"],
                                                  previous["goalsFor"], previous["goalsAgainst"],
                                                  month["pointsPct"], previous["pointsPct"])):
        findings.append(f"Frente a {previous['month']}: saldo de gols "
                        f"{_delta((month['goalsFor'] - month['goalsAgainst']) - (previous['goalsFor'] - previous['goalsAgainst']))}, "
                        f"aproveitamento {_delta(month['pointsPct'] - previous['pointsPct'], ' p.p.')} "
                        f"({len(games)} contra {len(previous['matches'])} jogos).")
    elif previous:
        findings.append(f"Frente a {previous['month']}: comparação de placar n/d por cobertura incompleta.")
    else:
        findings.append("Primeiro mês registrado: não há comparação mensal anterior na temporada selecionada.")
    findings.append(f"Cobertura detalhada: {month['exports']}/{len(games)} partidas com MatchStats vinculado; "
                    "métricas avançadas só descrevem esse subconjunto.")
    ranked = sorted((p for p in month["players"] if p["minutes"] is not None),
                    key=lambda p: (p["minutes"], p["name"]), reverse=True)
    if ranked:
        top = ranked[0]
        findings.append(f"Maior uso rastreado: {top['name']}, {top['minutes']} min "
                        f"em {top['matchesWithMinutes']} jogos com minutagem.")
    else:
        findings.append("Uso individual: sem minutagem rastreável no mês.")
    rated = sorted((p for p in month["players"] if p["averageRating"] is not None and
                    p["minutes"] is not None and p["minutes"] >= 300 and p["matchesWithRating"] >= 3),
                   key=lambda p: (p["averageRating"], p["minutes"]), reverse=True)
    if rated:
        p = rated[0]
        findings.append(f"Melhor média entre amostras de pelo menos 300 min e três notas: "
                        f"{p['name']}, {_fmt(p['averageRating'])} em {p['matchesWithRating']} jogos com nota.")
    else:
        findings.append("Nenhum atleta atingiu simultaneamente 300 min e três notas neste mês; "
                        "ranking individual de nota indisponível.")
    return findings


def render_month(report: dict[str, Any], month: dict[str, Any],
                 previous: dict[str, Any] | None = None,
                 navigation: bool = True) -> str:
    games = month["matches"]
    lines = [f"# Relatório mensal — {report['teamName']} — {month['month']}", "",
             f"**Carreira:** `{report['careerFingerprint']}` (ID {report['careerId']}) · "
             f"**temporada:** {report['seasonIndex']} · **snapshot:** {report['snapshotId']} "
             f"({report['snapshotCareerDate']}) · **período:** {month['month']} "
             f"{'(parcial)' if month['partial'] else '(completo até o snapshot)'}.", ""]
    if navigation:
        lines += ["[Índice](README.md) · [Consolidado](temporada.md)", ""]
    lines += ["## Resumo executivo", "",
             f"{len(games)} partidas; {_fmt(month['goalsFor'])} gols pró, {_fmt(month['goalsAgainst'])} contra; "
             f"{_fmt(month['pointsPct'])}% dos pontos possíveis nos resultados registrados. "
             f"Liga: {_fmt(month['pointsLeague'])} ponto(s).", "",
             "| Competição | J | V | E | D |", "|---|---:|---:|---:|---:|"]
    for comp, record in month["competitions"].items():
        lines.append(f"| {_clean(comp)} | {record['matches']} | {record['wins']} | {record['draws']} | {record['losses']} |")
    lines += ["", "### Cinco conclusões sustentadas por dados", ""]
    lines += [f"{i}. {finding}" for i, finding in enumerate(_five_findings(month, previous), 1)]
    lines += ["", "## Partidas", "",
              "| Data | Adversário (liga) | Competição | Mando | Placar | xG / xGA* | NPK-xG / NPK-xGA | Finalizações | Passes | Destaques com nota | Export |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for game in games:
        stats = game["teamStats"]
        opp = game["opponentStats"]
        score = f"{_fmt(game['goalsFor'])}–{_fmt(game['goalsAgainst'])} ({game['result']})"
        standouts = ", ".join(f"{p['name']} {_fmt(p['rating'])} ({_fmt(p['minutes'])} min)"
                              for p in game["standouts"][:2]) or "n/d"
        lines.append(f"| {game['date']} | {_clean(game['opponent'])} ({_clean(game['opponentLeague'])}) | {_clean(game['competition'])} | {game['venue']} | {score} | "
                     f"{_metric(stats, 'expected_goals_derived')} / {_metric(opp, 'expected_goals_derived')} | "
                     f"{_metric(stats, 'npk_expected_goals')} / {_metric(opp, 'npk_expected_goals')} | "
                     f"{_metric(stats, 'shots')} | {_metric(stats, 'passes')} | {_clean(standouts)} | {_fmt(game['exportId'])} |")
    lines += ["", "* xG total é derivado pelo Atlas de NPK-xG + 0,7 × pênaltis cometidos pelo adversário "
              "quando o contexto de pênalti está disponível; NPK-xG exclui pênaltis. Posse percentual "
              "não está disponível neste export validado. Placar e campanha vêm dos fixtures; dados avançados "
              "vêm apenas dos exports vinculados. A liga do adversário é o cadastro no snapshot selecionado; "
              "nível superior significa divisão numericamente menor que a do clube no mesmo snapshot. "
              "Resultados de competições distintas exigem leitura contextual.", "",
              "## Evolução individual — todos os atletas vinculados à temporada", "",
              "GER e potencial são cadastro do snapshot de estado indicado abaixo; não são medida de atuação. "
              "`n/d` significa ausência de observação confiável, e zero significa contagem observada igual a zero.", ""]
    ordered_players = sorted(month["players"], key=lambda p: (p["category"], p["name"].casefold()))
    lines += ["| Atleta (EA ID) | Vínculo | Idade | Posição | GER (Δ) | Potencial | Min | Nota (n) | Exports | Avaliação |",
              "|---|---|---:|---|---|---:|---:|---|---:|---|"]
    for p in ordered_players:
        comp = p["comparison"] or {}
        assessment = ("Amostra insuficiente" if p["minutes"] is not None and p["minutes"] < 300
                      else "Sem atuação rastreada; rendimento n/d" if p["minutes"] is None
                      else "Ver análise abaixo")
        lines.append(f"| {_clean(p['name'])} ({p['playerEaId']}) | {p['category']} | {_fmt(p['age'])} | "
                     f"{_fmt(p['position'])} | {_fmt(p['overall'])} ({_delta(comp.get('overallDelta'))}) | "
                     f"{_fmt(p['potential'])} | {_fmt(p['minutes'])} | "
                     f"{_fmt(p['averageRating'])} ({p['matchesWithRating']}) | {p['detailedMatches']} | {assessment} |")
    lines += ["", "### Análises dos atletas com atuação observada", ""]
    for p in (p for p in ordered_players if p["minutes"] is not None or p["matchesWithRating"]):
        comp = p["comparison"] or {}
        lines += [f"### {_clean(p['name'])} (EA {p['playerEaId']})", "",
                  f"**Vínculo:** {p['category']} · **idade:** {_fmt(p['age'])} · "
                  f"**posição natural:** {_fmt(p['position'])} · **GER:** {_fmt(p['overall'])} "
                  f"(Δ {_delta(comp.get('overallDelta'))}) · **potencial:** {_fmt(p['potential'])}.", "",
                  f"**Atuação:** {_player_evaluation(p)} "
                  f"Comparação mensal de minutos: {_delta(comp.get('minutesDelta'))}; "
                  f"de nota: {_delta(comp.get('ratingDelta'))}. "
                  f"Melhor atuação com nota: {_performance_context(p['best'])}; "
                  f"pior: {_performance_context(p['worst'])}.", "",
                  f"**Leitura esportiva:** {_sporting_judgment(p)}", "",
                  f"**Cobertura:** {p['detailedMatches']} export(s), {p['matchesWithRating']} nota(s), "
                  f"{p['matchesWithMinutes']} partida(s) com minutos; posições jogadas confirmadas: "
                  f"{', '.join(p['observedPositions']) if p['observedPositions'] else 'n/d'}. "
                  f"Gols/assistências por delta oficial de partida: "
                  f"{_fmt(p['reconstructed']['goals']) + '/' + _fmt(p['reconstructed']['assists']) if p['reconstructed'] else 'n/d'} "
                  f"em {p['reconstructedMatches']} jogo(s) reconstruível(is).", ""]
        if p["detailedMatches"]:
            metrics = ", ".join(f"{key} {_fmt(value)} ({p['detailedCoverage'].get(key, 0)}/{p['detailedMatches']})"
                                for key, value in p["detailedStats"].items() if value is not None)
            rates = ", ".join("{} {}".format(key, _fmt(value)) for key, value in p["per90"].items())
            lines += [f"**Indicadores rastreados:** {metrics or 'n/d'}. "
                      f"Por 90 min do export: {rates or 'n/d'}.", ""]
    lines += ["## Setores e desenvolvimento", ""]
    sectors = (("Goleiros", lambda p: p["position"] == "GK"),
               ("Laterais", lambda p: p["position"] in {"LB", "RB", "LWB", "RWB"}),
               ("Zagueiros", lambda p: p["position"] in {"CB", "LCB", "RCB", "SW"}),
               ("Volantes e meias centrais", lambda p: p["position"] in {"CDM", "CM"}),
               ("Meias ofensivos e pontas", lambda p: p["position"] in {"CAM", "LM", "RM", "LW", "RW"}),
               ("Centroavantes", lambda p: p["position"] in {"ST", "CF"}))
    for label, predicate in sectors:
        group = [p for p in month["players"] if predicate(p) and p["category"] != "academia"]
        active = sorted((p for p in group if p["minutes"]), key=lambda p: p["minutes"], reverse=True)
        used = ", ".join("{} ({} min)".format(p["name"], p["minutes"]) for p in active[:3])
        lines += [f"### {label}", "",
                  f"{len(group)} atletas vinculados; {len(active)} com minutos rastreados. "
                  f"Maior utilização: {used or 'n/d'}. "
                  "Profundidade e hierarquia dependem também de escalações e disponibilidade não cobertas integralmente.", ""]
    academy = [p for p in month["players"] if p["category"].startswith("academia")]
    lines += ["### Academia e desenvolvimento", "", f"{len(academy)} jovens cadastrados no estado do mês. "
              "Sem partidas profissionais rastreadas, evolução de campo permanece n/d.", "",
              "## Adversários superiores, mercado e planejamento", "",
              "Adversário de divisão superior é identificado pelo nível de liga cadastrado no snapshot. "
              "Cardiff, quando presente, é da mesma divisão no snapshot selecionado e aparece no recorte "
              "de partidas, sem ser classificado como superior. Vitórias coletivas não são atribuídas "
              "individualmente sem atuação rastreada.", ""]
    superior = [game for game in games if game["superior"]]
    if superior:
        for game in superior:
            used = [(p["name"], row) for p in month["players"]
                    for row in p["superiorOpponents"] if row["fixtureId"] == game["fixtureId"]]
            used_text = ", ".join("{} {} min / nota {}".format(name, _fmt(row["minutes"]),
                                                                   _fmt(row["rating"])) for name, row in used)
            lines += [f"- {game['date']} — {game['opponent']} ({game['opponentLeague']}): "
                      f"{len(used)} atletas com atuação rastreada; "
                      f"{used_text or 'detalhe individual n/d'}."]
    else:
        lines.append("- Nenhum adversário com divisão superior verificável neste mês.")
    changes = month["rosterChanges"]
    if changes is not None:
        names = {p["playerEaId"]: p["name"] for p in month["players"]}
        added = ", ".join(names.get(pid, "EA {}".format(pid)) for pid in changes["added"])
        removed = ", ".join(names.get(pid, "EA {}".format(pid)) for pid in changes["removed"])
        lines += [f"**Mudança no elenco entre snapshots de fechamento:** entradas no cadastro: "
                  f"{added or 'nenhuma'}; saídas do cadastro: {removed or 'nenhuma'}.", ""]
    lines += ["Movimentos confirmados por evento de mercado: n/d nesta camada; mudança cadastral "
              "sozinha não confirma negociação. Intenções e recomendações específicas dependem de "
              "contexto adicional verificado.", "",
              "## Qualidade dos dados", "",
              f"- {len(games)} fixtures únicos concluídos; {month['resultCoverage']} com placar; "
              f"{month['exports']} com export completo vinculado; {len(games) - month['exports']} sem ele.",
              f"- Cobertura por indicador coletivo, com os dois lados presentes: xG total "
              f"{month['metricCoverage']['expected_goals_derived']}/{len(games)}, NPK-xG "
              f"{month['metricCoverage']['npk_expected_goals']}/{len(games)}, finalizações "
              f"{month['metricCoverage']['shots']}/{len(games)}, passes "
              f"{month['metricCoverage']['passes']}/{len(games)}.",
              f"- Estado cadastral dos jogadores: snapshot {month['snapshotIdForPlayerState']}; "
              f"recorte de partidas e elegibilidade de export: snapshot {report['snapshotId']}.",
              "- Aparições oficiais acumuladas não foram distribuídas por mês. Deltas oficiais aparecem "
              "apenas quando o Atlas conseguiu vincular exatamente uma partida entre snapshots consecutivos.",
              "- Notas e minutos de histórico e export têm cobertura distinta. Titularidade, posição jogada "
              "sem fonte confiável, ação tática causal e negociações sem confirmação permanecem n/d.", ""]
    return "\n".join(lines)


def render_season(report: dict[str, Any], *, navigation: bool = True) -> str:
    months = report["months"]
    def total(key: str) -> str:
        return _fmt(sum(m[key] for m in months)) if all(m[key] is not None for m in months) else "n/d"
    period = report.get("period")
    title = (f"Relatório de {period['startMonth']} a {period['endMonth']}" if period else "Temporada")
    lines = [f"# {title} — {report['teamName']}", "",
             f"**Carreira:** `{report['careerFingerprint']}` (ID {report['careerId']}) · "
             f"**temporada:** {report['seasonIndex']} · **snapshot:** {report['snapshotId']} "
             f"({report['snapshotCareerDate']}).", ""]
    if period and period["partial"]:
        lines += ["Período parcial no corte selecionado.", ""]
    if not months:
        return "\n".join([*lines, "Nenhuma partida concluída neste recorte.", ""])
    if navigation:
        lines += ["[Índice](README.md)", ""]
    lines += [
             "## Trajetória mensal", "",
             "| Mês | J | V-E-D | Liga pts | GF-GA | Aproveitamento | Exports |", "|---|---:|---|---:|---|---:|---:|"]
    for m in months:
        rec = [sum(c[key] for c in m["competitions"].values()) for key in ("wins", "draws", "losses")]
        month_label = f"[{m['month']}]({m['month']}.md)" if navigation else m["month"]
        lines.append(f"| {month_label}{' parcial' if m['partial'] else ''} | {len(m['matches'])} | "
                     f"{'-'.join(map(str, rec))} | {_fmt(m['pointsLeague'])} | {_fmt(m['goalsFor'])}-{_fmt(m['goalsAgainst'])} | "
                     f"{_fmt(m['pointsPct'])}% | {m['exports']}/{len(m['matches'])} |")
    lines += ["", f"**Total:** {report['fixtureCount']} partidas únicas; "
              f"{total('goalsFor')} gols pró, {total('goalsAgainst')} contra; "
              f"{total('pointsLeague')} pontos de liga recalculados dos fixtures.", "",
              "## Síntese da trajetória", ""]
    scored = [m for m in months if m["goalsFor"] is not None and m["goalsAgainst"] is not None]
    attacking = max(scored, key=lambda m: (m["goalsFor"] / len(m["matches"]), m["month"])) if scored else None
    defending = min(scored, key=lambda m: (m["goalsAgainst"] / len(m["matches"]), m["month"])) if scored else None
    lines += [f"- Melhor produção de gols por jogo: {attacking['month']}, "
              f"{_fmt(attacking['goalsFor'] / len(attacking['matches']))} em {len(attacking['matches'])} partidas."
              if attacking else "- Melhor produção de gols por jogo: n/d.",
              f"- Menos gols sofridos por jogo: {defending['month']}, "
              f"{_fmt(defending['goalsAgainst'] / len(defending['matches']))} em {len(defending['matches'])} partidas."
              if defending else "- Menos gols sofridos por jogo: n/d.",
              "- Estes são recortes de placar, não estimativas de qualidade de chances. "
              "Diferenças de calendário, adversários e competições limitam a comparação causal.", "",
              "xG e métricas individuais "
              "cobrem somente os exports vinculados de cada mês; diferenças de cobertura impedem uma série "
              "completa de qualidade de chances ou rendimento para toda a temporada.", "",
              "## Evolução de todos os jogadores", "",
              "Células: minutos rastreados / nota média (n jogos com nota) / GER cadastrado. "
              "`n/d` não é zero. O GER mensal é o último snapshot do mês disponível até o snapshot selecionado.", "",
              "| Jogador | Vínculo final | " + " | ".join(m["month"] for m in months) + " |",
              "|---|---|" + "---|" * len(months)]
    ids = sorted({p["playerEaId"] for m in months for p in m["players"]})
    for pid in ids:
        series = [next((p for p in m["players"] if p["playerEaId"] == pid), None) for m in months]
        last = next(p for p in reversed(series) if p)
        cells = [f"{_fmt(p['minutes'])} / {_fmt(p['averageRating'])} ({p['matchesWithRating']}) / {_fmt(p['overall'])}" if p else "n/d"
                 for p in series]
        lines.append(f"| {_clean(last['name'])} (EA {pid}) | {last['category']} | " + " | ".join(cells) + " |")
    lines += ["", "### Evolução, consistência e importância", ""]
    trajectories = []
    for pid in ids:
        series = [next((p for p in m["players"] if p["playerEaId"] == pid), None) for m in months]
        known = [p for p in series if p and p["overall"] is not None]
        rated = [p for p in series if p and p["averageRating"] is not None
                 and p["minutes"] is not None and p["minutes"] >= 300 and p["matchesWithRating"] >= 3]
        trajectories.append({"name": next(p["name"] for p in reversed(series) if p),
                             "overallDelta": known[-1]["overall"] - known[0]["overall"] if len(known) >= 2 else None,
                             "rated": rated, "series": series})
    growth = sorted((p for p in trajectories if p["overallDelta"] is not None and p["overallDelta"] > 0),
                    key=lambda p: (p["overallDelta"], p["name"]), reverse=True)
    lines.append("- Maiores aumentos de GER registrado: " +
                 (", ".join(f"{p['name']} +{p['overallDelta']}" for p in growth[:5]) or "n/d") +
                 ". GER é cadastro, não prova isolada de rendimento em campo.")
    consistency = sorted((p for p in trajectories if len(p["rated"]) >= 3),
                         key=lambda p: (max(x["averageRating"] for x in p["rated"]) -
                                        min(x["averageRating"] for x in p["rated"]), -len(p["rated"])))
    if consistency:
        p = consistency[0]
        lines.append(f"- Menor variação de nota mensal em pelo menos três meses com amostra útil: "
                     f"{p['name']}, amplitude {_fmt(max(x['averageRating'] for x in p['rated']) - min(x['averageRating'] for x in p['rated']))} "
                     f"em {len(p['rated'])} meses. A média depende apenas dos jogos com nota.")
    else:
        lines.append("- Consistência de nota: n/d; nenhum atleta tem três meses com pelo menos 300 min e três notas.")
    declines = sorted((p for p in trajectories if len(p["rated"]) >= 2 and
                       p["rated"][-1]["averageRating"] < p["rated"][0]["averageRating"]),
                      key=lambda p: p["rated"][-1]["averageRating"] - p["rated"][0]["averageRating"])
    lines.append("- Quedas de média entre primeiro e último mês com amostra útil: " +
                 (", ".join(f"{p['name']} {_delta(p['rated'][-1]['averageRating'] - p['rated'][0]['averageRating'])}"
                            for p in declines[:5]) or "nenhuma observável") +
                 ". A variação não comprova regressão causal.")
    first, last = months[0], months[-1]
    minutes_change = []
    for p in trajectories:
        start = p["series"][0]
        end = p["series"][-1]
        if start and end and start["minutes"] is not None and end["minutes"] is not None:
            minutes_change.append((end["minutes"] / len(last["matches"]) -
                                   start["minutes"] / len(first["matches"]), p["name"]))
    rising = sorted((item for item in minutes_change if item[0] > 0), reverse=True)[:5]
    lines.append("- Maior crescimento de minutos por partida do calendário entre primeiro e último mês: " +
                 (", ".join(f"{name} +{_fmt(change)}" for change, name in rising) or "n/d") +
                 ". É indicador de uso rastreado, não prova de titularidade.")
    lines.append("")
    lines += ["", "## Leitura por setor", ""]
    for label, role in (("Goleiros", "GK"), ("Defensores e laterais", "DEF"),
                        ("Volantes e meias centrais", "MID"), ("Meias ofensivos e atacantes", "ATT")):
        trajectory = []
        for m in months:
            active = [p for p in m["players"] if p["role"] == role and p["minutes"]]
            trajectory.append(f"{m['month']}: {len(active)} usados, {sum(p['minutes'] for p in active)} min rastreados")
        lines += [f"### {label}", "", "; ".join(trajectory) + ".", ""]
    lines += ["## Adversários de divisão superior", ""]
    superior_games = [(m, g) for m in months for g in m["matches"] if g["superior"]]
    if superior_games:
        for m, g in superior_games:
            used = [(p["name"], row) for p in m["players"] for row in p["superiorOpponents"]
                    if row["fixtureId"] == g["fixtureId"]]
            top = sorted(used, key=lambda item: item[1]["rating"] or 0, reverse=True)[:3]
            top_text = ", ".join("{} {}".format(name, _fmt(row["rating"])) for name, row in top)
            lines.append(f"- {g['date']} {g['opponent']} ({g['opponentLeague']}): "
                         f"{g['goalsFor']}–{g['goalsAgainst']}; {len(used)} atletas com atuação rastreada. "
                         f"Maior nota: {top_text or 'n/d'}.")
    else:
        lines.append("Nenhum adversário de divisão superior identificável no cadastro do snapshot.")
    lines += ["", "## Movimentos de elenco e mercado", ""]
    for m in months:
        changes = m["rosterChanges"]
        if changes and (changes["added"] or changes["removed"]):
            names = {p["playerEaId"]: p["name"] for p in m["players"]}
            added = ", ".join(names.get(pid, "EA {}".format(pid)) for pid in changes["added"])
            removed = ", ".join(names.get(pid, "EA {}".format(pid)) for pid in changes["removed"])
            lines.append(f"- {m['month']}: entradas cadastrais "
                         f"{added or 'nenhuma'}; saídas cadastrais {removed or 'nenhuma'}.")
    lines += ["", "Essas diferenças comparam os elencos nos snapshots de fechamento mensal. "
              "Não são prova de venda, contratação ou empréstimo concluído; eventos de mercado confirmados "
              "continuam n/d na fonte consultada.", ""]
    lines += ["## Qualidade, interpretação e planejamento", "",
              f"{sum(m['exports'] for m in months)}/{report['fixtureCount']} partidas têm export detalhado "
              "elegível. Partidas sem export continuam no placar, mas métricas avançadas são n/d. "
              "Ranking de evolução e consistência deve considerar amostra mensal de notas/minutos; "
              "a tabela individual permite inspecionar a trajetória sem confundir ausência com regressão.", "",
              "Transações e decisões táticas só podem ser declaradas confirmadas com eventos e observações "
              "próprios; esta versão apresenta mudança cadastral e de uso, sem atribuir causalidade. "
              "Próximo passo analítico: ampliar cobertura MatchStats, registrar escalações/posições e "
              "eventos de mercado verificáveis.", ""]
    return "\n".join(lines)


def render_index(report: dict[str, Any]) -> str:
    lines = ["# Índice dos relatórios mensais", "",
             f"**Carreira:** `{report['careerFingerprint']}` · **temporada:** {report['seasonIndex']} · "
             f"**snapshot:** {report['snapshotId']} ({report['snapshotCareerDate']}) · "
             f"**equipe:** {report['teamName']} (EA {report['teamEaId']}).", "",
             "- [Consolidado da temporada](temporada.md)"]
    lines += [f"- [{m['month']}{' — parcial' if m['partial'] else ''}]({m['month']}.md)"
              for m in report["months"]]
    lines += ["", "Fonte: SQLite do workspace Atlas, aberto em modo somente leitura. "
              "Datas são da carreira, não da importação. Consulte a seção de qualidade de cada relatório.", ""]
    return "\n".join(lines)
