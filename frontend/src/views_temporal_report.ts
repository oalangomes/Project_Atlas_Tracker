interface TemporalPlayer {
    playerEaId: number;
    name: string;
    category: string;
    position: string | null;
    overall: number | null;
    potential: number | null;
    minutes: number | null;
    matchesWithMinutes: number;
    averageRating: number | null;
    matchesWithRating: number;
    detailedMatches: number;
    detailedStats: Record<string, number | null>;
    detailedCoverage: Record<string, number>;
}

interface TemporalMatch {
    fixtureId: number;
    date: string;
    opponent: string | null;
    competition: string | null;
    venue: string;
    result: "V" | "E" | "D" | "n/d";
    goalsFor: number | null;
    goalsAgainst: number | null;
    teamStats: Record<string, number | null>;
    opponentStats: Record<string, number | null>;
    exportId: number | null;
}

interface TemporalMonth {
    month: string;
    partial: boolean;
    matches: TemporalMatch[];
    players: TemporalPlayer[];
    pointsPct: number | null;
    pointsLeague: number | null;
    goalsFor: number | null;
    goalsAgainst: number | null;
    resultCoverage: number;
    exports: number;
    metricCoverage: Record<string, number>;
}

interface TemporalReport {
    teamName: string;
    snapshotId: number;
    snapshotCareerDate: string;
    months: TemporalMonth[];
    availableMonths?: string[];
    period?: { startMonth: string; endMonth: string; partial: boolean };
}

type TemporalSelection =
    | { mode: "season" }
    | { mode: "month"; month: string }
    | { mode: "semester"; startMonth: string; endMonth: string }
    | { mode: "range"; startMonth: string; endMonth: string };

