function setLoading() { content.innerHTML = `<div class="content-inner"><div class="grid metrics">${Array.from({ length: 5 }, () => '<div class="card metric-card skeleton"></div>').join("")}</div><div class="card skeleton" style="height:300px"></div></div>`; }
async function bootstrap() {
    const initialView = new URLSearchParams(location.search).get("view");
    window.addEventListener("unhandledrejection", event => {
        const reason = event.reason instanceof Error ? event.reason.message : String(event.reason || "Unknown error");
        console.error("Atlas action failed", event.reason);
        toast(`Action failed: ${reason}`);
        event.preventDefault();
    });
    applyIcons();
    bindShell();
    setLoading();
    try {
        state.status = await api<StatusResponse>("/api/status");
        
        // Load LLM configuration from DB
        const llmConfig = await api<JsonRecord>("/api/llm/config");
        if (llmConfig) {
            state.llmProvider = llmConfig.provider || "ollama";
            state.llmKeys = llmConfig.keys || {};
        }

        applyAtlasLanguage();
        state.careers = await api<CareerSummary[]>("/api/careers");
        if (state.careers.length) {
            state.careerId = Number(state.careers[0].id);
            await loadSnapshots();
        }
        fillSelectors();
        updateSystemUi();
        if (initialView === "commission") state.analysisTab = "commission";
        navigate(initialView === "commission" ? "commission" : "overview", {}, true);
    }
    catch (e) {
        content.innerHTML = errorState("Application could not be loaded", e.message);
    }
    if (!new URLSearchParams(location.search).has("static"))
        setInterval(pollStatus, 5000);
}
async function loadSnapshots(preserve: any = false) {
    if (!state.careerId) {
        state.snapshots = [];
        state.careerClock = null;
        state.snapshotId = null;
        return;
    }
    const old = state.snapshotId;
    const [snapshots, clock] = await Promise.all([
        api<SnapshotSummary[]>(`/api/careers/${state.careerId}/snapshots`),
        api<CareerClock>(`/api/careers/${state.careerId}/clock`),
    ]);
    state.snapshots = snapshots;
    state.careerClock = clock;
    state.snapshotId = preserve && state.snapshots.some((s: any) => Number(s.id) === Number(old)) ? old : (state.snapshots.length ? Number(state.snapshots[0].id) : null);
    state.compareFrom = state.snapshots.length > 1 ? Number(state.snapshots.at(-1)?.id) : state.snapshotId;
    state.compareTo = state.snapshotId;
}
function currentCareer() { return state.careers.find((c: any) => Number(c.id) === Number(state.careerId)); }
function currentSnapshot() { return state.snapshots.find((s: any) => Number(s.id) === Number(state.snapshotId)); }
function fillSelectors() {
    careerSelect.innerHTML = state.careers.length ? state.careers.map((c: any) => `<option value="${c.id}">${esc(c.initial_team_name || c.display_name)}</option>`).join("") : '<option>No career</option>';
    if (state.careerId)
        careerSelect.value = String(state.careerId);
    snapshotSelect.innerHTML = state.snapshots.length ? state.snapshots.map((s: any) => {
        const isLiveSnapshot = Number(state.careerClock?.snapshotId) === Number(s.id);
        const liveDate = String(state.careerClock?.careerDate || s.career_date || "");
        const snapshotDate = String(s.career_date || "");
        const advanced = isLiveSnapshot && liveDate && snapshotDate && liveDate !== snapshotDate;
        const dateLabel = advanced ? `${dateText(liveDate)} · career date · data from ${dateText(snapshotDate)}` : dateText(snapshotDate);
        return `<option value="${s.id}">${dateLabel} · ${esc(s.season_label || "Unknown season")}${s.career_season_number ? ` · Career season ${num(s.career_season_number)}` : ""}${Number(s.same_day_sequence) > 1 ? ` · #${s.same_day_sequence}` : ""}</option>`;
    }).join("") : '<option>No snapshot</option>';
    if (state.snapshotId)
        snapshotSelect.value = String(state.snapshotId);
}
function updateSystemUi() {
    applyAtlasLanguage();
    const c = currentCareer(), s = currentSnapshot(), club = s?.managed_team_name || c?.initial_team_name || "No career", mark = initials(club);
    $("#careerMark").textContent = mark;
    $("#sidebarClubMark").textContent = mark;
    $("#sidebarClubName").textContent = club;
    if (s) {
        const isLiveSnapshot = Number(state.careerClock?.snapshotId) === Number(s.id);
        const liveDate = String(state.careerClock?.careerDate || s.career_date || "");
        const advanced = isLiveSnapshot && liveDate && liveDate !== String(s.career_date || "");
        $("#sidebarSnapshotText").textContent = advanced
            ? `${dateText(liveDate)} · ${esc(s.season_label || "Unknown season")}${s.career_season_number ? ` · C${num(s.career_season_number)}` : ""} · data from ${dateText(s.career_date)}`
            : `${dateText(s.career_date)} · ${esc(s.season_label || "Unknown season")}${s.career_season_number ? ` · C${num(s.career_season_number)}` : ""}`;
    } else {
        $("#sidebarSnapshotText").textContent = "Choose a snapshot";
    }
    $("#managerInitials").textContent = initials(c?.manager_name || c?.display_name || "AT");
    $("#versionText").textContent = `v${state.status?.version || "1.2.5"}`;
    $("#watcherText").textContent = state.status?.watcherActive ? "Watcher active" : "Watcher inactive";
    const workspace = state.status?.workspace || {}, workspaceBadge = $("#workspaceBadge");
    const isSandbox = Boolean(workspace.isSandbox || workspace.kind === "sandbox" || workspace.kind === "branch");
    const workspaceName = String(workspace.name || (isSandbox ? "Branch" : "Career"));
    workspaceBadge.textContent = isSandbox ? `BRANCH · ${workspaceName}` : workspaceName;
    workspaceBadge.title = `${isSandbox ? "Career Branch" : "Career Save"}: ${workspaceName} · click to manage`;
    workspaceBadge.classList.toggle("sandbox", isSandbox);
    workspaceBadge.classList.toggle("workspace-main", !isSandbox);
    document.body.classList.toggle("workspace-sandbox", isSandbox);
    const b = $("#readyBadge"), n = Number(state.status?.readyCount || 0);
    b.textContent = String(n);
    b.classList.toggle("hidden", n === 0);
    const clockNote = state.careerClock?.careerDate ? ` · career date ${dateText(state.careerClock.careerDate)}` : "";
    $("#pageStatus").innerHTML = state.status ? `<span class="pulse"></span>${num(state.status.snapshotCount)} Snapshot${Number(state.status.snapshotCount) === 1 ? "" : "s"}${clockNote}` : "";
}
function navigate(route: any, data: any = {}, push: any = true) {
    if (push) {
        state.history = state.history.slice(0, state.historyIndex + 1);
        state.history.push({ route, data: { ...data } });
        state.historyIndex = state.history.length - 1;
    }
    state.route = route;
    state.routeData = { ...data };
    setActiveNav();
    renderBreadcrumbs();
    render().catch((e: any) => content.innerHTML = errorState("Page could not be loaded", e.message));
}
function goHistory(delta: any) {
    const next = state.historyIndex + delta;
    if (next < 0 || next >= state.history.length)
        return;
    state.historyIndex = next;
    const e = state.history[next];
    state.route = e.route;
    state.routeData = { ...(e.data || {}) };
    setActiveNav();
    renderBreadcrumbs();
    render().catch((err: any) => content.innerHTML = errorState("Page could not be loaded", err.message));
}
function setActiveNav() { const map: Record<string, string> = { player: "squad", club: "overview", match: "match-center", competition: "competitions", "world-competition": "competitions" }; const active = map[state.route] || state.route; $$('#mainNav [data-route]').forEach((n: any) => n.classList.toggle("active", n.dataset.route === active)); }
function renderBreadcrumbs() { const labels: Record<string, string> = { overview:tr("crumbOverview"), "match-center":tr("crumbMatches"), schedule:tr("navSchedule"), results:tr("navResults"), match:tr("crumbMatch"), competitions:tr("navCompetitions"), competition:tr("navCompetitions"), "world-competition":tr("navCompetitions"), squad:tr("crumbSquad"), player:tr("crumbPlayer"), club:tr("crumbOverview"), contracts:tr("navContracts"), loans:tr("navLoans"), transfers:tr("navTransfers"), youth:tr("navYouth"), compare:tr("navCompare"), chronology:tr("navChronology"), "manual-data":tr("navManual"), analysis:tr("crumbAnalysis"), commission:tr("crumbCommission"), records:tr("navRecords"), "season-report":tr("navSeasonReport"), snapshots:tr("navSnapshots"), imports:tr("navImports"), media:tr("navMedia"), setup:tr("crumbSetup") }; const club = currentSnapshot()?.managed_team_name || currentCareer()?.initial_team_name || "Career"; $("#breadcrumbs").innerHTML = `<button data-crumb="overview">${esc(club)}</button><span>›</span><b>${labels[state.route] || esc(state.route)}</b>`; $$('[data-crumb]').forEach((b: any) => b.onclick = () => navigate(b.dataset.crumb || "overview")); }
async function refreshCareerBootstrap(preserveSnapshot = true) {
    state.status = await api<StatusResponse>("/api/status");
    state.careers = await api<CareerSummary[]>("/api/careers");
    const currentStillExists = state.careers.some((career: any) => Number(career.id) === Number(state.careerId));
    if (!currentStillExists)
        state.careerId = state.careers.length ? Number(state.careers[0].id) : null;
    if (state.careerId)
        await loadSnapshots(preserveSnapshot);
    else {
        state.snapshots = [];
        state.careerClock = null;
        state.snapshotId = null;
    }
    fillSelectors();
    updateSystemUi();
}
async function render() {
    const careerIndependentRoutes = ["setup", "imports", "media"];
    if ((!state.careers.length && !careerIndependentRoutes.includes(state.route)) ||
        (state.careers.length && !state.snapshotId && !["manual-data", ...careerIndependentRoutes].includes(state.route))) {
        renderNoData();
        return;
    }
    setLoading();
    const routes: Record<string, () => Promise<void>> = { overview: renderOverview, analysis: renderAnalysis, commission: renderAnalysis, records: renderRecords, "season-report": renderSeasonReport, squad: renderSquad, "match-center": renderMatchCenter, schedule: () => renderMatchList("schedule"), results: () => renderMatchList("results"), match: renderMatch, competitions: renderCompetitions, competition: renderCompetition, "world-competition": renderWorldCompetition, contracts: renderContracts, loans: renderLoans, transfers: renderTransfers, youth: renderYouth, compare: renderCompare, chronology: renderChronology, "manual-data": renderManualData, snapshots: renderSnapshots, imports: renderImports, media: renderMedia, setup: renderSetup, player: renderPlayer, club: renderClub };
    await (routes[state.route] || renderOverview)();
    content.scrollTop = 0;
    applyIcons(content);
    bindContent();
}
function renderNoData() { const configured = Boolean(state.status?.snapshotRoot); content.innerHTML = `<div class="content-inner">${pageHead("Welcome to Project Atlas Tracker", "FC26 career statistics and world tracking")}${emptyState(configured ? "No career imported yet" : "Set up the snapshot folder", configured ? "Place a complete export in the ready folder and start a scan." : "Choose the shared root folder used by the LUA exporter and Project Atlas Tracker.", `<button class="button primary" data-action="${configured ? "scan" : "setup"}">${configured ? "Scan now" : "Open setup"}</button>`)}</div>`; applyIcons(content); bindContent(); }
function renderMatchRows(rows: any, limit: any = Infinity) {
    if (!rows.length)
        return `<div class="muted" style="font-size:11px;padding:12px">No matches available.</div>`;
    return rows.slice(0, limit).map((m: any) => `<div class="match-card" data-match="${m.fixture_id}"><div class="match-date"><strong>${dateText(m.date)}</strong>${esc(timeText(m.time))}<br><span class="inline-identity">${m.competitionIdentity ? identityLogo(m.competitionIdentity, m.competition_name, "inline-logo") : ""}${competitionLink(m.competition_object_id, m.competition_name)}</span>${m.detailedStatsAvailable ? `<br><span class="status-badge good match-detail-badge">Detailed FC26 data</span>` : ""}</div><div class="match-teams"><div class="match-team"><span class="inline-identity">${identityLogo(m.homeIdentity, m.home_team_name, "match-logo-small")}${clubLink(m.home_team_ea_id, m.home_team_name)}</span><b>${m.is_completed ? num(m.home_score) : ""}</b></div><div class="match-team"><span class="inline-identity">${identityLogo(m.awayIdentity, m.away_team_name, "match-logo-small")}${clubLink(m.away_team_ea_id, m.away_team_name)}</span><b>${m.is_completed ? num(m.away_score) : ""}</b></div></div><div class="score">${m.is_completed ? resultPill(m.managed_team_result) : matchLink(m.fixture_id, "Open")}</div></div>`).join("");
}
function lineChart(points: any, keys: any = ["overall", "potential"], options: any = {}) {
    if (!points?.length) return '<div class="muted">Not enough data points yet.</div>';
    const W = 720, H = 250, left = 54, right = 22, top = 28, bottom = 50;
    const values = points.flatMap((p: any) => keys.map((k: any) => Number(p[k])).filter(Number.isFinite));
    if (!values.length) return '<div class="muted">No values are available for this chart.</div>';
    const rawMin = Math.min(...values), rawMax = Math.max(...values);
    const margin = options.margin ?? Math.max(options.decimals ? .5 : 2, (rawMax - rawMin) * .12);
    const min = options.min ?? Math.max(0, rawMin - margin), max = options.max ?? rawMax + margin, span = Math.max(.1, max - min);
    const x = (i: number) => left + i * (W-left-right) / Math.max(1, points.length-1);
    const y = (value: number) => top + (max-value) * (H-top-bottom) / span;
    const decimals = Number(options.decimals ?? 1);
    const format = (value: number) => options.format === "money" ? money(value) : `${num(value, decimals)}${options.unit || ""}`;
    const ticks = Array.from({length: 5}, (_, i) => max - i * span / 4);
    const labelsEvery = Math.max(1, Math.ceil(points.length / 7));
    const lines = keys.map((key: string, series: number) => {
        const coords = points.map((point: any, index: number) => ({point, index, value: Number(point[key])})).filter((item: any) => Number.isFinite(item.value));
        return `<polyline class="chart-line ${series ? "secondary" : ""}" points="${coords.map((item: any) => `${x(item.index)},${y(item.value)}`).join(" ")}"/>${coords.map((item: any) => `<circle class="chart-point ${series ? "secondary" : ""}" cx="${x(item.index)}" cy="${y(item.value)}" r="4"><title>${esc(item.point.season_label || item.point.career_date || item.point.effective_date || "")}: ${esc(format(item.value))}</title></circle><text class="chart-value-label ${series ? "secondary" : ""}" x="${x(item.index)}" y="${y(item.value) - (series ? -16 : 10)}" text-anchor="middle">${esc(format(item.value))}</text>`).join("")}`;
    }).join("");
    return `<div class="chart analysis-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(options.ariaLabel || "Timeline")}">${ticks.map(t => `<line class="chart-grid-line" x1="${left}" y1="${y(t)}" x2="${W-right}" y2="${y(t)}"/><text class="chart-axis-label" x="${left-8}" y="${y(t)+4}" text-anchor="end">${esc(format(t))}</text>`).join("")}${lines}${points.map((point: any, index: number) => index % labelsEvery === 0 || index === points.length-1 ? `<text class="chart-axis-label" x="${x(index)}" y="${H-15}" text-anchor="middle">${esc(point.season_label || dateText(point.career_date || point.effective_date))}</text>` : "").join("")}</svg></div>`;
}