const temporalLabels = {
    title: ["Relatórios", "Reports", "Informes"],
    tab: ["Evolução temporal", "Timeline", "Evolución temporal"],
    overview: ["Visão da temporada", "Season overview", "Resumen de temporada"],
    competitions: ["Competições", "Competitions", "Competiciones"],
    squadTab: ["Elenco da temporada", "Season squad", "Plantilla de temporada"],
    transfers: ["Transferências", "Transfers", "Traspasos"],
    awards: ["Prêmios", "Awards", "Premios"],
    quality: ["Qualidade dos dados", "Data quality", "Calidad de datos"],
    scope: ["Time e elenco", "Team and squad", "Equipo y plantilla"],
    season: ["Temporada", "Season", "Temporada"],
    snapshot: ["Snapshot de corte", "Snapshot cut-off", "Snapshot de corte"],
    period: ["Recorte", "Period", "Período"],
    semester: ["Semestre", "Semester", "Semestre"],
    month: ["Mês", "Month", "Mes"],
    range: ["Período personalizado", "Custom period", "Período personalizado"],
    full: ["Toda a temporada", "Full season", "Toda la temporada"],
    start: ["De (mês inicial)", "From (first month)", "Desde (mes inicial)"],
    end: ["Até (mês final)", "To (last month)", "Hasta (mes final)"],
    apply: ["Aplicar", "Apply", "Aplicar"],
    invalid: ["O mês inicial deve ser anterior ou igual ao final.", "The first month must be on or before the last month.", "El mes inicial debe ser anterior o igual al final."],
    download: ["Baixar Markdown", "Download Markdown", "Descargar Markdown"],
    downloadError: ["Falha ao baixar Markdown", "Markdown download failed", "Error al descargar Markdown"],
    loading: ["Carregando relatório…", "Loading report…", "Cargando informe…"],
    error: ["Não foi possível carregar o relatório", "The report could not be loaded", "No se pudo cargar el informe"],
    retry: ["Tentar novamente", "Try again", "Reintentar"],
    empty: ["Nenhuma partida concluída neste recorte", "No completed matches in this period", "Sin partidos finalizados en este período"],
    emptyHelp: ["Escolha outro recorte ou snapshot de corte.", "Choose another period or snapshot.", "Elige otro período o snapshot."],
    partial: ["Período parcial até o snapshot", "Partial period as of the snapshot", "Período parcial hasta el snapshot"],
    monthPartial: ["Parcial", "Partial", "Parcial"],
    games: ["Partidas", "Matches", "Partidos"],
    results: ["Placares disponíveis", "Available results", "Marcadores disponibles"],
    record: ["V–E–D", "W–D–L", "V–E–D"],
    goals: ["Gols pró / contra", "Goals for / against", "Goles a favor / en contra"],
    league: ["Pontos na liga", "League points", "Puntos de liga"],
    rate: ["Aproveitamento", "Points won", "Aprovechamiento"],
    exports: ["Exports vinculados", "Linked exports", "Exports vinculados"],
    timeline: ["Trajetória do time", "Team timeline", "Trayectoria del equipo"],
    timelineNote: ["Meses com partidas concluídas", "Months with completed matches", "Meses con partidos finalizados"],
    coverage: ["Cobertura por partida", "Match coverage", "Cobertura por partido"],
    fixtures: ["Partidas do recorte", "Matches in this period", "Partidos del período"],
    date: ["Data", "Date", "Fecha"],
    opponent: ["Adversário", "Opponent", "Rival"],
    competition: ["Competição", "Competition", "Competición"],
    venue: ["Mando", "Venue", "Localía"],
    home: ["Casa", "Home", "Local"],
    away: ["Fora", "Away", "Visitante"],
    score: ["Placar", "Score", "Marcador"],
    shots: ["Finalizações", "Shots", "Remates"],
    passes: ["Passes", "Passes", "Pases"],
    squad: ["Evolução do elenco", "Squad development", "Evolución de la plantilla"],
    search: ["Buscar atleta", "Find a player", "Buscar jugador"],
    noPlayers: ["Nenhum atleta encontrado.", "No players found.", "No se encontraron jugadores."],
    players: ["atletas", "players", "jugadores"],
    squadNote: ["Minutos e notas cobrem as atuações registradas. O GER e o potencial vêm do último snapshot disponível de cada mês.", "Minutes and ratings cover recorded appearances. OVR and potential use the last available snapshot for each month.", "Los minutos y notas cubren actuaciones registradas. La media y el potencial usan el último snapshot disponible de cada mes."],
    playerCoverage: ["Gols e assistências indicam jogos com a métrica disponível sobre exports vinculados.", "Goals and assists show matches with the metric available out of linked exports.", "Goles y asistencias muestran partidos con la métrica disponible sobre exports vinculados."],
    minutes: ["Minutos (jogos)", "Minutes (matches)", "Minutos (partidos)"],
    rating: ["Nota média (jogos)", "Avg. rating (matches)", "Nota media (partidos)"],
    overall: ["GER", "OVR", "Media"],
    potential: ["Potencial", "Potential", "Potencial"],
    position: ["Posição natural", "Natural position", "Posición natural"],
    category: ["Vínculo", "Squad status", "Vínculo"],
    playerGoals: ["Gols s/ pênalti", "Non-penalty goals", "Goles sin penalti"],
    assists: ["Assistências", "Assists", "Asistencias"],
    available: ["Disponível", "Available", "Disponible"],
    noData: ["n/d", "n/a", "n/d"],
} as const;

function temporalText(key: keyof typeof temporalLabels): string {
    const language = atlasLanguage();
    return temporalLabels[key][language === "en-GB" ? 1 : language === "es-ES" ? 2 : 0];
}

function temporalNumber(value: number | null, digits = 0): string {
    return value == null ? temporalText("noData") : num(value, digits);
}

function temporalMonthLabel(month: string): string {
    return new Intl.DateTimeFormat(atlasLanguage(), {
        month: "short", year: "numeric", timeZone: "UTC",
    }).format(new Date(`${month}-01T00:00:00Z`));
}

function temporalSemester(month: string): Extract<TemporalSelection, { mode: "semester" }> {
    const year = month.slice(0, 4);
    const firstHalf = month.slice(5, 7) <= "06";
    return {
        mode: "semester",
        startMonth: `${year}-${firstHalf ? "01" : "07"}`,
        endMonth: `${year}-${firstHalf ? "06" : "12"}`,
    };
}

function temporalPeriodLabel(start: string, end: string): string {
    return start === end ? temporalMonthLabel(start) : `${temporalMonthLabel(start)} – ${temporalMonthLabel(end)}`;
}

function temporalOption(value: string | number, label: string, selected: string | number): string {
    return `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(label)}</option>`;
}

let temporalContext: { key: string; snapshotId: number; selection: TemporalSelection } | null = null;

async function renderTemporalSeasonReport(selected: number, isCurrent: () => boolean): Promise<void> {
    const snapshots = state.snapshots;
    const seasonSnapshots = snapshots.filter(snapshot => Number(snapshot.season_index) === selected);
    const key = `${state.careerId}:${state.snapshotId}:${selected}`;
    const context = temporalContext?.key === key ? temporalContext : null;
    const snapshot = seasonSnapshots.find(item => Number(item.id) === (context?.snapshotId ?? state.snapshotId))
        || seasonSnapshots[0] || currentSnapshot();
    if (!snapshot) return;

    const cutMonth = snapshot.career_date.slice(0, 7);
    const selection = context?.selection ?? temporalSemester(cutMonth);
    const params = new URLSearchParams({
        season_index: String(snapshot.season_index), snapshot_id: String(snapshot.id),
    });
    if (selection.mode === "month") params.set("month", selection.month);
    if (selection.mode === "semester" || selection.mode === "range") {
        params.set("start_month", selection.startMonth);
        params.set("end_month", selection.endMonth);
    }
    const url = `/api/careers/${state.careerId}/sporting-reports?${params}`;
    const setSelection = (next: TemporalSelection, snapshotId = Number(snapshot.id)) => {
        temporalContext = {key, snapshotId, selection: next};
        void render();
    };
    const shell = (subtitle: string, body: string, actions = "", periodControls = "") => {
        const seasons = [...new Map(snapshots.map(item => [Number(item.season_index), item.season_label || String(item.season_index)])).entries()];
        content.innerHTML = `<div class="content-inner wide season-report-page temporal-report">
            ${pageHead(temporalText("title"), subtitle, actions)}
            ${seasonReportTabs("temporal")}
            <form class="page-filter-bar temporal-period" data-temporal-period>
                <label class="page-filter"><span>${temporalText("season")}</span><select data-season-report-season>
                    ${seasons.map(([id, label]) => temporalOption(id, label, Number(snapshot.season_index))).join("")}
                </select></label>
                <label class="page-filter"><span>${temporalText("snapshot")}</span><select data-temporal-snapshot>
                    ${seasonSnapshots.map(item => temporalOption(Number(item.id), `${dateText(item.career_date)} · #${item.id}`, Number(snapshot.id))).join("")}
                </select></label>
                ${periodControls}
            </form>
            ${body}
        </div>`;
        const picker = content.querySelector<HTMLSelectElement>("[data-temporal-snapshot]");
        if (picker) picker.onchange = () => {
            const next = seasonSnapshots.find(item => Number(item.id) === Number(picker.value));
            if (next) setSelection(temporalSemester(next.career_date.slice(0, 7)), Number(next.id));
        };
    };
    shell(temporalText("scope"), `<p role="status" class="muted">${temporalText("loading")}</p><div class="card skeleton temporal-report-loading"></div>`);
    bindContent();
    let report: TemporalReport;
    try {
        report = await api<TemporalReport>(url);
    } catch (error) {
        if (!isCurrent()) return;
        shell(temporalText("scope"), emptyState(temporalText("error"), String(error.message),
            `<button class="button" data-temporal-retry>${temporalText("retry")}</button>`));
        const retry = content.querySelector<HTMLButtonElement>("[data-temporal-retry]");
        if (retry) retry.onclick = () => { void render(); };
        return;
    }
    if (!isCurrent()) return;
    const available = report.availableMonths ?? report.months.map(month => month.month);
    const controls = temporalControls(selection, available, cutMonth);
    const body = report.months.length ? temporalBody(report, Number(snapshot.id) === state.snapshotId)
        : emptyState(temporalText("empty"), temporalText("emptyHelp"));
    const cutNotice = report.period?.partial || report.months.some(month => month.partial)
        ? ` · ${temporalText("partial")}` : "";
    const actions = `<button class="button primary" data-temporal-export>${temporalText("download")}</button>`;
    shell(`${report.teamName} · ${dateText(report.snapshotCareerDate)}${cutNotice}`, body, actions, controls);
    bindTemporalReport(selection, available, cutMonth, setSelection, url);
}

function temporalControls(selection: TemporalSelection, months: string[], cutMonth: string): string {
    const semesters = [...new Map([...months, cutMonth].map(month => {
        const semester = temporalSemester(month);
        return [semester.startMonth, semester];
    })).values()].sort((a, b) => b.startMonth.localeCompare(a.startMonth));
    const optional = selection.mode === "semester"
        ? `<label class="page-filter"><span>${temporalText("semester")}</span><select data-temporal-semester>
            ${semesters.map(period => temporalOption(period.startMonth, temporalPeriodLabel(period.startMonth, period.endMonth), selection.startMonth)).join("")}
        </select></label>`
        : selection.mode === "month"
            ? `<label class="page-filter"><span>${temporalText("month")}</span><select data-temporal-month-picker>
                ${months.slice().reverse().map(month => temporalOption(month, temporalMonthLabel(month), selection.month)).join("")}
            </select></label>`
            : selection.mode === "range" ? `
            <label class="page-filter"><span>${temporalText("start")}</span><input name="startMonth" type="month" value="${esc(selection.startMonth)}" required></label>
            <label class="page-filter"><span>${temporalText("end")}</span><input name="endMonth" type="month" value="${esc(selection.endMonth)}" required></label>
            <button class="button" type="submit">${temporalText("apply")}</button>
            <span class="temporal-filter-error" role="alert"></span>` : "";
    return `<label class="page-filter"><span>${temporalText("period")}</span><select data-temporal-mode>
            ${temporalOption("semester", temporalText("semester"), selection.mode)}
            ${months.length ? temporalOption("month", temporalText("month"), selection.mode) : ""}
            ${temporalOption("range", temporalText("range"), selection.mode)}
            ${temporalOption("season", temporalText("full"), selection.mode)}
        </select></label>${optional}`;
}

function bindTemporalReport(selection: TemporalSelection, months: string[], cutMonth: string,
                            setSelection: (selection: TemporalSelection) => void, url: string): void {
    const mode = content.querySelector<HTMLSelectElement>("[data-temporal-mode]");
    if (mode) mode.onchange = () => {
        const latest = months.at(-1) ?? cutMonth;
        if (mode.value === "season") setSelection({mode: "season"});
        else if (mode.value === "month") setSelection({mode: "month", month: latest});
        else if (mode.value === "semester") setSelection(temporalSemester(latest));
        else {
            const startMonth = selection.mode === "semester" ? selection.startMonth : months[0] ?? latest;
            const endMonth = selection.mode === "semester" ? selection.endMonth : latest;
            setSelection({mode: "range", startMonth, endMonth});
        }
    };
    const semester = content.querySelector<HTMLSelectElement>("[data-temporal-semester]");
    if (semester) semester.onchange = () => setSelection(temporalSemester(semester.value));
    const month = content.querySelector<HTMLSelectElement>("[data-temporal-month-picker]");
    if (month) month.onchange = () => setSelection({mode: "month", month: month.value});
    $$<HTMLButtonElement>("[data-temporal-open-month]", content).forEach(button => {
        button.onclick = () => setSelection({mode: "month", month: button.dataset.temporalOpenMonth!});
    });
    const form = content.querySelector<HTMLFormElement>("[data-temporal-period]");
    if (form) form.onsubmit = event => {
        event.preventDefault();
        if (selection.mode !== "range") return;
        const data = new FormData(form);
        const startMonth = String(data.get("startMonth"));
        const endMonth = String(data.get("endMonth"));
        if (startMonth > endMonth) {
            const error = form.querySelector(".temporal-filter-error");
            if (error) error.textContent = temporalText("invalid");
        } else setSelection({mode: "range", startMonth, endMonth});
    };
    const download = content.querySelector<HTMLButtonElement>("[data-temporal-export]");
    if (download) download.onclick = async () => {
        download.disabled = true;
        try {
            const markdown = await api<{ fileName: string; content: string }>(`${url}&format=markdown`);
            if (download.isConnected) downloadText(markdown.fileName, markdown.content, "text/markdown;charset=utf-8");
        } catch (error) {
            if (download.isConnected) toast(`${temporalText("downloadError")}. ${error.message}`);
        } finally {
            download.disabled = false;
        }
    };
    const search = content.querySelector<HTMLInputElement>("[data-temporal-search]");
    if (search) search.oninput = () => {
        const normalized = (text: string) => text.toLocaleLowerCase(atlasLanguage()).normalize("NFD").replace(/\p{M}/gu, "");
        const query = normalized(search.value.trim());
        const cards = $$<HTMLElement>("[data-temporal-player]", content);
        let found = 0;
        for (const card of cards) {
            card.hidden = !normalized(card.dataset.temporalPlayer || "").includes(query);
            if (!card.hidden) found++;
        }
        const count = content.querySelector("[data-temporal-player-count]");
        if (count) count.textContent = found ? `${num(found)} / ${num(cards.length)} ${temporalText("players")}` : temporalText("noPlayers");
    };
}

function temporalRecord(matches: TemporalMatch[]): string {
    return ["V", "E", "D"].map(result => num(matches.filter(match => match.result === result).length)).join("–");
}

function temporalBody(report: TemporalReport, links: boolean): string {
    const months = report.months;
    const games = months.flatMap(month => month.matches);
    const sum = (key: "exports" | "resultCoverage") => months.reduce((total, month) => total + month[key], 0);
    const completeTotal = (key: "goalsFor" | "goalsAgainst" | "pointsLeague") =>
        months.some(month => month[key] == null) ? null : months.reduce((total, month) => total + (month[key] ?? 0), 0);
    const score = (goalsFor: number | null, goalsAgainst: number | null) =>
        `${temporalNumber(goalsFor)} / ${temporalNumber(goalsAgainst)}`;
    const period = report.period;
    const label = period ? temporalPeriodLabel(period.startMonth, period.endMonth)
        : temporalPeriodLabel(months[0].month, months.at(-1)!.month);
    const summary = `<div class="grid metrics temporal-metrics">
        ${metric(temporalText("games"), num(games.length), `${temporalRecord(games)} ${temporalText("record")}`, "green")}
        ${metric(temporalText("goals"), score(completeTotal("goalsFor"), completeTotal("goalsAgainst")),
            `${num(sum("resultCoverage"))}/${num(games.length)} ${temporalText("results").toLocaleLowerCase(atlasLanguage())}`)}
        ${metric(temporalText("league"), temporalNumber(completeTotal("pointsLeague")), "", "blue")}
        ${metric(temporalText("exports"), `${num(sum("exports"))} / ${num(games.length)}`)}
    </div>`;
    const monthlyRows = months.map(month => `<tr>
        <td><button class="entity-link" data-temporal-open-month="${esc(month.month)}">${esc(temporalMonthLabel(month.month))}</button>
            ${month.partial ? `<small class="table-subline">${temporalText("monthPartial")}</small>` : ""}</td>
        <td class="num">${num(month.matches.length)}</td><td class="num">${temporalRecord(month.matches)}</td>
        <td class="num">${score(month.goalsFor, month.goalsAgainst)}</td><td class="num">${temporalNumber(month.pointsLeague)}</td>
        <td class="num">${month.pointsPct == null ? temporalText("noData") :
            `<div class="temporal-rate"><progress max="100" value="${month.pointsPct}" aria-label="${temporalText("rate")}"></progress>${num(month.pointsPct, 1)}%</div>`}</td>
        <td class="num">${num(month.exports)} / ${num(month.matches.length)}</td>
    </tr>`);
    const monthlyTable = table([
        {label: temporalText("month"), sortable: false}, {label: temporalText("games"), cls: "num", sortable: false},
        {label: temporalText("record"), cls: "num", sortable: false}, {label: temporalText("goals"), cls: "num", sortable: false},
        {label: temporalText("league"), cls: "num", sortable: false}, {label: temporalText("rate"), cls: "num", sortable: false},
        {label: temporalText("exports"), cls: "num", sortable: false},
    ], monthlyRows);
    const coverage = ["expected_goals_derived", "shots", "passes"].map((key, index) => {
        const label = ["xG / xGA", temporalText("shots"), temporalText("passes")][index];
        const covered = months.reduce((total, month) => total + (month.metricCoverage[key] ?? 0), 0);
        return `<span>${label} <b>${num(covered)}/${num(games.length)}</b></span>`;
    }).join("");
    return `<div class="grid">
        <section class="card pad temporal-summary">
            <div class="card-title-row"><h2>${esc(label)}</h2></div>
            ${summary}
        </section>
        <section class="card">
            <header class="card-header"><div><h2>${temporalText("timeline")}</h2><p>${temporalText("timelineNote")}</p></div></header>
            ${monthlyTable}
            <div class="data-note temporal-coverage"><strong>${temporalText("coverage")}</strong>${coverage}</div>
        </section>
        <details class="card temporal-fixtures"${months.length === 1 ? " open" : ""}>
            <summary class="card-header"><h2>${temporalText("fixtures")}</h2><span>${num(games.length)}</span></summary>
            ${temporalFixtures(games, links)}
        </details>
        ${temporalSquad(months, links)}
    </div>`;
}

function temporalFixtures(games: TemporalMatch[], links: boolean): string {
    return table([
        {label: temporalText("date")}, {label: temporalText("opponent")}, {label: temporalText("competition")},
        {label: temporalText("venue")}, {label: temporalText("score"), sortable: false},
        {label: "xG / xGA", sortable: false}, {label: temporalText("shots"), cls: "num"},
        {label: temporalText("passes"), cls: "num"}, {label: "MatchStats"},
    ], games.map(game => `<tr><td>${dateText(game.date)}</td>
        <td>${links ? matchLink(game.fixtureId, game.opponent || temporalText("noData")) : esc(game.opponent || temporalText("noData"))}</td>
        <td>${esc(game.competition || temporalText("noData"))}</td><td>${temporalText(game.venue === "Casa" ? "home" : "away")}</td>
        <td><b>${temporalNumber(game.goalsFor)}–${temporalNumber(game.goalsAgainst)}</b></td>
        <td>${temporalNumber(game.teamStats.expected_goals_derived, 2)} / ${temporalNumber(game.opponentStats.expected_goals_derived, 2)}</td>
        <td class="num">${temporalNumber(game.teamStats.shots)}</td><td class="num">${temporalNumber(game.teamStats.passes)}</td>
        <td>${game.exportId == null ? temporalText("noData") : statusBadge(temporalText("available"), "good")}</td></tr>`));
}

function temporalCategory(category: string): string {
    const labels: Record<string, [string, string, string]> = {
        profissional: ["Profissional", "Professional", "Profesional"],
        academia: ["Base", "Academy", "Cantera"],
        emprestado: ["Emprestado", "On loan", "Cedido"],
        "academia histórica": ["Base histórica", "Former academy", "Cantera histórica"],
        "histórico/saída": ["Histórico / saída", "Former squad", "Histórico / salida"],
    };
    return labels[category]?.[atlasLanguage() === "en-GB" ? 1 : atlasLanguage() === "es-ES" ? 2 : 0]
        || category || temporalText("noData");
}

function temporalSquad(months: TemporalMonth[], links: boolean): string {
    const series = new Map<number, { month: string; player: TemporalPlayer }[]>();
    for (const month of months) {
        for (const player of month.players) {
            const history = series.get(player.playerEaId) ?? [];
            history.push({month: month.month, player});
            series.set(player.playerEaId, history);
        }
    }
    const roster = [...series.values()].map(history => {
        const last = history.at(-1)!.player;
        const tracked = history.filter(row => row.player.minutes != null);
        const minutes = tracked.length ? tracked.reduce((total, row) => total + (row.player.minutes ?? 0), 0) : null;
        const rated = history.filter(row => row.player.averageRating != null);
        const ratedMatches = rated.reduce((total, row) => total + row.player.matchesWithRating, 0);
        const rating = ratedMatches ? rated.reduce((total, row) =>
            total + (row.player.averageRating ?? 0) * row.player.matchesWithRating, 0) / ratedMatches : null;
        return {history, last, minutes, rating, ratedMatches};
    }).sort((a, b) => (b.minutes ?? -1) - (a.minutes ?? -1) || a.last.name.localeCompare(b.last.name, atlasLanguage()));
    const metrics = (player: TemporalPlayer, key: string) => {
        const value = player.detailedStats[key];
        return value == null ? temporalText("noData") : `${num(value)} <small>(${num(player.detailedCoverage[key])}/${num(player.detailedMatches)})</small>`;
    };
    const players = roster.map(({history, last, minutes, rating, ratedMatches}) => {
        const rows = history.map(({month, player}) => `<tr>
            <td>${esc(temporalMonthLabel(month))}</td><td>${esc(temporalCategory(player.category))}</td>
            <td>${esc(player.position || temporalText("noData"))}</td><td class="num">${temporalNumber(player.overall)}</td>
            <td class="num">${temporalNumber(player.potential)}</td>
            <td class="num">${temporalNumber(player.minutes)} <small>(${num(player.matchesWithMinutes)})</small></td>
            <td class="num">${temporalNumber(player.averageRating, 2)} <small>(${num(player.matchesWithRating)})</small></td>
            <td class="num">${metrics(player, "npk_goals")}</td><td class="num">${metrics(player, "assists")}</td>
        </tr>`);
        return `<details class="story-player" data-temporal-player="${esc(`${last.name} ${last.playerEaId} ${temporalCategory(last.category)} ${last.position || ""}`)}">
            <summary><span><strong>${esc(last.name)}</strong><small>${esc(temporalCategory(last.category))} · ${esc(last.position || temporalText("noData"))}</small></span>
                <span>${temporalNumber(minutes)} min · ${temporalNumber(rating, 2)} (${num(ratedMatches)})</span></summary>
            <div class="story-player-body">${links ? `<div>${playerLink(last.playerEaId, last.name)}</div>` : ""}
                ${table([
                    {label: temporalText("month")}, {label: temporalText("category")}, {label: temporalText("position")},
                    {label: temporalText("overall"), cls: "num"}, {label: temporalText("potential"), cls: "num"},
                    {label: temporalText("minutes"), cls: "num"}, {label: temporalText("rating"), cls: "num"},
                    {label: temporalText("playerGoals"), cls: "num"}, {label: temporalText("assists"), cls: "num"},
                ].map(header => ({...header, sortable: false})), rows)}
            </div>
        </details>`;
    }).join("");
    return `<section class="card pad">
        <div class="card-title-row"><h2>${temporalText("squad")}</h2><span data-temporal-player-count aria-live="polite">${num(roster.length)} ${temporalText("players")}</span></div>
        <p class="chart-note">${temporalText("squadNote")} ${temporalText("playerCoverage")}</p>
        <div class="story-report-controls"><input type="search" data-temporal-search placeholder="${temporalText("search")}" aria-label="${temporalText("search")}"></div>
        <div class="story-player-list">${players || `<p class="muted">${temporalText("noPlayers")}</p>`}</div>
    </section>`;
}
