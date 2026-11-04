"use strict";
let mediaProgressTimer = null;
let lastMediaProgressPhase = null;
let lastMediaPending = null;
let mediaRefreshPending = false;
const apiCache = new Map();
const state = {
    status: null, careers: [], snapshots: [], careerClock: null, careerId: null, snapshotId: null,
    route: "overview", routeData: {}, history: [], historyIndex: -1,
    searchResults: [], searchIndex: -1, playerTab: "overview", playerComparisonScope: "club", playerComparisonMode: "group",
    squadQuery: "", squadPosition: "all", squadSort: "position",
    competitionQuery: "", matchCompetition: "all",
    compareFrom: null, compareTo: null,
    competitionTab: "results", chronologyType: "all", chronologyQuery: "", loanScope: "club", transferScope: "club",
    movementSeasonIndex: null, movementEditKind: null, movementEditId: null,
    analysisSeasonIndex: null, recordsSeasonIndex: -1, seasonReportSeasonIndex: null, seasonReportTab: "overview", analysisTab: "overview", clubTab: "overview", competitionListTab: "deeper",
    mediaType: "all", mediaStatus: "all", mediaSources: null,
    manualSeasonId: null, manualTab: "competitions", manualEditKind: null, manualEditId: null, manualDraftCompetitionId: null, manualQuickEntry: false,
    pendingLiveRender: false,
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const content = $("#content");
const toastEl = $("#toast");
const careerSelect = $("#careerSelect");
const snapshotSelect = $("#snapshotSelect");
const searchPalette = $("#searchPalette");
const searchInput = $("#searchInput");
const searchResults = $("#searchResults");
const statusPopover = $("#statusPopover");
const iconSvg = (path) => `<svg viewBox="0 0 24 24" fill="none"><path d="${path}" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICONS = {
    dashboard: iconSvg("M4 4h6v7H4zM14 4h6v4h-6zM4 15h6v5H4zM14 12h6v8h-6z"),
    users: iconSvg("M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M17 11a3 3 0 1 0 0-6M22 21v-2a4 4 0 0 0-3-3.87"),
    match: iconSvg("M4 5h16v14H4zM9 5v14M15 5v14M4 12h16M12 9v6"),
    calendar: iconSvg("M4 6h16v14H4zM8 3v6M16 3v6M4 10h16"),
    result: iconSvg("M5 4h14v16H5zM8 8h8M8 12h5M8 16h8"),
    trophy: iconSvg("M8 4h8v4a4 4 0 0 1-8 0V4M8 6H5v2a4 4 0 0 0 4 4M16 6h3v2a4 4 0 0 1-4 4M12 12v6M8 21h8"),
    contract: iconSvg("M6 3h9l3 3v15H6zM14 3v5h5M9 12h6M9 16h6"),
    transfer: iconSvg("M4 8h14m-4-4 4 4-4 4M20 16H6m4-4-4 4 4 4"),
    compare: iconSvg("M7 4v16M17 4v16M3 8l4-4 4 4M13 16l4 4 4-4"),
    timeline: iconSvg("M4 6h16M4 12h16M4 18h16M8 4v4M15 10v4M10 16v4"),
    download: iconSvg("M12 3v12m-5-5 5 5 5-5M5 21h14"),
    settings: iconSvg("M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A7 7 0 0 0 15 6l-.3-2.6h-4L10.5 6A7 7 0 0 0 9 7.1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1A7 7 0 0 0 10.5 18l.2 2.6h4L15 18a7 7 0 0 0 1.5-1.1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z"),
    back: iconSvg("m15 18-6-6 6-6"), forward: iconSvg("m9 18 6-6-6-6"),
    search: iconSvg("M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 5 5"),
    history: iconSvg("M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2"),
    refresh: iconSvg("M20 11a8 8 0 1 0-2.3 5.7L20 14M20 7v4h-4"),
    arrow: iconSvg("M5 12h14m-5-5 5 5-5 5"), database: iconSvg("M4 5c0 2 16 2 16 0s-16-2-16 0v14c0 2 16 2 16 0V5M4 12c0 2 16 2 16 0"),
    folder: iconSvg("M3 6h7l2 2h9v11H3z"), empty: iconSvg("M4 7h16v12H4zM8 4h8v3M9 12h6"),
    media: iconSvg("M4 5h16v14H4zM8 14l2-2 3 3 2-2 3 3M9 9h.01"),
    edit: iconSvg("M4 20h4l11-11-4-4L4 16v4M13 7l4 4"),
    save: iconSvg("M5 4h12l2 2v14H5zM8 4v6h8V4M8 16h8"),
};
function applyIcons(root = document) {
    $$('[data-icon]', root).forEach((n) => {
        const key = n.dataset.icon;
        if (key && ICONS[key])
            n.innerHTML = ICONS[key];
    });
}
const ATLAS_TEXT = {
    "pt-BR": { navOverview: "Visão geral", navChronology: "Linha do tempo", navManual: "Dados históricos", navMatches: "Central de partidas", navSchedule: "Calendário", navResults: "Resultados", navCompetitions: "Competições", navSquad: "Elenco", navContracts: "Contratos", navTransfers: "Transferências", navLoans: "Empréstimos", navYouth: "Base FC26", navCommission: "Comissão técnica", navAnalysis: "Análises", navRecords: "Recordes", navSeasonReport: "Relatório da temporada", navCompare: "Comparar snapshots", navSnapshots: "Snapshots", navImports: "Importações", navMedia: "Biblioteca de mídia", navSetup: "Configurações", crumbOverview: "Visão geral", crumbCommission: "Comissão técnica", crumbAnalysis: "Análises", crumbMatches: "Partidas", crumbMatch: "Partida", crumbSquad: "Elenco", crumbPlayer: "Perfil do jogador", crumbSetup: "Configurações", setupLanguage: "Idioma do Atlas", setupLanguageHelp: "Define o idioma da interface principal e das análises da Comissão Técnica.", saveLanguage: "Salvar idioma", languageSaved: "Idioma do Atlas atualizado.", commissionNote: "Nota da comissão", claimFact: "Fato observado", claimInference: "Inferência baseada em evidências", claimHypothesis: "Hipótese esportiva", claimLimit: "Limite da evidência", claimsFiltered: "Afirmações filtradas", interpretationNotScored: "Qualidade interpretativa não avaliada independentemente", reportOnDemand: "Análises sob demanda", generateReport: "Gerar análise", retroTitle: "Analisar histórico da carreira", retroHelp: "Gera relatórios da temporada selecionada em ordem cronológica. Atualiza partidas, jogadores e avaliações acumuladas; retoma após interrupções e sinaliza dados ausentes.", retroStart: "Gerar análises históricas", retroResume: "Retomar análises históricas", retroWorking: "Processando análises históricas", retroPaused: "Pausado: Ollama indisponível. O progresso foi salvo; clique em retomar.", retroFailed: "Concluído com falhas ou dados ausentes", retroDone: "Análises históricas concluídas", retroBackup: "Backup criado antes da geração" },
    "en-GB": { navOverview: "Overview", navChronology: "Career timeline", navManual: "Historical data", navMatches: "Match Centre", navSchedule: "Schedule", navResults: "Results", navCompetitions: "Competitions", navSquad: "Squad", navContracts: "Contracts", navTransfers: "Transfer history", navLoans: "Loans", navYouth: "FC26 youth", navCommission: "Technical commission", navAnalysis: "Analysis", navRecords: "Records", navSeasonReport: "Season report", navCompare: "Snapshot comparison", navSnapshots: "Snapshots", navImports: "Imports", navMedia: "Media library", navSetup: "Settings", crumbOverview: "Overview", crumbCommission: "Technical commission", crumbAnalysis: "Analysis", crumbMatches: "Matches", crumbMatch: "Match", crumbSquad: "Squad", crumbPlayer: "Player profile", crumbSetup: "Settings", setupLanguage: "Atlas language", setupLanguageHelp: "Sets the main interface and Technical Commission analysis language.", saveLanguage: "Save language", languageSaved: "Atlas language updated.", commissionNote: "Commission note", claimFact: "Observed fact", claimInference: "Evidence-based inference", claimHypothesis: "Sports hypothesis", claimLimit: "Evidence limitation", claimsFiltered: "Claims filtered", interpretationNotScored: "Interpretation quality not independently scored", reportOnDemand: "On-demand analysis", generateReport: "Generate analysis", retroTitle: "Analyse career history", retroHelp: "Generate reports for the selected season in chronological order. Update match, player and accumulated assessments; resume after interruptions and flag missing data.", retroStart: "Generate historical reports", retroResume: "Resume historical reports", retroWorking: "Processing historical reports", retroPaused: "Paused: Ollama is unavailable. Progress is saved; select resume to continue.", retroFailed: "Completed with failures or missing data", retroDone: "Historical reports complete", retroBackup: "Backup created before generation" },
    "es-ES": { navOverview: "Resumen", navChronology: "Cronología", navManual: "Datos históricos", navMatches: "Centro de partidos", navSchedule: "Calendario", navResults: "Resultados", navCompetitions: "Competiciones", navSquad: "Plantilla", navContracts: "Contratos", navTransfers: "Historial de traspasos", navLoans: "Cesiones", navYouth: "Cantera FC26", navCommission: "Comisión técnica", navAnalysis: "Análisis", navRecords: "Récords", navSeasonReport: "Informe de temporada", navCompare: "Comparar snapshots", navSnapshots: "Snapshots", navImports: "Importaciones", navMedia: "Biblioteca multimedia", navSetup: "Ajustes", crumbOverview: "Resumen", crumbCommission: "Comisión técnica", crumbAnalysis: "Análisis", crumbMatches: "Partidos", crumbMatch: "Partido", crumbSquad: "Plantilla", crumbPlayer: "Perfil del jugador", crumbSetup: "Ajustes", setupLanguage: "Idioma de Atlas", setupLanguageHelp: "Define el idioma de la interfaz principal y de los análisis de la Comisión Técnica.", saveLanguage: "Guardar idioma", languageSaved: "Idioma de Atlas actualizado.", commissionNote: "Nota de la comisión", claimFact: "Hecho observado", claimInference: "Inferencia basada en evidencias", claimHypothesis: "Hipótesis deportiva", claimLimit: "Límite de la evidencia", claimsFiltered: "Afirmaciones filtradas", interpretationNotScored: "Calidad interpretativa no evaluada de forma independiente", reportOnDemand: "Análisis bajo demanda", generateReport: "Generar análisis", retroTitle: "Analizar el historial de la carrera", retroHelp: "Genera informes para la temporada seleccionada en orden cronológico. Actualiza partidos, jugadores y valoraciones acumuladas; reanuda después de interrupciones y señala datos ausentes.", retroStart: "Generar informes históricos", retroResume: "Reanudar informes históricos", retroWorking: "Procesando informes históricos", retroPaused: "Pausado: Ollama no está disponible. El progreso está guardado; pulse reanudar.", retroFailed: "Terminado con fallos o datos ausentes", retroDone: "Informes históricos terminados", retroBackup: "Copia de seguridad creada antes de generar" }
};
Object.assign(ATLAS_TEXT["pt-BR"], { moreContextTitle: "A comissão pediu mais contexto", moreContextHelp: "Responda apenas o que souber. Sua resposta será enviada separada das estatísticas importadas.", yourContext: "Sua resposta", sendContext: "Enviar contexto à comissão", contextSent: "Contexto enviado ao Ollama; atualizando a análise…" });
Object.assign(ATLAS_TEXT["en-GB"], { moreContextTitle: "The commission needs more context", moreContextHelp: "Answer only what you know. Your response is sent separately from imported statistics.", yourContext: "Your answer", sendContext: "Send context to the commission", contextSent: "Context sent to Ollama; refreshing the analysis…" });
Object.assign(ATLAS_TEXT["es-ES"], { moreContextTitle: "La comisión necesita más contexto", moreContextHelp: "Responde solo lo que sepas. Tu respuesta se envía por separado de las estadísticas importadas.", yourContext: "Tu respuesta", sendContext: "Enviar contexto a la comisión", contextSent: "Contexto enviado a Ollama; actualizando el análisis…" });
function atlasLanguage() { const selected = String(state.status?.settings?.language || "pt-BR"); return ATLAS_TEXT[selected] ? selected : "pt-BR"; }
function tr(key) { return ATLAS_TEXT[atlasLanguage()][key] || ATLAS_TEXT["en-GB"][key] || key; }
function applyAtlasLanguage() { const language = atlasLanguage(); document.documentElement.lang = language; $$("[data-nav-key]").forEach(item => { const key = String(item.dataset.navKey || ""); if (key)
    item.textContent = tr(key); }); }
function esc(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
function num(value, digits = 0) { if (value == null || value === "")
    return "–"; const n = Number(value); return Number.isFinite(n) ? new Intl.NumberFormat(atlasLanguage(), { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n) : "–"; }
function rawNumber(value) { const n = Number(value); return Number.isFinite(n) ? String(n) : ""; }
function commissionFollowupForm(requests, params) {
    if (!Array.isArray(requests) || !requests.length)
        return "";
    const prior = Array.isArray(params.coach_context) ? params.coach_context.slice(0, 6).map((item) => `<input type="hidden" name="prior_question" value="${esc(item.question || "")}"><input type="hidden" name="prior_answer" value="${esc(item.answer || "")}">`).join("") : "";
    const fields = requests.slice(0, 2).map((request, index) => `<div class="commission-followup-question"><label for="commission-followup-answer-${index}"><strong>${esc(request.question || "")}</strong><small>${esc(request.reason || "")}</small></label><input type="hidden" name="question" value="${esc(request.question || "")}"><textarea id="commission-followup-answer-${index}" name="answer" maxlength="1000" required placeholder="${esc(tr("yourContext"))}"></textarea></div>`).join("");
    return `<form class="commission-followup-form" data-commission-followup data-snapshot-id="${Number(params.snapshot_id || 0)}" data-mode="${esc(params.mode || "")}" data-fixture-id="${Number(params.fixture_id || 0)}" data-player-ea-id="${Number(params.player_ea_id || 0)}" data-model="${esc(params.model || "")}">${prior}<h4>${esc(tr("moreContextTitle"))}</h4><p>${esc(tr("moreContextHelp"))}</p>${fields}<button class="button" type="submit">${esc(tr("sendContext"))}</button></form>`;
}
function rawId(value) { const n = Number(value); return Number.isSafeInteger(n) && n > 0 ? String(n) : ""; }
function compact(value) { const n = Number(value); return Number.isFinite(n) ? new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 }).format(n) : "–"; }
function money(value) {
    const n = Number(value);
    if (!Number.isFinite(n))
        return "–";
    if (Math.abs(n) >= 1e6)
        return `€${num(n / 1e6, 1)}m`;
    if (Math.abs(n) >= 1e3)
        return `€${num(n / 1e3, 0)}k`;
    return `€${num(n)}`;
}
function financialHint(financial, kind) {
    const item = kind === "market" ? financial?.market_value : financial?.weekly_wage;
    if (!item)
        return "";
    const parts = [];
    if (item.label)
        parts.push(String(item.label));
    if (item.profitability_value_source === "observed")
        parts.push(`Profitability ${item.profitability_value}: observed`);
    if (item.profitability_value_source === "inferred_from_later_snapshot")
        parts.push(`Profitability ${item.profitability_value}: inferred from a later snapshot`);
    if (item.warning)
        parts.push(String(item.warning));
    if (item.profile_id)
        parts.push(`Profile ${item.profile_id}`);
    return esc(parts.join(" · "));
}
function dateText(value) {
    if (!value)
        return "–";
    const d = new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime()) ? esc(value) : new Intl.DateTimeFormat(atlasLanguage()).format(d);
}
function timeText(v) { return v ? String(v).slice(0, 5) : ""; }
function initials(value) { const p = String(value || "AT").trim().split(/\s+/).filter(Boolean); return p.length > 1 ? `${p[0]?.[0] || ""}${p.at(-1)?.[0] || ""}`.toUpperCase() : (p[0] || "AT").slice(0, 2).toUpperCase(); }
const positionAliases = {
    TW: "GK", TORWART: "GK", LIB: "SW", LIBERO: "SW", RAV: "RWB", RV: "RB", RIV: "RCB", IV: "CB", LIV: "LCB", LV: "LB", LAV: "LWB",
    ZDM: "CDM", RZM: "RCM", ZM: "CM", LZM: "LCM", ROM: "RAM", ZOM: "CAM", LOM: "LAM", HS: "CF", MS: "CF", LST: "LS", RST: "RS"
};
const positionById = { 0: "GK", 1: "SW", 2: "RWB", 3: "RB", 4: "RCB", 5: "CB", 6: "LCB", 7: "LB", 8: "LWB", 9: "RDM", 10: "CDM", 11: "LDM", 12: "RM", 13: "RCM", 14: "CM", 15: "LCM", 16: "LM", 17: "RAM", 18: "CAM", 19: "LAM", 20: "RF", 21: "CF", 22: "LF", 23: "RW", 24: "RS", 25: "ST", 26: "LS", 27: "LW" };
function canonicalPosition(value, explicitId = null) {
    const raw = String(value || "").trim().toUpperCase();
    const hasExplicitId = explicitId !== null && explicitId !== undefined && String(explicitId).trim() !== "";
    const id = hasExplicitId ? Number(explicitId) : Number.NaN;
    return positionAliases[raw] || raw || (Number.isInteger(id) ? positionById[id] : "");
}
function pos(v) { return canonicalPosition(v) || "–"; }
function positionClass(v) { const value = canonicalPosition(v); if (value === "GK")
    return "pos-gk"; if (["SW", "RWB", "RB", "RCB", "CB", "LCB", "LB", "LWB"].includes(value))
    return "pos-def"; if (["RDM", "CDM", "LDM", "RM", "RCM", "CM", "LCM", "LM", "RAM", "CAM", "LAM"].includes(value))
    return "pos-mid"; return "pos-att"; }
function positionOrder(value, explicitId = null) {
    const rank = {
        GK: 0, SW: 5,
        RWB: 10, RB: 11, RCB: 20, CB: 21, LCB: 22, LB: 30, LWB: 31,
        RDM: 40, CDM: 41, LDM: 42, RCM: 50, CM: 51, LCM: 52,
        RAM: 60, CAM: 61, LAM: 62, RM: 70, RF: 71, RW: 72, LM: 80, LF: 81, LW: 82,
        CF: 90, RS: 100, ST: 101, LS: 102
    };
    const canonical = canonicalPosition(value, explicitId);
    return rank[canonical] ?? 999;
}
function overallClass(v) { const n = Number(v); return n >= 75 ? "overall-high" : n >= 68 ? "overall-mid" : "overall-low"; }
function resultCode(v) { const s = String(v || "").toUpperCase(); return s.startsWith("W") ? "W" : s.startsWith("D") ? "D" : s.startsWith("L") ? "L" : "–"; }
function resultPill(v) { const c = resultCode(v); return `<span class="result-pill ${c}">${c}</span>`; }
function boolText(v) { return Number(v) === 1 ? "Yes" : Number(v) === 0 ? "No" : "–"; }
function entityMark(name, kind = "club") { return `<span class="entity-mark ${kind}">${esc(initials(name))}</span>`; }
function mediaImg(asset, alt, cls = "media-image", thumb = true) {
    if (!asset)
        return "";
    const url = thumb ? (asset.thumbUrl || asset.url) : asset.url;
    return url ? `<img class="${esc(cls)}" src="${esc(url)}" alt="${esc(alt || "")}" loading="lazy">` : "";
}
function playerPortrait(media, name, cls = "player-portrait") {
    const portrait = media?.portrait;
    return portrait ? mediaImg(portrait, name, cls, cls !== "player-portrait-large") : `<span class="generated-avatar ${esc(cls)}" style="--seed:${Number(media?.placeholderSeed || 0) % 360}">${esc(initials(name))}</span>`;
}
function identityLogo(identity, name, cls = "identity-logo") {
    return identity?.logo ? mediaImg(identity.logo, name, cls) : `<span class="identity-fallback ${esc(cls)}">${esc(initials(name))}</span>`;
}
function trophyImage(identity, name, cls = "trophy-image") { return identity?.trophy ? mediaImg(identity.trophy, name, cls) : ""; }
function identityStyle(identity) { const colors = identity?.colors || []; return colors.length ? `style="--club-primary:${esc(colors[0])};--club-secondary:${esc(colors[1] || colors[0])};--club-accent:${esc(colors[2] || colors[1] || colors[0])}"` : ""; }
function kitCard(kit) { const image = kit.image ? mediaImg(kit.image, kit.label, "kit-image", false) : `<span class="kit-placeholder" style="--kit-1:${esc(kit.colors?.[0] || "#d7e1ec")};--kit-2:${esc(kit.colors?.[1] || "#233b57")}"></span>`; return `<div class="kit-card">${image}<strong>${esc(kit.label)}</strong><small>${kit.image?.season_start ? `Season ${kit.image.season_start}/${String(kit.image.season_start + 1).slice(-2)}` : kit.image?.usedFallback ? "Default kit" : "Reference colours"}</small></div>`; }
function playerLink(id, name) { return `<button class="entity-link" data-player="${Number(id)}">${esc(name || `Player ${id}`)}</button>`; }
function clubLink(id, name) { return `<button class="entity-link" data-club="${Number(id)}">${esc(name || `Club ${id}`)}</button>`; }
function competitionLink(id, name) { return `<button class="entity-link" data-competition="${Number(id)}">${esc(name || `Competition ${id}`)}</button>`; }
function matchLink(id, label = "Open match") { return `<button class="entity-link" data-match="${Number(id)}">${esc(label)}</button>`; }
function positionBadge(v) { return `<span class="position-badge ${positionClass(v)}">${esc(pos(v))}</span>`; }
function overallBadge(v) { return `<span class="overall-badge ${overallClass(v)}">${num(v)}</span>`; }
function potentialRangeBadge(low, high) {
    const lo = Number(low), hi = Number(high);
    if (!Number.isFinite(lo) && !Number.isFinite(hi))
        return "–";
    const a = Number.isFinite(lo) ? lo : hi, b = Number.isFinite(hi) ? hi : lo;
    if (a === b)
        return `<span class="potential-range single">${overallBadge(a)}</span>`;
    return `<span class="potential-range">${overallBadge(a)}<span class="range-separator">–</span>${overallBadge(b)}</span>`;
}
function nationalityFlag(nationality, cls = "nationality-flag") {
    if (!nationality)
        return "";
    const isSmall = String(cls || "").includes("small");
    const frameClass = `nationality-flag-frame${isSmall ? " small" : ""}`;
    const visual = nationality.flagUrl
        ? `<span class="${frameClass}"><img class="${esc(cls)}" src="${esc(nationality.flagUrl)}" alt="${esc(nationality.name || "Nationality")}" loading="lazy"></span>`
        : `<span class="${frameClass}"><span class="flag-fallback ${esc(cls)}">${esc((nationality.isoCode || nationality.flagCode || "–").slice(0, 3))}</span></span>`;
    return `<span class="nationality-chip">${visual}<span>${esc(nationality.name || "Unknown")}</span></span>`;
}
function statusBadge(text, cls = "") { return `<span class="status-badge ${cls}">${esc(text)}</span>`; }
function pageHead(title, subtitle, actions = "") { return `<div class="page-head"><div class="page-head-copy"><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="page-actions">${actions}</div></div>`; }
function metric(label, value, note = "", cls = "") { return `<div class="card metric-card"><span class="metric-label">${esc(label)}</span><strong class="metric-value ${cls}">${value}</strong><small class="metric-note">${esc(note)}</small></div>`; }
function emptyState(title, text, action = "") { return `<div class="card empty"><div><div class="empty-icon" data-icon="empty"></div><h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div></div>`; }
function errorState(title, text) { return `<div class="content-inner">${pageHead(title, "Loading error")}<div class="card empty error-card"><div><h2>${esc(title)}</h2><p>${esc(text)}</p></div></div></div>`; }
function card(title, body, extra = "") { return `<section class="card"><header class="card-header"><div><h2>${esc(title)}</h2>${extra}</div></header><div class="card-body">${body}</div></section>`; }
let tableSequence = 0;
function table(headers, rows, classes = "") { const tableId = `atlas-table-${++tableSequence}`; const body = Array.isArray(rows) ? rows.join("") : typeof rows === "string" ? rows : ""; return `<div class="table-wrap"><table id="${tableId}" class="data-table sortable-table ${classes}"><thead><tr>${headers.map((h, index) => `<th class="${h.cls || ""}" data-column="${index}" data-sortable="${h.sortable === false || !h.label ? "0" : "1"}">${h.sortable === false || !h.label ? esc(h.label) : `<button class="sort-button" type="button">${esc(h.label)}<span class="sort-indicator">↕</span></button>`}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`; }
function parseSortValue(cell) {
    const explicit = cell.dataset.sort;
    if (explicit !== undefined) {
        const numeric = Number(explicit);
        return explicit !== "" && Number.isFinite(numeric) ? { type: "number", value: numeric } : { type: "text", value: explicit };
    }
    const raw = (cell.textContent || "").trim();
    if (!raw || raw === "–" || raw === "Not recorded")
        return { type: "empty", value: null };
    const dateMatch = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (dateMatch)
        return { type: "number", value: Number(`${dateMatch[3]}${dateMatch[2].padStart(2, "0")}${dateMatch[1].padStart(2, "0")}`) };
    const moneyMatch = raw.replaceAll(",", "").match(/^€?([+-]?[\d.]+)\s*([mk])?$/i);
    if (moneyMatch) {
        let value = Number(moneyMatch[1]);
        if (/m/i.test(moneyMatch[2] || ""))
            value *= 1e6;
        if (/k/i.test(moneyMatch[2] || ""))
            value *= 1e3;
        return { type: "number", value };
    }
    const normalized = raw.replace(/^#/, "").replace(/\s*(months|apps|matches|G|A)$/i, "").replaceAll(",", "");
    if (/^[+-]?\d+(?:\.\d+)?$/.test(normalized))
        return { type: "number", value: Number(normalized) };
    return { type: "text", value: raw.toLocaleLowerCase("en-GB") };
}
function bindSortableTables() {
    $$("table.sortable-table", content).forEach((tableEl) => {
        const tbody = $("tbody", tableEl);
        if (!tbody)
            return;
        const original = [...tbody.rows];
        original.forEach((row, index) => row.dataset.originalIndex = String(index));
        $$("th[data-sortable='1']", tableEl).forEach((th) => {
            th.onclick = () => {
                const column = Number(th.dataset.column);
                const previousColumn = Number(tableEl.dataset.sortColumn ?? -1);
                const previousDirection = tableEl.dataset.sortDirection || "none";
                let direction = previousColumn !== column ? "asc" : previousDirection === "asc" ? "desc" : previousDirection === "desc" ? "none" : "asc";
                tableEl.dataset.sortColumn = String(column);
                tableEl.dataset.sortDirection = direction;
                $$("th", tableEl).forEach((header) => {
                    header.classList.remove("sort-asc", "sort-desc");
                    const indicator = $(".sort-indicator", header);
                    if (indicator)
                        indicator.textContent = "↕";
                });
                if (direction === "none") {
                    original.sort((a, b) => Number(a.dataset.originalIndex) - Number(b.dataset.originalIndex)).forEach((row) => tbody.appendChild(row));
                    return;
                }
                th.classList.add(direction === "asc" ? "sort-asc" : "sort-desc");
                const indicator = $(".sort-indicator", th);
                if (indicator)
                    indicator.textContent = direction === "asc" ? "↑" : "↓";
                const rows = [...tbody.rows];
                rows.sort((a, b) => {
                    const av = parseSortValue(a.cells[column]), bv = parseSortValue(b.cells[column]);
                    if (av.type === "empty" && bv.type === "empty")
                        return 0;
                    if (av.type === "empty")
                        return 1;
                    if (bv.type === "empty")
                        return -1;
                    let result = 0;
                    if (av.type === "number" && bv.type === "number")
                        result = Number(av.value) - Number(bv.value);
                    else
                        result = String(av.value).localeCompare(String(bv.value), "en", { numeric: true, sensitivity: "base" });
                    return direction === "asc" ? result : -result;
                });
                rows.forEach((row) => tbody.appendChild(row));
            };
        });
    });
}
function ratingValue(value, average = false) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0)
        return "–";
    if (average)
        return num(n, 2);
    return Number.isInteger(n) ? num(n, 0) : num(n, 1);
}
function delta(v) { const n = Number(v) || 0; return `<span class="delta ${n > 0 ? "pos positive" : n < 0 ? "negative" : "muted"}">${n > 0 ? num(n) : num(n)}</span>`; }
function clearApiCache() { apiCache.clear(); }
function cacheableApiPath(path, options) {
    const method = String(options?.method || "GET").toUpperCase();
    if (method !== "GET")
        return false;
    return /^\/api\/snapshots\/\d+\/(competitions\/\d+|world-leagues\/\d+|players\/\d+|clubs\/\d+|matches(?:\/\d+)?)$/.test(path);
}
async function api(path, options) {
    const cacheable = cacheableApiPath(path, options);
    const cached = cacheable ? apiCache.get(path) : null;
    if (cached && Date.now() - cached.time < 300000)
        return cached.value;
    const request = (async () => {
        const r = await fetch(path, { headers: { "Content-Type": "application/json", ...(options?.headers || {}) }, ...options });
        const p = await r.json().catch(() => ({}));
        if (!r.ok)
            throw new Error(p.error || `HTTP ${r.status}`);
        return p;
    })();
    if (cacheable)
        apiCache.set(path, { time: Date.now(), value: request });
    try {
        return await request;
    }
    catch (error) {
        if (cacheable)
            apiCache.delete(path);
        throw error;
    }
}
function toast(message) { toastEl.textContent = message; toastEl.classList.add("show"); setTimeout(() => toastEl.classList.remove("show"), 2600); }
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
        state.status = await api("/api/status");
        applyAtlasLanguage();
        state.careers = await api("/api/careers");
        if (state.careers.length) {
            state.careerId = Number(state.careers[0].id);
            await loadSnapshots();
        }
        fillSelectors();
        updateSystemUi();
        if (initialView === "commission")
            state.analysisTab = "commission";
        navigate(initialView === "commission" ? "commission" : "overview", {}, true);
    }
    catch (e) {
        content.innerHTML = errorState("Application could not be loaded", e.message);
    }
    if (!new URLSearchParams(location.search).has("static"))
        setInterval(pollStatus, 5000);
}
async function loadSnapshots(preserve = false) {
    if (!state.careerId) {
        state.snapshots = [];
        state.careerClock = null;
        state.snapshotId = null;
        return;
    }
    const old = state.snapshotId;
    const [snapshots, clock] = await Promise.all([
        api(`/api/careers/${state.careerId}/snapshots`),
        api(`/api/careers/${state.careerId}/clock`),
    ]);
    state.snapshots = snapshots;
    state.careerClock = clock;
    state.snapshotId = preserve && state.snapshots.some((s) => Number(s.id) === Number(old)) ? old : (state.snapshots.length ? Number(state.snapshots[0].id) : null);
    state.compareFrom = state.snapshots.length > 1 ? Number(state.snapshots.at(-1)?.id) : state.snapshotId;
    state.compareTo = state.snapshotId;
}
function currentCareer() { return state.careers.find((c) => Number(c.id) === Number(state.careerId)); }
function currentSnapshot() { return state.snapshots.find((s) => Number(s.id) === Number(state.snapshotId)); }
function fillSelectors() {
    careerSelect.innerHTML = state.careers.length ? state.careers.map((c) => `<option value="${c.id}">${esc(c.initial_team_name || c.display_name)}</option>`).join("") : '<option>No career</option>';
    if (state.careerId)
        careerSelect.value = String(state.careerId);
    snapshotSelect.innerHTML = state.snapshots.length ? state.snapshots.map((s) => {
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
    }
    else {
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
function navigate(route, data = {}, push = true) {
    if (push) {
        state.history = state.history.slice(0, state.historyIndex + 1);
        state.history.push({ route, data: { ...data } });
        state.historyIndex = state.history.length - 1;
    }
    state.route = route;
    state.routeData = { ...data };
    setActiveNav();
    renderBreadcrumbs();
    render().catch((e) => content.innerHTML = errorState("Page could not be loaded", e.message));
}
function goHistory(delta) {
    const next = state.historyIndex + delta;
    if (next < 0 || next >= state.history.length)
        return;
    state.historyIndex = next;
    const e = state.history[next];
    state.route = e.route;
    state.routeData = { ...(e.data || {}) };
    setActiveNav();
    renderBreadcrumbs();
    render().catch((err) => content.innerHTML = errorState("Page could not be loaded", err.message));
}
function setActiveNav() { const map = { player: "squad", club: "overview", match: "match-center", competition: "competitions", "world-competition": "competitions" }; const active = map[state.route] || state.route; $$('#mainNav [data-route]').forEach((n) => n.classList.toggle("active", n.dataset.route === active)); }
function renderBreadcrumbs() { const labels = { overview: tr("crumbOverview"), "match-center": tr("crumbMatches"), schedule: tr("navSchedule"), results: tr("navResults"), match: tr("crumbMatch"), competitions: tr("navCompetitions"), competition: tr("navCompetitions"), "world-competition": tr("navCompetitions"), squad: tr("crumbSquad"), player: tr("crumbPlayer"), club: tr("crumbOverview"), contracts: tr("navContracts"), loans: tr("navLoans"), transfers: tr("navTransfers"), youth: tr("navYouth"), compare: tr("navCompare"), chronology: tr("navChronology"), "manual-data": tr("navManual"), analysis: tr("crumbAnalysis"), commission: tr("crumbCommission"), records: tr("navRecords"), "season-report": tr("navSeasonReport"), snapshots: tr("navSnapshots"), imports: tr("navImports"), media: tr("navMedia"), setup: tr("crumbSetup") }; const club = currentSnapshot()?.managed_team_name || currentCareer()?.initial_team_name || "Career"; $("#breadcrumbs").innerHTML = `<button data-crumb="overview">${esc(club)}</button><span>›</span><b>${labels[state.route] || esc(state.route)}</b>`; $$('[data-crumb]').forEach((b) => b.onclick = () => navigate(b.dataset.crumb || "overview")); }
async function refreshCareerBootstrap(preserveSnapshot = true) {
    state.status = await api("/api/status");
    state.careers = await api("/api/careers");
    const currentStillExists = state.careers.some((career) => Number(career.id) === Number(state.careerId));
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
    const routes = { overview: renderOverview, analysis: renderAnalysis, commission: renderAnalysis, records: renderRecords, "season-report": renderSeasonReport, squad: renderSquad, "match-center": renderMatchCenter, schedule: () => renderMatchList("schedule"), results: () => renderMatchList("results"), match: renderMatch, competitions: renderCompetitions, competition: renderCompetition, "world-competition": renderWorldCompetition, contracts: renderContracts, loans: renderLoans, transfers: renderTransfers, youth: renderYouth, compare: renderCompare, chronology: renderChronology, "manual-data": renderManualData, snapshots: renderSnapshots, imports: renderImports, media: renderMedia, setup: renderSetup, player: renderPlayer, club: renderClub };
    await (routes[state.route] || renderOverview)();
    content.scrollTop = 0;
    applyIcons(content);
    bindContent();
}
function renderNoData() { const configured = Boolean(state.status?.snapshotRoot); content.innerHTML = `<div class="content-inner">${pageHead("Welcome to Project Atlas Tracker", "FC26 career statistics and world tracking")}${emptyState(configured ? "No career imported yet" : "Set up the snapshot folder", configured ? "Place a complete export in the ready folder and start a scan." : "Choose the shared root folder used by the LUA exporter and Project Atlas Tracker.", `<button class="button primary" data-action="${configured ? "scan" : "setup"}">${configured ? "Scan now" : "Open setup"}</button>`)}</div>`; applyIcons(content); bindContent(); }
function renderMatchRows(rows, limit = Infinity) {
    if (!rows.length)
        return `<div class="muted" style="font-size:11px;padding:12px">No matches available.</div>`;
    return rows.slice(0, limit).map((m) => `<div class="match-card" data-match="${m.fixture_id}"><div class="match-date"><strong>${dateText(m.date)}</strong>${esc(timeText(m.time))}<br><span class="inline-identity">${m.competitionIdentity ? identityLogo(m.competitionIdentity, m.competition_name, "inline-logo") : ""}${competitionLink(m.competition_object_id, m.competition_name)}</span>${m.detailedStatsAvailable ? `<br><span class="status-badge good match-detail-badge">Detailed FC26 data</span>` : ""}</div><div class="match-teams"><div class="match-team"><span class="inline-identity">${identityLogo(m.homeIdentity, m.home_team_name, "match-logo-small")}${clubLink(m.home_team_ea_id, m.home_team_name)}</span><b>${m.is_completed ? num(m.home_score) : ""}</b></div><div class="match-team"><span class="inline-identity">${identityLogo(m.awayIdentity, m.away_team_name, "match-logo-small")}${clubLink(m.away_team_ea_id, m.away_team_name)}</span><b>${m.is_completed ? num(m.away_score) : ""}</b></div></div><div class="score">${m.is_completed ? resultPill(m.managed_team_result) : matchLink(m.fixture_id, "Open")}</div></div>`).join("");
}
function lineChart(points, keys = ["overall", "potential"], options = {}) {
    if (!points?.length)
        return '<div class="muted">Not enough data points yet.</div>';
    const W = 720, H = 250, left = 54, right = 22, top = 28, bottom = 50;
    const values = points.flatMap((p) => keys.map((k) => Number(p[k])).filter(Number.isFinite));
    if (!values.length)
        return '<div class="muted">No values are available for this chart.</div>';
    const rawMin = Math.min(...values), rawMax = Math.max(...values);
    const margin = options.margin ?? Math.max(options.decimals ? .5 : 2, (rawMax - rawMin) * .12);
    const min = options.min ?? Math.max(0, rawMin - margin), max = options.max ?? rawMax + margin, span = Math.max(.1, max - min);
    const x = (i) => left + i * (W - left - right) / Math.max(1, points.length - 1);
    const y = (value) => top + (max - value) * (H - top - bottom) / span;
    const decimals = Number(options.decimals ?? 1);
    const format = (value) => options.format === "money" ? money(value) : `${num(value, decimals)}${options.unit || ""}`;
    const ticks = Array.from({ length: 5 }, (_, i) => max - i * span / 4);
    const labelsEvery = Math.max(1, Math.ceil(points.length / 7));
    const lines = keys.map((key, series) => {
        const coords = points.map((point, index) => ({ point, index, value: Number(point[key]) })).filter((item) => Number.isFinite(item.value));
        return `<polyline class="chart-line ${series ? "secondary" : ""}" points="${coords.map((item) => `${x(item.index)},${y(item.value)}`).join(" ")}"/>${coords.map((item) => `<circle class="chart-point ${series ? "secondary" : ""}" cx="${x(item.index)}" cy="${y(item.value)}" r="4"><title>${esc(item.point.season_label || item.point.career_date || item.point.effective_date || "")}: ${esc(format(item.value))}</title></circle><text class="chart-value-label ${series ? "secondary" : ""}" x="${x(item.index)}" y="${y(item.value) - (series ? -16 : 10)}" text-anchor="middle">${esc(format(item.value))}</text>`).join("")}`;
    }).join("");
    return `<div class="chart analysis-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(options.ariaLabel || "Timeline")}">${ticks.map(t => `<line class="chart-grid-line" x1="${left}" y1="${y(t)}" x2="${W - right}" y2="${y(t)}"/><text class="chart-axis-label" x="${left - 8}" y="${y(t) + 4}" text-anchor="end">${esc(format(t))}</text>`).join("")}${lines}${points.map((point, index) => index % labelsEvery === 0 || index === points.length - 1 ? `<text class="chart-axis-label" x="${x(index)}" y="${H - 15}" text-anchor="middle">${esc(point.season_label || dateText(point.career_date || point.effective_date))}</text>` : "").join("")}</svg></div>`;
}
async function renderOverview() {
    const d = await api(`/api/snapshots/${state.snapshotId}/dashboard`), team = d.team || {}, snap = d.snapshot, league = d.leagueState || {}, strength = d.squadStrength || {};
    content.innerHTML = `<div class="content-inner">${pageHead("Career dashboard", `${dateText(snap.career_date)} · ${esc(snap.season_label || "Season unknown")}${snap.career_season_number ? ` · Career season ${num(snap.career_season_number)}` : ""}`, `<button class="button" data-route="chronology">Career timeline</button><button class="button" data-route="compare">Compare snapshots</button><button class="button primary" data-route="match-center">Match Center</button>`)}
      <div class="grid metrics">${metric("Squad OVR", strength.overall == null ? "–" : num(strength.overall, 2), `${num(strength.overallSum)} OVR ÷ ${num(strength.playerCount)} first-team players`)}${metric("League position", league.current_table_position ? `#${num(league.current_table_position)}` : "–", `${team.league_name || "League"}${league.position_source_label ? ` · ${league.position_source_label}` : ""}`, "green")}${metric("Squad", num(d.squadCount), "players in the current roster")}${metric("Club value", money(team.club_worth), "snapshot value", "blue")}${metric("Weekly payroll", money(d.contractSummary?.wage_total), `${num(d.contractSummary?.count)} contracts`, "amber")}</div>
      <div class="data-note"><b>Squad OVR:</b> ${esc(strength.formula || "Average OVR of the current first-team squad")}. The EA base team rating${strength.eaBaseOverall == null ? "" : ` ${num(strength.eaBaseOverall)}`} is not used.</div>
      <div class="grid dashboard-layout"><div class="dashboard-main"><section class="card hero identity-hero" ${identityStyle(d.teamIdentity)}><div class="hero-content">${identityLogo(d.teamIdentity, team.team_name, "hero-club-logo")}<div class="hero-copy"><p>CURRENT CLUB</p><h1>${clubLink(team.ea_team_id, team.team_name)}</h1><p>${esc(team.league_name || "League unavailable")} · Manager ${esc(snap.manager_name || "–")}</p><div class="hero-meta"><span class="chip accent">Snapshot ${esc(snap.external_snapshot_id)}</span><span class="chip">EA Team ID ${num(team.ea_team_id)}</span><span class="chip">${num(d.completedMatches)} completed matches</span></div></div></div></section>
      <div class="grid two-col"><section class="card"><header class="card-header"><h2>Recent matches</h2><button class="entity-link" data-route="results">All results</button></header>${renderMatchRows(d.recent, 5)}</section><section class="card"><header class="card-header"><h2>Upcoming matches</h2><button class="entity-link" data-route="schedule">Full schedule</button></header>${renderMatchRows(d.upcoming, 5)}</section></div>
      <section class="card"><header class="card-header"><h2>Competitions</h2><button class="entity-link" data-route="competitions">Open all</button></header><div class="card-body grid competition-grid">${d.competitions.length ? d.competitions.map((c) => `<button class="competition-card card" data-competition="${c.competition_object_id}"><div class="competition-top">${identityLogo(c.identity, c.competition_name, "competition-logo-card")}<div><h3>${esc(c.competition_name)}</h3><p>${num(c.played)} played · ${num(c.upcoming)} remaining</p></div></div></button>`).join("") : '<span class="muted">No competitions available.</span>'}</div></section></div>
      <aside class="dashboard-side"><section class="card"><header class="card-header"><h2>Top players</h2><button class="entity-link" data-route="squad">Squad</button></header><div class="card-body list">${d.topPlayers.map((p) => `<div class="list-row">${playerPortrait(p.media, p.display_name, "list-portrait")}<div class="list-main">${playerLink(p.ea_player_id, p.display_name)}<small>${pos(p.primary_position)} · #${num(p.jersey_number)}</small></div>${overallBadge(p.overall)}</div>`).join("")}</div></section><section class="card"><header class="card-header"><h2>Top scorers</h2></header><div class="card-body list">${d.leaders.map((p) => `<div class="list-row"><div class="list-main">${playerLink(p.player_ea_id, p.display_name)}<small>${num(p.appearances)} apps · ${ratingValue(p.average_rating, true)} avg.</small></div><div class="list-value"><strong>${num(p.goals)} G</strong><small>${num(p.assists)} A</small></div></div>`).join("") || '<span class="muted">No season statistics.</span>'}</div></section><section class="card"><header class="card-header"><h2>Snapshot timeline</h2><button class="entity-link" data-route="snapshots">Open</button></header><div class="card-body timeline">${d.timeline.slice(-6).reverse().map((s) => `<div class="timeline-item ${Number(s.id) === Number(state.snapshotId) ? "current" : ""}"><h3>${dateText(s.career_date)}</h3><p>${esc(s.season_label || "Season unknown")}${s.career_season_number ? ` · Career season ${num(s.career_season_number)}` : ""} · Sequence ${num(s.import_sequence)}</p></div>`).join("")}</div></section></aside></div></div>`;
}
async function renderSquad() {
    const d = await api(`/api/snapshots/${state.snapshotId}/squad`);
    const positions = [...new Set(d.players.map((p) => pos(p.primary_position)))].sort((a, b) => positionOrder(a) - positionOrder(b));
    let rows = d.players.filter((p) => (state.squadPosition === "all" || pos(p.primary_position) === state.squadPosition)
        && (!state.squadQuery || p.display_name.toLowerCase().includes(state.squadQuery.toLowerCase())));
    const sorters = {
        number: (a, b) => (a.jersey_number || 999) - (b.jersey_number || 999),
        position: (a, b) => positionOrder(a.primary_position, a.raw?.primary_position_id || a.primary_position_id) - positionOrder(b.primary_position, b.raw?.primary_position_id || b.primary_position_id) || (b.overall || 0) - (a.overall || 0) || a.display_name.localeCompare(b.display_name, "en"),
        overall: (a, b) => (b.overall || 0) - (a.overall || 0),
        potential: (a, b) => (b.potential || 0) - (a.potential || 0),
        age: (a, b) => (a.age ?? 999) - (b.age ?? 999) || a.display_name.localeCompare(b.display_name, "en"),
        name: (a, b) => a.display_name.localeCompare(b.display_name, "en"),
    };
    rows.sort(sorters[state.squadSort] || sorters.position);
    content.innerHTML = `<div class="content-inner wide">${pageHead("Squad", `${num(rows.length)} of ${num(d.players.length)} players · ${esc(d.team?.team_name || "")}`, `<button class="button" data-route="contracts">Contracts</button><button class="button" data-route="loans">Loans</button><button class="button primary" data-route="youth">FC26 youth</button>`)}
      <div class="filter-row"><input class="filter-input" id="squadQuery" value="${esc(state.squadQuery)}" placeholder="Search players…"><select class="filter-select" id="squadPosition"><option value="all">All positions</option>${positions.map((p) => `<option ${p === state.squadPosition ? "selected" : ""}>${esc(p)}</option>`).join("")}</select><select class="filter-select" id="squadSort"><option value="number" ${state.squadSort === "number" ? "selected" : ""}>By shirt number</option><option value="position" ${state.squadSort === "position" ? "selected" : ""}>By position</option><option value="overall" ${state.squadSort === "overall" ? "selected" : ""}>By OVR</option><option value="potential" ${state.squadSort === "potential" ? "selected" : ""}>By POT</option><option value="age" ${state.squadSort === "age" ? "selected" : ""}>By age</option><option value="name" ${state.squadSort === "name" ? "selected" : ""}>By name</option></select></div>
      <section class="card">${table([{ label: "#", cls: "center" }, { label: "Player" }, { label: "Age", cls: "center" }, { label: "Pos.", cls: "center" }, { label: "OVR", cls: "center" }, { label: "POT", cls: "center" }, { label: "Est. value", cls: "num" }, { label: "Apps", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "Avg", cls: "num" }, { label: "Est. wage", cls: "num" }, { label: "Contract", cls: "center" }, { label: "Status" }], rows.map((p) => `<tr><td class="center"><b>${p.jersey_number ? num(p.jersey_number) : "–"}</b></td><td><div class="player-line">${playerPortrait(p.media, p.display_name, "table-portrait")}<div class="player-line-copy">${playerLink(p.ea_player_id, p.display_name)}<small>${p.is_captain ? "Captain · " : ""}EA ID ${num(p.ea_player_id)}</small></div></div></td><td class="center" data-sort="${p.age ?? 999}">${p.age == null ? "–" : num(p.age)}</td><td class="center" data-sort="${positionOrder(p.primary_position, p.raw?.primary_position_id || p.primary_position_id)}">${positionBadge(p.primary_position)}</td><td class="center">${overallBadge(p.overall)}</td><td class="center">${overallBadge(p.potential)}</td><td class="num" title="${financialHint(p.financial, "market")}">${money(p.market_value)}</td><td class="num">${num(p.appearances)}</td><td class="num">${num(p.goals)}</td><td class="num">${num(p.assists)}</td><td class="num">${ratingValue(p.average_rating, true)}</td><td class="num" title="${financialHint(p.financial, "wage")}">${money(p.weekly_wage)}</td><td class="center">${esc(p.contract_valid_until || "–")}</td><td>${p.injury ? statusBadge("Injured", "bad") : p.is_on_loan ? statusBadge("On loan") : statusBadge("Available", "good")}${p.is_captain ? ` ${statusBadge("Captain", "blue")}` : ""}</td></tr>`))}</section>
    </div>`;
    const q = $("#squadQuery", content), pp = $("#squadPosition", content), ss = $("#squadSort", content);
    q.oninput = () => { state.squadQuery = q.value; render(); };
    pp.onchange = () => { state.squadPosition = pp.value; render(); };
    ss.onchange = () => { state.squadSort = ss.value; render(); };
}
function leaguePositionChart(points) {
    if (!points?.length)
        return '<div class="muted">No league history available yet.</div>';
    const hasLevel = (value) => Number.isInteger(Number(value)) && Number(value) > 0;
    const known = points.filter(p => hasLevel(p.league_level));
    if (!known.length)
        return '<div class="muted">No reliable league tier is recorded for the available leagues.</div>';
    const W = 760, H = Math.max(250, 112 + new Set(known.map(p => Number(p.league_level))).size * 64), left = 165, right = 32, top = 42, bottom = 62;
    const levels = [...new Set(known.map(p => Number(p.league_level)))].sort((a, b) => a - b);
    const x = (i) => left + i * (W - left - right) / Math.max(1, points.length - 1);
    const lane = (level) => top + levels.indexOf(level) * (H - top - bottom) / Math.max(1, levels.length - 1);
    const coords = points.map((p, i) => hasLevel(p.league_level) ? { p, i, x: x(i), y: lane(Number(p.league_level)) } : null).filter(Boolean);
    const leagueAtLevel = (level) => [...known].reverse().find(p => Number(p.league_level) === level)?.league_name || "League";
    let path = "";
    coords.forEach((c, index) => { if (index === 0)
        path = `M ${c.x} ${c.y}`;
    else
        path += ` H ${c.x} V ${c.y}`; });
    return `<div class="chart analysis-chart league-journey-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="League path and season positions">
      ${levels.map(level => `<line class="chart-grid-line" x1="${left}" y1="${lane(level)}" x2="${W - right}" y2="${lane(level)}"/><text class="chart-axis-label league-lane-label" x="${left - 12}" y="${lane(level) + 4}" text-anchor="end">${esc(leagueAtLevel(level))}</text>`).join("")}
      <path class="chart-line league-step-line" d="${path}" fill="none"/>
      ${coords.map(c => { const result = String(c.p.position_display || "–"); const badgeWidth = Math.max(34, Math.min(92, 16 + result.length * 6.2)); return `<circle class="chart-point" cx="${c.x}" cy="${c.y}" r="7"><title>${esc(c.p.season_label)} · ${esc(c.p.league_name)} · ${esc(result)}</title></circle><g class="league-position-badge"><rect x="${c.x - badgeWidth / 2}" y="${c.y - 37}" width="${badgeWidth}" height="22" rx="11"></rect><text x="${c.x}" y="${c.y - 22}" text-anchor="middle">${esc(result)}</text></g><text class="chart-axis-label" x="${c.x}" y="${H - 18}" text-anchor="middle">${esc(c.p.season_label)}</text>`; }).join("")}
    </svg><p class="chart-note">The line shows the league path. The number at each point is the final position or current table position.</p></div>`;
}
function horizontalBars(items, valueKey = "count", labelKey = "label", suffix = "") {
    if (!items?.length)
        return '<div class="muted">No data in the selected period.</div>';
    const max = Math.max(1, ...items.map(item => Number(item[valueKey]) || 0));
    return `<div class="horizontal-bars">${items.map(item => {
        const value = Number(item[valueKey]) || 0;
        const width = Math.max(value > 0 ? 4 : 0, value / max * 100);
        return `<div class="horizontal-bar-row"><div class="horizontal-bar-label"><span>${esc(item[labelKey] || "–")}</span><b>${num(value)}${esc(suffix)}</b></div><div class="horizontal-bar-track"><i style="width:${width}%"></i></div>${item.average_overall != null ? `<small>Avg. OVR ${num(item.average_overall, 1)}</small>` : ""}</div>`;
    }).join("")}</div>`;
}
function simpleBarChart(points, keys) {
    if (!points?.length)
        return '<div class="muted">No data in the selected period.</div>';
    const W = 720, H = 230, left = 40, right = 18, top = 24, bottom = 46;
    const max = Math.max(1, ...points.flatMap(p => keys.map(k => Number(p[k.key]) || 0)));
    const groupWidth = (W - left - right) / Math.max(1, points.length);
    const barWidth = Math.max(7, Math.min(24, (groupWidth - 10) / Math.max(1, keys.length)));
    const y = (value) => top + (max - value) * (H - top - bottom) / max;
    return `<div class="chart analysis-chart"><svg viewBox="0 0 ${W} ${H}">
      <line class="chart-grid-line" x1="${left}" y1="${H - bottom}" x2="${W - right}" y2="${H - bottom}"/>
      ${points.map((p, i) => {
        const center = left + groupWidth * i + groupWidth / 2;
        const bars = keys.map((key, ki) => {
            const value = Number(p[key.key]) || 0;
            const x = center - (keys.length * barWidth) / 2 + ki * barWidth;
            return `<rect class="chart-bar series-${ki}" x="${x}" y="${y(value)}" width="${Math.max(4, barWidth - 2)}" height="${H - bottom - y(value)}"><title>${esc(p.season_label)} · ${esc(key.label)}: ${num(value)}</title></rect>`;
        }).join("");
        return `${bars}<text class="chart-axis-label" x="${center}" y="${H - 14}" text-anchor="middle">${esc(p.season_label)}</text>`;
    }).join("")}
    </svg><div class="chart-legend">${keys.map((k, i) => `<span><i class="series-${i}"></i>${esc(k.label)}</span>`).join("")}</div></div>`;
}
function radarChart(points) {
    const rows = (points || []).filter(point => Number.isFinite(Number(point.value))).slice(0, 8);
    if (rows.length < 3)
        return '<div class="muted">Not enough attributes are available for a profile yet.</div>';
    const W = 760, H = 560, cx = 380, cy = 272, radius = 188;
    const angle = (index) => -Math.PI / 2 + index * Math.PI * 2 / rows.length;
    const xy = (index, factor) => ({ x: cx + Math.cos(angle(index)) * radius * factor, y: cy + Math.sin(angle(index)) * radius * factor });
    const polygon = (factor) => rows.map((_, index) => { const p = xy(index, factor); return `${p.x},${p.y}`; }).join(" ");
    const valuePolygon = rows.map((row, index) => { const p = xy(index, Math.max(0, Math.min(100, Number(row.value))) / 100); return `${p.x},${p.y}`; }).join(" ");
    return `<div class="chart player-radar-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Attribute profile">
      ${[.25, .5, .75, 1].map(level => `<polygon class="radar-grid" points="${polygon(level)}"></polygon>`).join("")}
      ${rows.map((_, index) => { const p = xy(index, 1); return `<line class="radar-axis" x1="${cx}" y1="${cy}" x2="${p.x}" y2="${p.y}"></line>`; }).join("")}
      <polygon class="radar-value" points="${valuePolygon}"></polygon>
      ${rows.map((row, index) => { const p = xy(index, 1.14); return `<text class="radar-label" x="${p.x}" y="${p.y}" text-anchor="middle"><tspan x="${p.x}">${esc(row.label)}</tspan><tspan class="radar-number" x="${p.x}" dy="14">${num(row.value, 1)}</tspan></text>`; }).join("")}
    </svg></div>`;
}
function recordCatalog(records) {
    const playerRows = records?.playerRecords || [];
    const positionRows = records?.positionRecords || [];
    const matchRows = records?.matchRecords || [];
    const streakRows = records?.streakRecords || [];
    const transferRows = records?.transferRecords || [];
    const recordValue = (row) => row.value_type === "money" ? money(row.value) : row.value_type === "rating" ? ratingValue(row.value, true) : row.value_type === "rate" ? `${num(row.value, 2)} / Match` : row.value_type === "text" ? esc(row.value) : num(row.value);
    const playerTable = playerRows.length ? table([
        { label: "Record" }, { label: "Player" }, { label: "Value", cls: "num" }, { label: "appearances", cls: "num" }
    ], playerRows.map((row) => `<tr><td><strong>${esc(row.label)}</strong></td><td>${row.player_ea_id ? playerLink(row.player_ea_id, row.display_name) : esc(row.display_name || "–")}</td><td class="num"><strong>${recordValue(row)}</strong></td><td class="num">${row.appearances != null ? num(row.appearances) : "–"}</td></tr>`)) : '<div class="card-body"><span class="muted">No player records available.</span></div>';
    const positionTable = positionRows.length ? `<div class="position-record-grid">${positionRows.map((group) => `<section class="position-record-card"><h3>${esc(group.group)}</h3>${table([{ label: "Record" }, { label: "Player" }, { label: "Value", cls: "num" }], (group.records || []).map((row) => `<tr><td>${esc(row.label)}</td><td>${row.player_ea_id ? playerLink(row.player_ea_id, row.display_name) : esc(row.display_name || "–")}</td><td class="num"><strong>${recordValue(row)}</strong></td></tr>`))}</section>`).join("")}</div>` : '<span class="muted">No position records available.</span>';
    const eventCards = [...matchRows, ...transferRows].map((row) => `<div class="record-card"><span>${esc(row.label)}</span><strong>${recordValue(row)}</strong><small>${row.display_name ? (row.player_ea_id ? playerLink(row.player_ea_id, row.display_name) : esc(row.display_name)) : row.fixture_id ? matchLink(row.fixture_id, row.opponent ? `vs ${row.opponent}` : "Open match") : esc(row.opponent || "")}${row.date ? ` · ${dateText(row.date)}` : ""}${row.competition_name ? ` · ${esc(row.competition_name)}` : ""}</small></div>`).join("");
    const streakCards = streakRows.map((row) => `<div class="record-card"><span>${esc(row.label)}</span><strong>${num(row.value)} matches</strong><small>${row.start_date ? `${dateText(row.start_date)} to ${dateText(row.end_date)}` : ""}</small></div>`).join("");
    return `<section class="card records-section"><header class="card-header"><h2>Records</h2><span>${esc(records?.periodLabel || "selected period")}</span></header><div class="records-grid"><div>${playerTable}</div><div class="record-card-grid">${eventCards || '<span class="muted">No match or transfer records available.</span>'}${streakCards}</div></div><section class="position-records"><div class="card-title-row"><h3 class="card-title">Position records</h3><span>within position groups</span></div>${positionTable}</section><div class="record-notes">${(records?.notes || []).map((note) => `<span>${esc(note)}</span>`).join("")}</div></section>`;
}
function qualityPanel(quality) {
    const icon = (level) => level === "good" ? "✓" : level === "warn" ? "!" : "i";
    return `<section class="card pad"><h3 class="card-title">Data quality</h3><div class="quality-list">${(quality?.items || []).map((item) => `<div class="quality-item ${esc(item.level)}"><b>${icon(item.level)}</b><span>${esc(item.label)}</span></div>`).join("")}</div></section>`;
}
function periodPicker(options, selected, attribute) {
    const dataAttribute = attribute === "records" ? "data-records-season" : "data-analysis-season";
    return `<label class="page-filter"><span>Period</span><select ${dataAttribute}><option value="-1" ${selected === -1 ? "selected" : ""}>All seasons</option>${options.map((option) => `<option value="${option.season_index}" ${Number(option.season_index) === Number(selected) ? "selected" : ""}>${esc(option.label)}${option.is_current ? " · current" : ""}</option>`).join("")}</select></label>`;
}
function analysisTabs(active) {
    return `<div class="page-tabs analysis-tabs"><button class="${active === "overview" ? "active" : ""}" data-analysis-tab="overview">Overview</button><button class="${active === "performance" ? "active" : ""}" data-analysis-tab="performance">Match data</button><button class="${active === "commission" ? "active" : ""}" data-analysis-tab="commission">Technical commission</button><button class="${active === "squad" ? "active" : ""}" data-analysis-tab="squad">Squad analysis</button><button class="${active === "seasons" ? "active" : ""}" data-analysis-tab="seasons">Season comparison</button></div>`;
}
function technicalCommission(d, reportCache = null) {
    const coverage = d?.coverage || {}, players = d?.players || [];
    const briefing = d?.briefingOptions || {}, completedMatches = briefing.matches || [], upcomingMatches = briefing.upcoming || [];
    const fixtureLabel = (m, completed) => `${dateText(m.date)} · ${esc(m.home || "?")} ${completed && m.home_score != null ? `${num(m.home_score)}–${num(m.away_score)}` : "v"} ${esc(m.away || "?")} · ${esc(m.competition || "")}${completed && !m.detailed_stats_available ? " · basic facts only" : ""}`;
    const reportMatchOptions = completedMatches.map((m) => `<option value="${m.fixture_id}">${fixtureLabel(m, true)}</option>`).join("");
    const reportNextOptions = upcomingMatches.map((m) => `<option value="${m.fixture_id}">${fixtureLabel(m, false)}</option>`).join("");
    const reportPlayerOptions = players.map((p) => `<option value="${p.player_ea_id}">${esc(p.display_name)} · ${esc(p.position || "N/D")}</option>`).join("");
    const rows = players.map((p) => { const m = p.metrics || {}; return `<tr><td>${p.player_ea_id ? playerLink(p.player_ea_id, p.display_name) : esc(p.display_name)}</td><td class="center">${positionBadge(p.position)}</td><td>${esc(p.hierarchy_label || "N/D")}</td><td class="num">${p.minutes ? num(p.minutes) : "N/D"}</td><td class="num">${p.season_rating == null ? "N/D" : num(p.season_rating, 2)}</td><td class="num">${p.recent_rating == null ? "N/D" : num(p.recent_rating, 2)}</td><td>${esc(p.sample?.label || "N/D")}${p.valid_form_games ? `<small class="table-subline">${num(p.valid_form_games)} atuações · ${num(p.recent_appearances)} recentes</small>` : ""}</td><td class="num">${m.appearances ? `${num(m.npk_goals)} / ${num(m.assists)}` : "N/D"}<small class="table-subline">${m.appearances ? `${num(m.appearances)} jogos · ${esc(m.sample?.label || "N/D")}` : "NPK G / A · MatchStats"}</small></td><td class="num">${m.npk_expected_goals == null ? "N/D" : num(m.npk_expected_goals, 2)} / ${m.expected_assists == null ? "N/D" : num(m.expected_assists, 2)}<small class="table-subline">xG / xA</small></td><td class="num">${m.appearances ? num(m.shots) : "N/D"}<small class="table-subline">${m.shot_accuracy_pct == null ? "N/D" : `${num(m.shot_accuracy_pct, 1)} % no alvo`}</small></td><td class="num">${m.pass_accuracy_pct == null ? "N/D" : `${num(m.pass_accuracy_pct, 1)} %`}</td><td class="num">${m.appearances ? `${num(m.tackles)} / ${num(m.interceptions)}` : "N/D"}<small class="table-subline">desarmes / interceptações</small></td><td class="num">${m.appearances ? `${num(m.blocks)} / ${num(m.clearances)}` : "N/D"}<small class="table-subline">bloqueios / cortes</small></td><td class="num">${m.appearances ? `${num(m.saves)} / ${num(m.goals_conceded)}` : "N/D"}<small class="table-subline">defesas / gols sofridos</small></td><td>${esc(p.moment || "N/D")}</td><td>${esc(p.recommendation || "N/D")}</td></tr>`; }).join("");
    const posRows = (d.position_comparisons || []).map((r) => `<tr><td>${esc(r.position)}</td><td class="num">${num(r.players)}</td><td class="num">${num(r.matches)}</td><td class="num">${num(r.minutes)}</td><td class="num">${r.average_rating == null ? "N/D" : num(r.average_rating, 2)}</td><td class="num">${r.goals_per90 == null ? "N/D" : num(r.goals_per90, 2)}</td><td class="num">${r.xg_per90 == null ? "N/D" : num(r.xg_per90, 2)}</td><td>${esc(r.sample?.label || "N/D")}</td></tr>`).join("");
    const fnRows = (d.function_comparisons || []).map((r) => `<tr><td>${esc(r.position)}</td><td class="num">${num(r.players)}</td><td class="num">${num(r.matches)}</td><td class="num">${num(r.minutes)}</td><td class="num">${r.average_rating == null ? "N/D" : num(r.average_rating, 2)}</td><td class="num">${r.goals_per90 == null ? "N/D" : num(r.goals_per90, 2)}</td><td>${esc(r.sample?.label || "N/D")}</td></tr>`).join("");
    const identity = d.team_identity || {}, tm = identity.metrics || {}, cached = reportCache?.result || {}, ai = cached.report || {};
    const refs = (ids) => { const catalog = new Map((cached.fact_catalog || []).map((f) => [f.id, f.label])); return esc((ids || []).map((id) => catalog.get(id) || id).join(" · ")); };
    const kindLabel = (kind) => kind === "fact" ? tr("claimFact") : kind === "hypothesis" ? tr("claimHypothesis") : tr("claimInference");
    const reportItems = (items) => items?.length ? `<ul>${items.map((item) => `<li><span class="commission-claim-kind ${esc(item.kind || "inference")}">${esc(kindLabel(item.kind))}</span> ${esc(item.text)}${item.kind === "hypothesis" && item.limitations ? `<small class="commission-claim-limit">${tr("claimLimit")}: ${esc(item.limitations)}</small>` : ""}<small class="table-subline">Atlas: ${refs(item.fact_refs)}</small></li>`).join("")}</ul>` : "";
    const profileRows = (identity.opponent_profiles || []).map((item) => `<div class="commission-profile-card"><strong>${esc(item.opponent_profile)}</strong><span>${item.reading === "maior_facilidade_observada" ? "Melhor desempenho" : item.reading === "maior_dificuldade_observada" ? "Maior dificuldade" : "Sem comparação"}</span><small>${num(item.matches)} jogos · ${num(item.points_per_match, 2)} pts/jogo · saldo ${num(item.goal_difference_per_match, 2)}/jogo</small></div>`).join("");
    const reportState = reportCache?.state || "missing";
    const reportNote = ai.commission_note?.text ? `<p class="commission-note"><strong>${tr("commissionNote")}:</strong> ${esc(ai.commission_note.text)}</p>` : "";
    const reportSummary = reportState === "ready" ? `<div class="commission-report-head"><strong>${esc(ai.summary?.text || "Análise salva.")}</strong><small><span class="commission-claim-kind ${esc(ai.summary?.kind || "inference")}">${esc(kindLabel(ai.summary?.kind))}</span> · ${esc(cached.model || "Ollama local")} · ${esc(reportCache.generated_at || "Atlas")}<br>Fatos: ${refs(ai.summary?.fact_refs)}</small></div>${ai.summary?.limitations ? `<p class="commission-claim-limit">${tr("claimLimit")}: ${esc(ai.summary.limitations)}</p>` : ""}${reportNote}${reportItems(ai.observations)}${reportItems(ai.recommendations)}${commissionFollowupForm(ai.information_requests, { snapshot_id: Number(d.snapshot_id), mode: "team_identity", model: cached.model, coach_context: cached.fact_catalog?.find((f) => f.id === "coach_context")?.value })}<details class="report-provenance"><summary>Cobertura e validação das evidências</summary><small>${num(cached.coverage?.previous_linked_matches)} partidas anteriores · ${num(cached.validation?.accepted_claims)} afirmações mantidas · ${num(cached.validation?.rejected_claims)} filtradas · ${esc(cached.validation?.interpretation_quality || "Qualidade interpretativa não avaliada independentemente")}</small></details>` : reportState === "queued" || reportState === "running" ? `<p>Ollama está preparando a leitura do estilo em segundo plano. O restante do Atlas continua disponível.</p>` : reportState === "stale" ? `<p>A leitura salva ficou desatualizada após a entrada de novos dados. Atualize para usar as estatísticas atuais.</p><div class="commission-report-head"><strong>${esc(ai.summary?.text || "")}</strong></div>` : `<p>A leitura da comissão será salva e reutilizada enquanto as estatísticas usadas não mudarem.</p>`;
    const retroactiveBatch = `<section class="card pad commission-retroactive"><div class="card-title-row"><div><h3 class="card-title">${tr("retroTitle")}</h3><p class="chart-note">${tr("retroHelp")}</p></div><button class="button primary" data-retroactive-reports data-season-index="${num(d.selectedSeasonIndex)}">${tr("retroStart")}</button></div><div data-retroactive-progress class="commission-report-output" aria-live="polite"></div></section>`;
    return `<section class="grid metrics analysis-metrics">${metric("Players on squad", num(coverage.squad_players), "selected snapshot")}${metric("With match ratings", num(coverage.players_with_performances), "player level")}${metric("MatchStats coverage", `${num(coverage.detailed_matches)} / ${num(coverage.completed_team_matches)}`, `${coverage.detailed_match_coverage_pct == null ? "N/D" : `${num(coverage.detailed_match_coverage_pct, 1)} %`} completed team matches`)}${metric("MatchStats player rows", num(coverage.detailed_player_rows), "complete linked exports")}</section>
      <section class="grid commission-identity-grid"><article class="card commission-identity-hero"><span class="metric-label">Leitura estatística · ${identity.style_sample_sufficient ? `${num(identity.detailed_matches)} partidas detalhadas` : "amostra insuficiente"}</span><h2>${identity.style_sample_sufficient ? "Perfil observado a partir das estatísticas registradas" : "Estilo ainda inconclusivo"}</h2><p>${identity.style_sample_sufficient ? "Tendências e médias determinísticas do Atlas. A interpretação da comissão aparece no relatório ao lado." : esc(identity.sample_note || "São necessárias partidas detalhadas suficientes para caracterizar o padrão.")}</p><span class="status-badge ${reportState === "ready" ? "good" : "amber"}">${reportState === "ready" ? "Análise salva · reutilizada" : reportState === "queued" || reportState === "running" ? "Ollama analisando em segundo plano" : "Aguardando análise"}</span><small class="table-subline">A interpretação usa somente métricas com cobertura. Posse percentual, pressão e altura da linha ficam N/D quando não exportadas.</small></article>
        <section class="card"><header class="card-header"><div><h2>Indicadores do estilo</h2><p>${num(identity.detailed_matches)} jogos detalhados de ${num(identity.completed_matches)} resultados</p></div><span>${identity.coverage_pct == null ? "N/D" : `${num(identity.coverage_pct, 1)} %`} cobertura</span></header><div class="card-body commission-style-metrics"><div><span>Passes por partida</span><b>${tm.passes_per_match == null ? "N/D" : num(tm.passes_per_match, 1)}</b></div><div><span>Precisão de passe</span><b>${tm.pass_accuracy_pct == null ? "N/D" : `${num(tm.pass_accuracy_pct, 1)} %`}</b></div><div><span>Dribles completos/jogo</span><b>${tm.dribbles_completed_per_match == null ? "N/D" : num(tm.dribbles_completed_per_match, 1)}</b></div><div><span>Cruzamentos tentados/jogo</span><b>${tm.crosses_attempted_per_match == null ? "N/D" : num(tm.crosses_attempted_per_match, 1)}</b></div><div><span>Passes em profundidade/jogo</span><b>${tm.through_passes_per_match == null ? "N/D" : num(tm.through_passes_per_match, 1)}</b></div><div><span>Finalizações / NPK-xG</span><b>${tm.shots_per_match == null ? "N/D" : num(tm.shots_per_match, 1)} / ${tm.npk_xg_per_match == null ? "N/D" : num(tm.npk_xg_per_match, 2)}</b></div></div></section></section>
      <div class="grid two-col commission-overview-grid"><section class="card"><header class="card-header"><div><h2>Facilidades e dificuldades observadas</h2><p>Perfis estatísticos do adversário · não são rótulos de clube</p></div></header><div class="card-body commission-profile-grid">${profileRows || '<p class="muted">Ainda não há pelo menos 5 jogos por perfil comparável. A comissão não conclui facilidade ou dificuldade.</p>'}</div><div class="data-note">Comparação por volume de finalizações do adversário e resultado registrado. Relação observada não comprova causa nem define a tática do adversário.</div></section>
      <section class="card"><header class="card-header"><div><h2>Relatório Ollama · estilo de jogo</h2><p>Atualizado após novas partidas; salvo na base desta carreira</p></div><span class="status-badge ${reportState === "ready" ? "good" : ""}">${esc(reportState)}</span></header><div class="card-body"><div data-commission-report-output data-report-slot="commission-team" class="commission-report-output">${reportSummary}</div><button class="button primary" data-commission-report data-report-target="commission-team" data-mode="team_identity" data-snapshot-id="${num(d.snapshot_id)}" data-force-refresh="${reportState === "ready" ? "1" : "0"}">${reportState === "ready" ? "Atualizar leitura" : "Gerar leitura"}</button><small class="chart-note">A análise salva só é renovada quando as estatísticas de origem mudam ou quando você pede atualização.</small></div></section></div>
      ${retroactiveBatch}<details class="commission-advanced"><summary>Elenco, comparações de posição e ferramentas sob demanda</summary><div class="commission-advanced-body"><section class="card"><header class="card-header"><h2>Professional squad · ${esc(d.managed_team_name || "selected career")}</h2><span>${esc(d.selectedSeasonLabel || "snapshot data")}</span></header>${rows ? table([{ label: "Player" }, { label: "Pos.", cls: "center" }, { label: "Hierarchy" }, { label: "Min", cls: "num" }, { label: "Season rating", cls: "num" }, { label: "Last five", cls: "num" }, { label: "Sample" }, { label: "NPK G / A", cls: "num" }, { label: "NPK-xG / xA", cls: "num" }, { label: "Shots", cls: "num" }, { label: "Pass accuracy", cls: "num" }, { label: "Tackles / Int.", cls: "num" }, { label: "Blocks / clearances", cls: "num" }, { label: "Saves / conceded", cls: "num" }, { label: "Form" }, { label: "Commission note" }], rows) : '<div class="card-body muted">No professional match ratings are recorded for this snapshot.</div>'}</section><section class="grid two-col"><section class="card"><header class="card-header"><h2>Position comparison · registered role</h2></header>${posRows ? table([{ label: "Position" }, { label: "Players", cls: "num" }, { label: "Match rows", cls: "num" }, { label: "Min", cls: "num" }, { label: "Rating", cls: "num" }, { label: "NPK G / 90", cls: "num" }, { label: "xG / 90", cls: "num" }, { label: "Sample" }], posRows) : '<div class="card-body muted">No comparable MatchStats samples.</div>'}</section><section class="card"><header class="card-header"><h2>Observed function comparison</h2></header>${fnRows ? table([{ label: "Position" }, { label: "Players", cls: "num" }, { label: "Match rows", cls: "num" }, { label: "Min", cls: "num" }, { label: "Rating", cls: "num" }, { label: "NPK G / 90", cls: "num" }, { label: "Sample" }], fnRows) : '<div class="card-body muted">N/D — no reliable observed match position.</div>'}</section></section><section class="card pad commission-studio"><div class="card-title-row"><div><h3 class="card-title">Report on demand</h3><p class="chart-note">Match, player and upcoming-fixture reports are saved by career and source facts, then reused when those facts are unchanged.</p></div><span class="status-badge good">Local Ollama</span></div><div class="commission-studio-controls"><label class="page-filter"><span>Analysis</span><select data-commission-mode><option value="match">Review completed match</option><option value="player">Review a player</option><option value="next_match">Prepare upcoming match</option></select></label><label class="page-filter" data-commission-fixture-wrap><span>Match</span><select data-commission-fixture>${reportMatchOptions || '<option value="">No completed matches</option>'}</select></label><label class="page-filter" data-commission-next-wrap hidden><span>Upcoming fixture</span><select data-commission-next-fixture>${reportNextOptions || '<option value="">No upcoming fixture</option>'}</select></label><label class="page-filter" data-commission-player-wrap hidden><span>Player</span><select data-commission-player>${reportPlayerOptions || '<option value="">No professional players</option>'}</select></label><button class="button" data-commission-report data-snapshot-id="${num(d.snapshot_id)}">Generate report</button></div><div data-commission-report-output class="commission-report-output" aria-live="polite"></div></section><div class="grid two-col analysis-grid"><section class="card pad"><h3 class="card-title">Sample rules</h3><p class="chart-note">Usable: 300+ minutes and 3+ appearances. Reliable: 450+ minutes and 5+ appearances. Form uses up to five valid appearances weighted by minutes. Hierarchy stays N/D when not recorded.</p></section><section class="card pad"><h3 class="card-title">Coverage</h3><p class="chart-note">${esc(coverage.detailed_metric_scope || "MatchStats coverage unavailable.")} ${coverage.detailed_match_coverage_pct == null ? "N/D" : `${num(coverage.detailed_match_coverage_pct, 1)} %`} (${num(coverage.detailed_matches)} of ${num(coverage.completed_team_matches)} completed matches). Missing metrics stay N/D; youth 5x5 remains separate.</p></section></div></div></details>`;
}
function analysisMatchSummary(mi) {
    if (!mi?.available)
        return `<section class="card pad"><div class="card-title-row"><h3 class="card-title">FC26 match data</h3>${statusBadge("No detailed matches yet", "amber")}</div><p class="chart-note">Once validated match exporter data is linked, xG/xA, shots, passing, duels and other performance metrics appear here.</p></section>`;
    const f = mi.team?.for || {}, a = mi.team?.against || {};
    const coverage = mi.coveragePct == null ? `${num(mi.matchesCovered)} detailed matches` : `${num(mi.matchesCovered)} / ${num(mi.totalCompletedMatches)} matches · ${num(mi.coveragePct, 0)} %`;
    return `<section class="card pad"><div class="card-title-row"><div><h3 class="card-title">FC26 match data</h3><span>${coverage}</span></div>${statusBadge("Direct FC26 data", "good")}</div><div class="grid metrics compact">${metric(f.expected_goals_derived_per_match != null ? "Team xG / match" : "NPK-xG / match", `${num(f.expected_goals_derived_per_match ?? f.npk_expected_goals_per_match, 2)} : ${num(a.expected_goals_derived_per_match ?? a.npk_expected_goals_per_match, 2)}`, `${num((Number(f.expected_goals_derived_per_match ?? f.npk_expected_goals_per_match) || 0) - (Number(a.expected_goals_derived_per_match ?? a.npk_expected_goals_per_match) || 0), 2)} difference`, "green")}${metric("xA / match", `${num(f.expected_assists_per_match, 2)} : ${num(a.expected_assists_per_match, 2)}`, "for : against", "blue")}${metric("Shots / match", `${num(f.shots_per_match, 1)} : ${num(a.shots_per_match, 1)}`, `xG/shot ${num(f.xg_per_shot, 3)} : ${num(a.xg_per_shot, 3)}`)}${metric("Pass accuracy", `${num(f.pass_accuracy_pct_derived, 1)} %`, `${num(a.pass_accuracy_pct_derived, 1)} % opponent`)}${metric("Possession balance / match", `${num(f.possession_won_per_match, 1)} / ${num(f.possession_lost_per_match, 1)}`, `opponent ${num(a.possession_won_per_match, 1)} / ${num(a.possession_lost_per_match, 1)}`)}${metric("Duels", f.combined_duel_success_pct == null ? "–" : `${num(f.combined_duel_success_pct, 1)} %`, a.combined_duel_success_pct == null ? "–" : `${num(a.combined_duel_success_pct, 1)} % opponent`)}</div></section>`;
}
function analysisMatchIntelligence(d) {
    const mi = d.matchIntelligence || {};
    if (!mi.available)
        return `<div class="grid">${analysisMatchSummary(mi)}</div>`;
    const f = mi.team?.for || {}, a = mi.team?.against || {}, players = (mi.players || []).slice();
    const leaders = [
        ["NPK-xG", "npk_expected_goals", 2], ["xA", "expected_assists", 2], ["Key passes", "key_passes", 0], ["Possession won", "possession_won", 0], ["Interceptions", "interceptions", 0], ["Avg. rating", "average_game_rating", 2]
    ];
    const trendPoints = (mi.trends || []).map((t) => ({ ...t, season_label: dateText(t.date) }));
    const venue = mi.splits?.venue || {}, home = venue.home || {}, away = venue.away || {};
    const competitionSplits = mi.splits?.competitions || [];
    const competitionSplitTable = competitionSplits.length ? `<section class="card"><header class="card-header"><div><h2>Competition profiles</h2><p>Per-match values rather than raw totals</p></div><span>${num(competitionSplits.length)} competitions</span></header>${table([{ label: "Competition" }, { label: "Matches", cls: "num" }, { label: "NPK-xG / match", cls: "num" }, { label: "Shots / match", cls: "num" }, { label: "xG / shot", cls: "num" }, { label: "Duels", cls: "num" }], competitionSplits.map((c) => `<tr><td><strong>${esc(c.competitionName || "–")}</strong></td><td class="num">${num(c.matches)}</td><td class="num">${num(c.for?.npk_expected_goals_per_match, 2)} : ${num(c.against?.npk_expected_goals_per_match, 2)}</td><td class="num">${num(c.for?.shots_per_match, 1)} : ${num(c.against?.shots_per_match, 1)}</td><td class="num">${num(c.for?.xg_per_shot, 3)} : ${num(c.against?.xg_per_shot, 3)}</td><td class="num">${c.for?.combined_duel_success_pct == null ? "–" : `${num(c.for.combined_duel_success_pct, 1)} %`}</td></tr>`))}</section>` : "";
    return `<div class="grid">${analysisMatchSummary(mi)}<div class="grid two-col analysis-grid"><section class="card pad"><div class="card-title-row"><h3 class="card-title">NPK-xG per match</h3><span>for / against</span></div>${simpleBarChart(trendPoints, [{ key: "npkXgFor", label: "NPK-xG for" }, { key: "npkXgAgainst", label: "NPK-xG against" }])}</section><section class="card pad"><div class="card-title-row"><h3 class="card-title">Five-match underlying trend</h3><span>rolling NPK-xG balance</span></div>${simpleBarChart(trendPoints, [{ key: "rolling5XgDiff", label: "Avg. NPK-xG difference (5)" }])}</section></div>
      <section class="card"><header class="card-header"><div><h2>Team profile from detailed data</h2><p>Totals plus reliable per-match and efficiency metrics</p></div></header><div class="card-body">${detailedAggregateGroups(f)}<div class="grid metrics compact" style="margin-top:12px">${metric("Home", num(home.matches), `${num(home.for?.npk_expected_goals_per_match, 2)} NPK-xG/match`)}${metric("Away", num(away.matches), `${num(away.for?.npk_expected_goals_per_match, 2)} NPK-xG/match`)}${metric("Chance quality", num(f.xg_per_shot, 3), "NPK-xG per shot", "green")}${metric("Pass accuracy under pressure", f.pressure_pass_accuracy_pct == null ? "–" : `${num(f.pressure_pass_accuracy_pct, 1)} %`, "passes under pressure")}</div></div><div class="data-note">Opponent comparison: ${num(a.npk_expected_goals_per_match, 2)} NPK-xG/match · ${num(a.expected_assists_per_match, 2)} xA/match · ${num(a.shots_per_match, 1)} shots/match. ${esc(mi.xgNote || "")}</div></section>
      <section class="card"><header class="card-header"><h2>Detailed-data leaders</h2><span>only matches with detailed FC26 imports</span></header><div class="match-leader-grid">${leaders.map(([label, key, digits]) => { const rows = players.filter((p) => p.stats?.[key] != null).sort((x, y) => (Number(y.stats[key]) || 0) - (Number(x.stats[key]) || 0)).slice(0, 5); return `<div class="match-leader-card"><h4>${esc(label)}</h4>${rows.map((p, i) => `<div><span>${num(i + 1)}. ${p.playerEaId ? playerLink(p.playerEaId, p.displayName) : esc(p.displayName || "–")}</span><strong>${num(p.stats[key], digits)}</strong></div>`).join("") || '<span class="muted">–</span>'}</div>`; }).join("")}</div></section>
      ${competitionSplitTable}
      <section class="card"><header class="card-header"><h2>Match-by-match profile</h2><span>${num(mi.matchesCovered)} matches</span></header>${table([{ label: "Date" }, { label: "Match" }, { label: "Competition" }, { label: "NPK-xG", cls: "num" }, { label: "xA", cls: "num" }, { label: "Shots", cls: "num" }, { label: "5-match xG balance", cls: "num" }], (mi.trends || []).slice().reverse().map((t) => `<tr><td>${dateText(t.date)}</td><td>${matchLink(t.fixtureId, `${t.homeTeamName || "?"} – ${t.awayTeamName || "?"}`)}<small class="table-subline">${t.venue === "home" ? "Home" : "Away"}</small></td><td>${esc(t.competitionName || "–")}</td><td class="num">${num(t.npkXgFor, 2)} : ${num(t.npkXgAgainst, 2)}</td><td class="num">${num(t.xAFor, 2)} : ${num(t.xAAgainst, 2)}</td><td class="num">${num(t.shotsFor)} : ${num(t.shotsAgainst)}</td><td class="num">${Number(t.rolling5XgDiff) >= 0 ? "+" : ""}${num(t.rolling5XgDiff, 2)}</td></tr>`))}</section></div>`;
}
function analysisOverview(d, placementMetric) {
    const m = d.metrics || {};
    const overview = d.seasonOverview || {};
    const competitionRows = overview.competitions || [];
    const leaderRows = overview.leaders || [];
    const seasonTable = d.leagueHistory?.length ? table([
        { label: "Season" }, { label: "League" }, { label: "Position", cls: "center" }, { label: "League movement" }, { label: "Source" }
    ], d.leagueHistory.map((row) => `<tr><td>${esc(row.season_label)}${row.is_current ? `<small class="table-subline">current season</small>` : ""}</td><td>${esc(row.league_name)}</td><td class="center"><strong>${esc(row.position_display || "–")}</strong>${row.result_status === "running" && row.position_source_label ? `<small class="table-subline">${esc(row.position_source_label)}</small>` : ""}</td><td>${row.movement === "promotion" ? statusBadge("Promotion", "good") : row.movement === "relegation" ? statusBadge("Relegation", "bad") : row.movement === "same" ? statusBadge("same league") : row.movement === "first" ? statusBadge("Start") : statusBadge("unknown")}</td><td>${statusBadge(row.source_label, row.source === "manual" ? "good" : "")}</td></tr>`)) : '<div class="card-body"><span class="muted">No league history available yet.</span></div>';
    return `<div class="grid metrics analysis-metrics">${metric("Matches", num(m.matches), `${num(m.wins)} W · ${num(m.draws)} D · ${num(m.losses)} L`, "green")}${metric("Goal balance", `${num(m.goals_for)}:${num(m.goals_against)}`, `${num((Number(m.goals_for) || 0) - (Number(m.goals_against) || 0))} difference`, "blue")}${metric(placementMetric.title, placementMetric.value, placementMetric.sub)}${metric("Titles", num(m.titles), "confirmed competition wins", "amber")}${metric("Players", num(m.players_used), "with appearances")}${metric("Transfers / Loans", `${num(m.transfers)} / ${num(m.loans)}`, "managed club")}</div>
      <div class="grid two-col analysis-grid"><section class="card pad"><div class="card-title-row"><h3 class="card-title">League path</h3><span>with season position</span></div>${leaguePositionChart(d.leagueHistory || [])}</section><section class="card pad"><div class="card-title-row"><h3 class="card-title">Transfer activity</h3><span>managed club</span></div>${simpleBarChart(d.transferActivity || [], [{ key: "incoming", label: "Arrivals" }, { key: "outgoing", label: "Departures" }, { key: "loans_in", label: "Loans in" }, { key: "loans_out", label: "Loans out" }])}</section></div>
      <div class="grid split-65"><div class="grid"><section class="card"><header class="card-header"><h2>Season results</h2><span>${num((d.leagueHistory || []).length)} seasons</span></header>${seasonTable}</section>
      <section class="card"><header class="card-header"><h2>${Number(d.selectedSeasonIndex) === -1 ? "Transfer activity by season" : "Season overview"}</h2><span>${esc(d.selectedSeasonLabel)}</span></header>${Number(d.selectedSeasonIndex) === -1 ? table([{ label: "Season" }, { label: "Arrivals", cls: "num" }, { label: "Departures", cls: "num" }, { label: "Loans in", cls: "num" }, { label: "Loans out", cls: "num" }, { label: "Unknown fees", cls: "num" }], (d.transferActivity || []).map((r) => `<tr><td>${esc(r.season_label)}</td><td class="num">${num(r.incoming)}</td><td class="num">${num(r.outgoing)}</td><td class="num">${num(r.loans_in)}</td><td class="num">${num(r.loans_out)}</td><td class="num">${num(r.unknown_fees)}</td></tr>`)) : `<div class="card-body grid two-col"><div><h4>Competitions</h4><div class="list">${competitionRows.map((c) => `<div class="list-row"><div class="list-main"><strong>${c.competition_object_id ? competitionLink(c.competition_object_id, c.competition_name) : esc(c.competition_name)}</strong><small>${c.result_text || `${num(c.completed)} of ${num(c.matches)} matches`}</small></div>${c.final_position ? statusBadge(`#${num(c.final_position)}`) : ""}</div>`).join("") || '<span class="muted">No competitions recorded.</span>'}</div></div><div><h4>Top players</h4><div class="list">${leaderRows.map((p) => `<div class="list-row"><div class="list-main">${p.player_ea_id ? playerLink(p.player_ea_id, p.display_name) : esc(p.display_name)}<small>${num(p.appearances)} appearances · ${ratingValue(p.average_rating, true)}</small></div><div class="list-value"><strong>${num(p.goals)} G</strong><small>${num(p.assists)} A</small></div></div>`).join("") || '<span class="muted">No player statistics.</span>'}</div></div></div>`}</section></div><aside class="grid">${qualityPanel(d.quality)}<section class="card pad"><h3 class="card-title">Data sources</h3><div class="source-legend"><span>${statusBadge("Imported")}</span><span>${statusBadge("Derived", "blue")}</span><span>${statusBadge("Manual", "good")}</span><p>Missing values are not estimated. A current season is considered complete only after a later season snapshot.</p></div></section></aside></div>${analysisMatchSummary(d.matchIntelligence)}`;
}
function analysisSquad(d) {
    const m = d.metrics || {};
    const squadAnalysis = d.squadAnalysis || {};
    const squadSummary = squadAnalysis.summary || {};
    const positionRows = squadAnalysis.positionBalance || [];
    const performanceRows = squadAnalysis.performanceLeaders || [];
    return `<div class="grid metrics analysis-metrics">${metric("Squad size", num(m.squad_count), "latest snapshot in the period")}${metric("Avg. OVR", num(m.average_overall, 1), "Squad strength", "green")}${metric("Avg. age", num(m.average_age, 1), "squad average", "blue")}${metric("Avg. POT", num(squadSummary.average_potential, 1), "development potential", "amber")}${metric("Players used", num(squadSummary.performance_player_count), d.selectedSeasonLabel)}</div>
      <div class="grid two-col analysis-grid"><section class="card pad"><div class="card-title-row"><h3 class="card-title">Squad strength</h3><span>by snapshot</span></div>${lineChart(d.squadTrend || [], ["average_overall"], { decimals: 1, ariaLabel: "Durchschnittliche Squad strength", unit: " OVR" })}</section><section class="card pad"><div class="card-title-row"><h3 class="card-title">Average age</h3><span>by snapshot</span></div>${lineChart(d.squadTrend || [], ["average_age"], { decimals: 1, ariaLabel: "Average age", unit: " J." })}</section></div>
      <div class="grid two-col analysis-grid"><section class="card"><header class="card-header"><h2>Squad balance</h2><span>${num(squadSummary.squad_count)} players · Avg. POT ${num(squadSummary.average_potential, 1)}</span></header>${positionRows.length ? table([{ label: "Position group" }, { label: "Players", cls: "num" }, { label: "Avg. OVR", cls: "num" }, { label: "Avg. POT", cls: "num" }, { label: "Avg. age", cls: "num" }], positionRows.map((r) => `<tr><td><strong>${esc(r.group)}</strong></td><td class="num">${num(r.count)}</td><td class="num">${num(r.average_overall, 1)}</td><td class="num">${num(r.average_potential, 1)}</td><td class="num">${num(r.average_age, 1)}</td></tr>`)) : '<div class="card-body"><span class="muted">No squad snapshot is available for this period.</span></div>'}</section><section class="card pad"><div class="card-title-row"><h3 class="card-title">Age structure</h3><span>${squadSummary.youngest_age != null ? `${num(squadSummary.youngest_age)}–${num(squadSummary.oldest_age)} years` : "no squad snapshot"}</span></div>${horizontalBars(squadAnalysis.ageStructure || [])}</section></div>
      <div class="grid two-col analysis-grid"><section class="card pad"><div class="card-title-row"><h3 class="card-title">Appearance distribution</h3><span>${num(squadSummary.performance_player_count)} players used</span></div>${horizontalBars(squadAnalysis.appearanceDistribution || [])}<p class="chart-note">${esc(squadAnalysis.usageDefinition || "")}</p></section><section class="card"><header class="card-header"><h2>Top performers</h2><span>selected period</span></header>${performanceRows.length ? table([{ label: "Player" }, { label: "Pos.", cls: "center" }, { label: "Matches", cls: "num" }, { label: "Goals", cls: "num" }, { label: "Assists", cls: "num" }, { label: "G+A", cls: "num" }, { label: "Avg. rating", cls: "num" }], performanceRows.map((p) => `<tr><td>${p.player_ea_id ? playerLink(p.player_ea_id, p.display_name) : esc(p.display_name)}</td><td class="center">${positionBadge(p.primary_position)}</td><td class="num">${num(p.appearances)}</td><td class="num">${num(p.goals)}</td><td class="num">${num(p.assists)}</td><td class="num"><strong>${num(p.goal_contributions)}</strong></td><td class="num">${ratingValue(p.average_rating, true)}</td></tr>`)) : '<div class="card-body"><span class="muted">No player statistics in the selected period.</span></div>'}</section></div>${analysisMatchSummary(d.matchIntelligence)}`;
}
function analysisSeasons(d) {
    const rows = d.seasonComparison || [], detailBySeason = new Map((d.matchIntelligence?.bySeason || []).map((x) => [Number(x.seasonIndex), x]));
    const seasonRows = rows.map((r) => { const md = detailBySeason.get(Number(r.season_index)), f = md?.for || {}, a = md?.against || {}; return `<tr><td><strong>${esc(r.season_label)}</strong>${r.is_current ? '<small class="table-subline">current</small>' : ""}</td><td>${esc(r.league_name || "–")}<small class="table-subline">${esc(r.position_display || "–")}</small></td><td class="num">${num(r.matches)}</td><td class="num">${num(r.wins)} / ${num(r.draws)} / ${num(r.losses)}</td><td class="num">${num(r.goals_for)}:${num(r.goals_against)}</td><td class="num">${num(r.goal_difference)}</td><td class="num">${md ? `${num(f.npk_expected_goals, 2)} : ${num(a.npk_expected_goals, 2)}` : "–"}</td><td class="num">${md ? `${num(f.expected_assists, 2)} : ${num(a.expected_assists, 2)}` : "–"}</td><td class="num">${md ? num(md.matchesCovered) : "–"}</td><td class="num">${num(r.players_used)}</td><td>${r.top_scorer_name ? (r.top_scorer_id ? playerLink(r.top_scorer_id, r.top_scorer_name) : esc(r.top_scorer_name)) + ` · ${num(r.top_scorer_goals)} G` : "–"}</td><td class="num">${num(r.average_overall, 1)}</td><td class="num">${num(r.average_age, 1)}</td><td class="num">${num(r.transfers)} / ${num(r.loans)}</td></tr>`; });
    const detailRows = (d.matchIntelligence?.bySeason || []).map((x) => ({ season_label: (rows.find((r) => Number(r.season_index) === Number(x.seasonIndex)) || {}).season_label || `Season ${num(Number(x.seasonIndex) + 1)}`, npkXgFor: x.for?.npk_expected_goals, npkXgAgainst: x.against?.npk_expected_goals }));
    return `<div class="grid two-col analysis-grid"><section class="card pad"><div class="card-title-row"><h3 class="card-title">Results by season</h3><span>Wins, draws and losses</span></div>${simpleBarChart(rows, [{ key: "wins", label: "Wins" }, { key: "draws", label: "Draws" }, { key: "losses", label: "Losses" }])}</section><section class="card pad"><div class="card-title-row"><h3 class="card-title">Goals by season</h3><span>scored and conceded</span></div>${simpleBarChart(rows, [{ key: "goals_for", label: "Goals" }, { key: "goals_against", label: "Goals against" }])}</section></div>
      ${detailRows.length ? `<section class="card pad"><div class="card-title-row"><h3 class="card-title">NPK-xG by season</h3><span>detailed FC26 matches only</span></div>${simpleBarChart(detailRows, [{ key: "npkXgFor", label: "NPK-xG for" }, { key: "npkXgAgainst", label: "NPK-xG against" }])}</section>` : ""}
      <section class="card"><header class="card-header"><h2>Season comparison</h2><span>${num(rows.length)} seasons</span></header>${rows.length ? table([{ label: "Season" }, { label: "League / position" }, { label: "Matches", cls: "num" }, { label: "W / D / L", cls: "num" }, { label: "Goals", cls: "num" }, { label: "Diff.", cls: "num" }, { label: "NPK-xG F:A", cls: "num" }, { label: "xA F:A", cls: "num" }, { label: "Detailed", cls: "num" }, { label: "Players", cls: "num" }, { label: "Top scorer" }, { label: "Avg. OVR", cls: "num" }, { label: "Avg. age", cls: "num" }, { label: "Tr. / L.", cls: "num" }], seasonRows, "season-comparison-table") : '<div class="card-body"><span class="muted">No comparable season data available yet.</span></div>'}</section>
      <p class="data-note">NPK-xG/xA comes only from clearly linked detailed FC26 match exports. Manually entered player statistics are summed across all competitions in the season; snapshot and manual values are not double-counted.</p>`;
}
let currentSeasonReportData = null;
function seasonReportPicker(options, selected) {
    return `<label class="page-filter"><span>Season</span><select data-season-report-season>${options.map((option) => `<option value="${option.season_index}" ${Number(option.season_index) === Number(selected) ? "selected" : ""}>${esc(option.label)}${option.is_current ? " · current" : ""}</option>`).join("")}</select></label>`;
}
function seasonReportTabs(active) {
    const tabs = [["overview", "Overview"], ["competitions", "Competitions"], ["squad", "Squad & performance"], ["transfers", "Transfers"], ["awards", "Awards"], ["quality", "Data quality"]];
    return `<div class="page-tabs season-report-tabs">${tabs.map(([key, label]) => `<button class="${active === key ? "active" : ""}" data-season-report-tab="${key}">${label}</button>`).join("")}</div>`;
}
function awardPortrait(award) {
    return playerPortrait(award.media, award.display_name, "season-award-portrait");
}
function automaticAwardCards(report) {
    const awards = report?.awards || [];
    if (!report?.awards_available)
        return `<div class="award-lock"><strong>Awards are locked</strong><span>${esc(report?.completion?.label || "The season must be completed first.")}</span></div>`;
    if (!awards.length)
        return '<div class="muted">Not enough season statistics are available for automatic awards yet.</div>';
    return `<div class="season-award-grid fancy">${awards.map((award) => {
        const payload = encodeURIComponent(JSON.stringify(award));
        return `<article class="season-award-card automatic">${awardPortrait(award)}<div class="season-award-copy"><span>Tracker evaluation · ${esc(award.label)}</span><strong>${award.player_ea_id ? playerLink(award.player_ea_id, award.display_name) : esc(award.display_name || "–")}</strong><b>${esc(award.value || "–")}</b><small>${esc(award.rule || "")}</small><button class="button tiny" data-season-award-copy="${payload}">Use as manager award</button></div></article>`;
    }).join("")}</div>`;
}
function managerAwardCards(report) {
    const awards = report?.manual?.awards || [];
    if (!report?.awards_available)
        return `<div class="award-lock"><strong>Manager awards are locked</strong><span>${esc(report?.completion?.label || "The season must be completed first.")}</span></div>`;
    if (!awards.length)
        return '<div class="muted">No custom season awards have been assigned yet.</div>';
    return `<div class="season-award-grid fancy">${awards.map((award) => {
        const payload = encodeURIComponent(JSON.stringify(award));
        const transfer = award.from_team_name || award.to_team_name ? `<small class="award-transfer">${esc(award.from_team_name || "–")} → ${esc(award.to_team_name || "–")}${award.fee != null ? ` · ${money(award.fee)}` : ""}</small>` : "";
        return `<article class="season-award-card manager">${awardPortrait(award)}<div class="season-award-copy"><span>Manager award · ${esc(award.award_label)}</span><strong>${award.player_ea_id ? playerLink(award.player_ea_id, award.display_name) : esc(award.display_name || "–")}</strong>${transfer}${award.reason ? `<p>${esc(award.reason)}</p>` : ""}<div class="row-actions"><button class="button tiny" data-season-award-edit="${payload}">Edit</button><button class="button tiny danger" data-season-award-delete="${award.id}">Delete</button></div></div></article>`;
    }).join("")}</div>`;
}
function seasonAwardEditor(report) {
    const manual = report?.manual || {}, players = manual.players || [], categories = manual.categories || [], transfers = manual.transfers || [];
    if (!report?.awards_available)
        return `<section class="card pad award-editor-locked"><h3 class="card-title">Custom awards</h3><p>Season awards can be assigned only after the final match of the season.</p><small>${esc(report?.completion?.label || "Season end not confirmed")}</small></section>`;
    return `<form class="card pad season-award-editor" data-season-award-form><input type="hidden" name="id"><div class="card-title-row"><h3 class="card-title">Assign custom award</h3><span>does not change the Tracker evaluation</span></div><div class="form-grid three"><label><span>Category</span><select name="awardKey">${categories.map((c) => `<option value="${esc(c.key)}">${esc(c.label)}</option>`).join("")}</select></label><label><span>Custom award name</span><input name="awardLabel" placeholder="only for Custom award"></label><label><span>Player</span><select name="playerEaId" data-season-award-player><option value="">Choose player</option>${players.map((p) => `<option value="${p.player_ea_id ?? ""}" data-name="${esc(p.display_name)}">${esc(p.display_name)} · ${pos(p.primary_position)} · ${num(p.appearances)} apps</option>`).join("")}</select></label><label><span>Player name</span><input name="displayName" data-season-award-name required placeholder="Player name"></label><label><span>Related manual transfer</span><select name="relatedTransactionId"><option value="">None</option>${transfers.filter((t) => t.id).map((t) => `<option value="${t.id}">${esc(t.display_name)} · ${esc(t.from_team_name || "–")} → ${esc(t.to_team_name || "–")}${t.fee != null ? ` · ${money(t.fee)}` : ""}</option>`).join("")}</select></label><label class="span-3"><span>Reason / note</span><textarea name="reason" rows="3" placeholder="Why does this player receive the award?"></textarea></label></div><div class="row-actions"><button class="button primary" type="submit">Save award</button><button class="button" type="reset">Clear form</button></div></form>`;
}
function seasonMovementRows(items, type) {
    if (!items?.length)
        return '<span class="muted">No movements recorded.</span>';
    return `<div class="season-report-movements">${items.filter((item) => item.direction !== "Global").map((item) => {
        const fromId = type === "loan" ? item.parent_team_ea_id : item.from_team_ea_id;
        const fromName = type === "loan" ? item.parent_team_name : item.from_team_name;
        const toId = type === "loan" ? item.loan_team_ea_id : item.to_team_ea_id;
        const toName = type === "loan" ? item.loan_team_name : item.to_team_name;
        return `<div class="season-report-movement"><div><strong>${item.player_ea_id ? playerLink(item.player_ea_id, item.display_name) : esc(item.display_name || "–")}</strong><small>${dateText(item.date || item.first_observed_date)}</small></div><div class="season-report-route"><span>${fromId ? clubLink(fromId, fromName) : esc(fromName || "–")}</span><b>→</b><span>${toId ? clubLink(toId, toName) : esc(toName || "–")}</span></div><div><strong>${type === "transfer" ? (item.fee == null ? "Fee unknown" : money(item.fee)) : (item.loan_end_date ? `to ${dateText(item.loan_end_date)}` : "Loan")}</strong><small>${esc(item.source_label || "")}</small></div></div>`;
    }).join("")}</div>`;
}
function seasonReportOverview(d) {
    const m = d.metrics || {}, overview = d.seasonOverview || {}, report = d.seasonReport || {}, league = overview.leagueFinish || {};
    return `<section class="card season-report-hero"><div><span>Season</span><h2>${esc(d.selectedSeasonLabel)}</h2><p>${esc(league.league_name || "League not recorded")} · ${esc(league.position_display || (report.is_current ? "current" : "Position unknown"))}</p>${league.position_source_label ? `<small>${esc(league.position_source_label)}</small>` : ""}</div><div class="season-report-score"><div><strong>${num(m.wins)}</strong><span>Wins</span></div><div><strong>${num(m.draws)}</strong><span>Draws</span></div><div><strong>${num(m.losses)}</strong><span>Losses</span></div></div><div><span>Goal balance</span><h2>${num(m.goals_for)}:${num(m.goals_against)}</h2><p>${num((Number(m.goals_for) || 0) - (Number(m.goals_against) || 0))} goal difference</p></div></section>
      <div class="grid metrics analysis-metrics">${metric("Matches", num(m.matches), `${num(m.players_used)} players used`, "green")}${metric("League position", esc(league.position_display || "–"), league.league_name || "League unknown")}${metric("Titles", num(m.titles), "confirmed competition wins", "amber")}${metric("Transfers / Loans", `${num(m.transfers)} / ${num(m.loans)}`, "managed club")}${metric("Avg. squad OVR", num(m.average_overall, 1), `Avg. age ${num(m.average_age, 1)}`, "blue")}</div>
      <div class="grid two-col"><section class="card pad"><div class="card-title-row"><h3 class="card-title">Season highlights</h3><span>from records</span></div>${recordCatalog(report.records || {})}</section><section class="card pad"><h3 class="card-title">Season review</h3><form data-season-report-note-form><textarea name="summaryNote" rows="8" placeholder="Your season review, turning points, objectives…">${esc(report.manual?.summaryNote || "")}</textarea><div class="row-actions"><button class="button primary" type="submit">Save note</button></div></form></section></div>${analysisMatchSummary(d.matchIntelligence)}`;
}
function seasonReportCompetitions(d) {
    const competitions = d.seasonOverview?.competitions || [];
    return `<section class="card"><header class="card-header"><h2>Competitions</h2><span>${num(competitions.length)} entries</span></header>${competitions.length ? table([{ label: "Competition" }, { label: "Matches", cls: "num" }, { label: "Result" }], competitions.map((c) => `<tr><td>${c.competition_object_id ? competitionLink(c.competition_object_id, c.competition_name) : esc(c.competition_name || "–")}</td><td class="num">${num(c.completed)} / ${num(c.matches)}</td><td>${esc(c.result_text || (c.final_position ? `#${num(c.final_position)}` : "–"))}</td></tr>`)) : '<div class="card-body muted">No competitions recorded.</div>'}</section>`;
}
function seasonReportSquad(d) {
    const leaders = d.squadAnalysis?.performanceLeaders || [], squad = d.squadAnalysis || {};
    return `<div class="grid"><section class="card"><header class="card-header"><h2>Top performers</h2><span>all competitions</span></header>${leaders.length ? table([{ label: "Player" }, { label: "Pos.", cls: "center" }, { label: "Apps", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "G+A", cls: "num" }, { label: "Avg. rating", cls: "num" }], leaders.slice(0, 20).map((p) => `<tr><td>${p.player_ea_id ? playerLink(p.player_ea_id, p.display_name) : esc(p.display_name)}</td><td class="center">${positionBadge(p.primary_position)}</td><td class="num">${num(p.appearances)}</td><td class="num">${num(p.goals)}</td><td class="num">${num(p.assists)}</td><td class="num"><b>${num(p.goal_contributions)}</b></td><td class="num">${ratingValue(p.average_rating, true)}</td></tr>`)) : '<div class="card-body muted">No player statistics.</div>'}</section><div class="grid two-col"><section class="card pad"><h3 class="card-title">Squad balance</h3>${horizontalBars((squad.positionGroups || []).map((r) => ({ label: r.group, count: r.count, average_overall: r.average_overall })))}</section><section class="card pad"><h3 class="card-title">Age structure</h3>${horizontalBars(squad.ageGroups || [])}</section></div></div>`;
}
function seasonReportTransfers(d) {
    const report = d.seasonReport || {}, overview = d.seasonOverview || {};
    return `<div class="grid two-col"><section class="card pad"><div class="card-title-row"><h3 class="card-title">Transfers</h3><span>${num(report.transfer_count)}</span></div>${seasonMovementRows(overview.transfers || [], "transfer")}</section><section class="card pad"><div class="card-title-row"><h3 class="card-title">Loans</h3><span>${num(report.loan_count)}</span></div>${seasonMovementRows(overview.loans || [], "loan")}</section></div>`;
}
function seasonReportAwards(d) {
    const report = d.seasonReport || {};
    return `<div class="grid"><section class="card pad"><div class="card-title-row"><h3 class="card-title">Manager awards</h3><span>custom</span></div>${managerAwardCards(report)}</section>${seasonAwardEditor(report)}<section class="card pad"><div class="card-title-row"><h3 class="card-title">Tracker evaluation</h3><span>rule-based</span></div>${automaticAwardCards(report)}</section></div>`;
}
function seasonReportQuality(d) {
    return `<div class="grid two-col">${qualityPanel(d.quality)}<section class="card pad"><h3 class="card-title">Report rules</h3><p class="chart-note">${esc(d.seasonReport?.method_note || "The report uses available data only.")}</p><p class="chart-note">Manual awards remain separate from automatically calculated Tracker awards. Missing competitions, fees or historical statistics are not filled in.</p></section></div>`;
}
function downloadText(filename, text, type) { const blob = new Blob([text], { type }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function exportSeasonReportCsv() { const d = currentSeasonReportData; if (!d)
    return; const m = d.metrics || {}, rows = [["Season", d.selectedSeasonLabel], ["League", d.seasonOverview?.leagueFinish?.league_name || ""], ["Position", d.seasonOverview?.leagueFinish?.position_display || ""], ["Matches", m.matches], ["Wins", m.wins], ["Draws", m.draws], ["Losses", m.losses], ["Goals", m.goals_for], ["Goals against", m.goals_against], ["Players", m.players_used]]; const awards = (d.seasonReport?.manual?.awards || []).map((a) => [a.award_label, a.display_name, a.reason || ""]); const csv = ["Section;Value;Note", ...rows.map((r) => r.map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`).join(";")), ...awards.map((r) => `"Award: ${String(r[0]).replaceAll('"', '""')}";"${String(r[1]).replaceAll('"', '""')}";"${String(r[2]).replaceAll('"', '""')}"`)].join("\r\n"); downloadText(`Atlas_Season_Report_${d.selectedSeasonLabel.replace('/', '-')}.csv`, `\ufeff${csv}`, "text/csv;charset=utf-8"); }
async function exportSeasonInfographic(format = "portrait") {
    const d = currentSeasonReportData;
    if (!d)
        return;
    const canvas = document.createElement("canvas"), W = 1080, H = format === "square" ? 1080 : 1350;
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext("2d");
    if (!ctx)
        return;
    const m = d.metrics || {}, league = d.seasonOverview?.leagueFinish || {}, awards = d.seasonReport?.manual?.awards?.length ? d.seasonReport.manual.awards : (d.seasonReport?.awards || []);
    const grad = ctx.createLinearGradient(0, 0, W, H);
    grad.addColorStop(0, "#102c43");
    grad.addColorStop(1, "#07121f");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#20df83";
    ctx.fillRect(64, 64, 12, 190);
    ctx.fillStyle = "#ffffff";
    ctx.font = "700 34px sans-serif";
    ctx.fillText("PROJECT ATLAS TRACKER · SEASON REPORT", 100, 100);
    ctx.font = "900 76px sans-serif";
    ctx.fillText(String(d.selectedSeasonLabel), 100, 190);
    ctx.font = "600 32px sans-serif";
    ctx.fillStyle = "#b9cad8";
    ctx.fillText(`${league.league_name || "League"} · ${league.position_display || "Position unknown"}`, 100, 240);
    const boxes = [["WINS", m.wins], ["DRAWS", m.draws], ["LOSSES", m.losses], ["GOALS", `${m.goals_for}:${m.goals_against}`]];
    boxes.forEach((b, i) => { const x = 70 + i * 250; ctx.fillStyle = "#0d2032"; ctx.fillRect(x, 310, 220, 150); ctx.fillStyle = "#8ea5b9"; ctx.font = "700 22px sans-serif"; ctx.fillText(String(b[0]), x + 20, 350); ctx.fillStyle = "#fff"; ctx.font = "900 58px sans-serif"; ctx.fillText(String(b[1] ?? "–"), x + 20, 425); });
    ctx.fillStyle = "#fff";
    ctx.font = "800 36px sans-serif";
    ctx.fillText(awards === d.seasonReport?.manual?.awards ? "Manager awards" : "Tracker awards", 70, 550);
    const maxAwards = format === "square" ? 3 : 5;
    (awards.slice(0, maxAwards)).forEach((a, i) => { const y = 600 + i * 118; ctx.fillStyle = i % 2 ? "#0a1a2a" : "#0d2235"; ctx.fillRect(70, y, 940, 92); ctx.fillStyle = "#20df83"; ctx.font = "700 20px sans-serif"; ctx.fillText(String(a.award_label || a.label || "Award").toUpperCase(), 95, y + 31); ctx.fillStyle = "#fff"; ctx.font = "800 30px sans-serif"; ctx.fillText(String(a.display_name || "–"), 95, y + 70); });
    ctx.fillStyle = "#8ea5b9";
    ctx.font = "500 20px sans-serif";
    ctx.fillText("Created locally with Project Atlas Tracker · data as recorded in the season report", 70, H - 48);
    const link = document.createElement("a");
    link.download = `Atlas_Season_Card_${format}_${String(d.selectedSeasonLabel).replace('/', '-')}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
}
async function renderSeasonReport() {
    const fallback = Number(currentSnapshot()?.season_index ?? 0);
    const selected = state.seasonReportSeasonIndex ?? fallback;
    const d = await api(`/api/careers/${state.careerId}/analysis?snapshot_id=${state.snapshotId}&season_index=${selected}`);
    currentSeasonReportData = d;
    state.seasonReportSeasonIndex = Number(d.selectedSeasonIndex);
    const report = d.seasonReport || {}, reportStatus = report.season_complete ? statusBadge("Complete", "good") : statusBadge("In progress", "blue");
    const active = state.seasonReportTab || "overview";
    const body = active === "competitions" ? seasonReportCompetitions(d) : active === "squad" ? seasonReportSquad(d) : active === "transfers" ? seasonReportTransfers(d) : active === "awards" ? seasonReportAwards(d) : active === "quality" ? seasonReportQuality(d) : seasonReportOverview(d);
    content.innerHTML = `<div class="content-inner wide season-report-page">${pageHead("Season report", `${esc(d.selectedSeasonLabel)} · structured career report`, `<button class="button" data-season-report-print>Print / PDF</button><button class="button" data-season-report-csv>CSV</button><button class="button" data-season-report-image="square">Square PNG</button><button class="button primary" data-season-report-image="portrait">Portrait PNG</button>`)}<div class="page-filter-bar">${seasonReportPicker(d.seasonOptions || [], Number(d.selectedSeasonIndex))}<span class="filter-hint">${reportStatus} Automatic and custom awards remain separate.</span></div>${seasonReportTabs(active)}${body}</div>`;
}
async function renderAnalysis() {
    const fallback = Number(currentSnapshot()?.season_index ?? 0);
    const selected = state.analysisSeasonIndex ?? fallback;
    const active = state.route === "commission" ? "commission" : state.analysisTab || "overview";
    if (active === "commission") {
        const commission = await api(`/api/careers/${state.careerId}/commission?season_index=${selected}`);
        state.analysisSeasonIndex = Number(commission.selectedSeasonIndex);
        const reportCache = await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(commission.snapshot_id)}&mode=team_identity`).catch(() => ({ state: "missing" }));
        const body = technicalCommission(commission, reportCache);
        const filter = `<div class="page-filter-bar">${periodPicker(commission.seasonOptions || [], Number(commission.selectedSeasonIndex), "analysis")}<span class="filter-hint">${esc(commission.detailed_metric_scope || "Position and MatchStats coverage are shown for this season.")}</span></div>`;
        content.innerHTML = `<div class="content-inner wide">${pageHead(state.route === "commission" ? "Technical commission" : "Analysis", `${esc(commission.managed_team_name || "Active career")} · ${esc(commission.selectedSeasonLabel)}`, `<button class="button" data-route="results">Results</button><button class="button" data-route="squad">Squad</button>`)}${state.route === "commission" ? "" : analysisTabs(active)}${filter}${body}</div>`;
        return;
    }
    const d = await api(`/api/careers/${state.careerId}/analysis?snapshot_id=${state.snapshotId}&season_index=${selected}`);
    state.analysisSeasonIndex = Number(d.selectedSeasonIndex);
    const leagueContext = d.metrics?.league_context || {};
    const placementMetric = leagueContext.mode === "current"
        ? { title: "League position", value: leagueContext.position ? `#${num(leagueContext.position)}` : "–", sub: leagueContext.league_name || "current league" }
        : { title: "Highest league", value: leagueContext.league_name || "–", sub: leagueContext.position ? `Best position there: #${num(leagueContext.position)} · ${esc(leagueContext.season_label || "")}` : "no reliable position" };
    const body = active === "performance" ? analysisMatchIntelligence(d) : active === "squad" ? analysisSquad(d) : active === "seasons" ? analysisSeasons(d) : analysisOverview(d, placementMetric);
    const filter = active === "seasons" ? '<div class="page-filter-bar"><span class="filter-hint">The season comparison shows all available seasons side by side.</span></div>' : `<div class="page-filter-bar">${periodPicker(d.seasonOptions || [], Number(d.selectedSeasonIndex), "analysis")}<span class="filter-hint">${active === "performance" ? "Only clearly linked detailed FC26 matches are included in this analysis." : "Tables and charts use the same selection."}</span></div>`;
    content.innerHTML = `<div class="content-inner wide">${pageHead("Analysis", `career metrics · ${esc(d.selectedSeasonLabel)}`, `<button class="button" data-route="records">Records</button><button class="button" data-route="chronology">Career timeline</button>`)}${analysisTabs(active)}${filter}${body}</div>`;
}
async function renderRecords() {
    const selected = state.recordsSeasonIndex ?? -1;
    const d = await api(`/api/careers/${state.careerId}/analysis?snapshot_id=${state.snapshotId}&season_index=${selected}`);
    state.recordsSeasonIndex = Number(d.selectedSeasonIndex);
    content.innerHTML = `<div class="content-inner wide">${pageHead("Records", `Player, match, streak and transfer records · ${esc(d.selectedSeasonLabel)}`, `<button class="button" data-route="analysis">Back to analysis</button>`)}
      <div class="page-filter-bar">${periodPicker(d.seasonOptions || [], Number(d.selectedSeasonIndex), "records")}<span class="filter-hint">The entire career is analysed by default.</span></div>
      ${recordCatalog(d.records || {})}
      <div class="grid two-col analysis-grid"><section class="card pad"><h3 class="card-title">Calculation rule</h3><p class="chart-note">All of a player’s competitions are summed within the selected period. Manual legacy seasons and snapshot seasons are joined by calendar year.</p></section>${qualityPanel(d.quality)}</div>
    </div>`;
}
async function renderMatchCenter() { const d = await api(`/api/snapshots/${state.snapshotId}/matches`), recent = d.completed.slice(-5).reverse(), upcoming = d.upcoming.slice(0, 5), form = d.completed.slice(-10).map((m) => resultCode(m.managed_team_result)); const next = upcoming[0]; content.innerHTML = `<div class="content-inner">${pageHead("Match Center", "Schedule, results and available match data", `<button class="button" data-route="schedule">Schedule</button><button class="button" data-route="results">Results</button>`)}<div class="grid metrics">${metric("Played", num(d.completed.length), "completed matches")}${metric("Open", num(d.upcoming.length), "upcoming matches", "blue")}${metric("Last 5", form.slice(-5).map(resultPill).join(" "), "across all competitions")}${metric("Last 10", form.map((c) => c).join(" · "), "Form sequence")}${metric("Competitions", num(d.competitions.length), "featuring your club", "green")}</div>${next ? `<section class="card fixture-hero"><div class="fixture-meta">NEXT MATCH · ${competitionLink(next.competition_object_id, next.competition_name)} · ${dateText(next.date)} ${esc(timeText(next.time))}</div><div class="fixture-scoreboard"><div class="fixture-club">${identityLogo(next.homeIdentity, next.home_team_name, "fixture-club-logo")}<h2>${clubLink(next.home_team_ea_id, next.home_team_name)}</h2></div><div class="fixture-score">VS<small>${matchLink(next.fixture_id, "Open match")}</small></div><div class="fixture-club">${identityLogo(next.awayIdentity, next.away_team_name, "fixture-club-logo")}<h2>${clubLink(next.away_team_ea_id, next.away_team_name)}</h2></div></div></section>` : ""}<div class="grid two-col" style="margin-top:14px"><section class="card"><header class="card-header"><h2>Recent results</h2><button class="entity-link" data-route="results">All</button></header>${renderMatchRows(recent)}</section><section class="card"><header class="card-header"><h2>Upcoming matches</h2><button class="entity-link" data-route="schedule">All</button></header>${renderMatchRows(upcoming)}</section></div><section class="card" style="margin-top:14px"><header class="card-header"><h2>Competition status</h2></header><div class="card-body grid competition-grid">${d.competitions.map((c) => `<button class="competition-card card" data-competition="${c.competition_object_id}"><div class="competition-top">${identityLogo(c.identity, c.competition_name, "competition-logo-card")}<div><h3>${esc(c.competition_name)}</h3><p>${num(c.completed)} of ${num(c.total)} completed</p></div></div></button>`).join("")}</div></section></div>`; }
async function renderMatchList(mode) {
    const d = await api(`/api/snapshots/${state.snapshotId}/matches`);
    const source = mode === "results" ? d.completed.slice().reverse() : d.upcoming;
    const comps = Array.from(new Map(d.competitions.map((c) => [Number(c.competition_object_id), c])).values());
    const rows = state.matchCompetition === "all" ? source : source.filter((m) => String(m.competition_object_id) === String(state.matchCompetition));
    const title = mode === "results" ? "Results" : "Schedule";
    const subtitle = mode === "results" ? "All completed matches for the managed club" : "All upcoming and open matches";
    content.innerHTML = `<div class="content-inner wide">${pageHead(title, subtitle, `<button class="button" data-route="match-center">Match Center</button>`)}
      <div class="filter-row"><select id="matchCompetition" class="filter-select"><option value="all">All competitions</option>${comps.map((c) => `<option value="${c.competition_object_id}" ${String(state.matchCompetition) === String(c.competition_object_id) ? "selected" : ""}>${esc(c.competition_name)}</option>`).join("")}</select><span class="chip">${num(rows.length)} matches</span></div>
      <section class="card">${table([
        { label: "Date" }, { label: "Competition" }, { label: "Home" }, { label: "Result", cls: "center" },
        { label: "Away" }, { label: "Status", cls: "center" }, { label: "" }
    ], rows.map((m) => `<tr>
        <td data-sort="${esc(m.date || "")}">${dateText(m.date)} <span class="muted">${esc(timeText(m.time))}</span></td>
        <td><span class="inline-identity">${identityLogo(m.competitionIdentity, m.competition_name, "inline-logo")}${competitionLink(m.competition_object_id, m.competition_name)}</span></td>
        <td><span class="inline-identity">${identityLogo(m.homeIdentity, m.home_team_name, "table-club-logo")}${clubLink(m.home_team_ea_id, m.home_team_name)}</span></td>
        <td class="center"><b>${m.is_completed ? `${num(m.home_score)} : ${num(m.away_score)}` : "–"}</b></td>
        <td><span class="inline-identity">${identityLogo(m.awayIdentity, m.away_team_name, "table-club-logo")}${clubLink(m.away_team_ea_id, m.away_team_name)}</span></td>
        <td class="center">${m.is_completed ? resultPill(m.managed_team_result) : statusBadge("Scheduled")}${m.detailedStatsAvailable ? `<small class="table-subline">${statusBadge("FC26 Detail", "good")}</small>` : ""}</td>
        <td>${matchLink(m.fixture_id, "Details")}</td>
      </tr>`))}</section></div>`;
    $("#matchCompetition", content).onchange = (e) => { state.matchCompetition = e.target.value; renderMatchList(mode); };
}
const detailedStatLabels = {
    goals_derived: "Goals", assists: "Assists", npk_expected_goals: "NPK-xG", expected_assists: "xA", shots: "Shots", shots_on_target: "Shots on target", shots_off_target_derived: "Off target", shots_blocked: "Blocked shots", key_passes: "Key passes", assists_from_shots: "Shot Assists", assists_from_dummy: "Dummy Assists", fk_goals: "Free-kick goals", pk_goals: "Penalty goals", offsides: "Offsides", offsides_caused: "Offsides caused", corners_won: "Corners won",
    passes: "Passes", passes_completed: "Completed passes", pass_accuracy_pct_derived: "Pass accuracy", passes_under_pressure: "Passes under pressure", passes_completed_under_pressure: "Completed passes under pressure", offside_passes: "Offside passes", passes_intercepted: "Passes intercepted", crosses_attempted: "Crosses", crosses_delivered: "Completed crosses", crosses_blocked: "Blocked crosses", cross_success_pct_derived: "Cross success",
    dribbles: "Dribbles", dribbles_completed: "Successful dribbles", dribbles_failed_derived: "Failed dribbles", dribble_success_pct_derived: "Dribble success", skillmove_beats: "Beaten with a skill move", nutmegs: "Nutmegs", knock_ons: "Knock-ons", beaten_by_opponent: "Beaten by opponent", beaten_in_defensive_third: "Beaten in defensive third", beaten_in_box: "Beaten in the box", tackled_by_opponent: "Tackled by opponent", beat_with_pass: "Beaten by a pass",
    tackles: "Tackles", stand_tackles: "Standing tackles", stand_tackles_won: "Standing tackles won", stand_tackle_success_pct_derived: "Standing tackle success", slide_tackles: "Sliding tackles", slide_tackles_won: "Sliding tackles won", slide_tackle_success_pct_derived: "Sliding tackle success", interceptions: "Interceptions", blocks: "Blocks", clearances: "Clearances", possession_won: "Possession won", possession_lost: "Possession lost",
    opense_duels_attempted: "Attacking duels", offense_duels_won: "Attacking duels won", offense_duel_success_pct_derived: "Attacking duel success", defense_duels_attempted: "Defensive duels", defense_duels_won: "Defensive duels won", defense_duel_success_pct_derived: "Defensive duel success", aerial_duels_attempted: "Aerial duels", aerial_duels_won: "Aerial duels won", aerial_duel_success_pct_derived: "Aerial duel success",
    fouls_committed: "Fouls", fouls_won: "Fouls won", yellow_card_events: "Yellow cards", red_dismissals: "Red cards", penalties_committed: "Penalties conceded", penalties_won: "Penalties won",
    saves: "Saves", shots_against: "Shots faced", saving_shots_on_target: "Shots on target faced", save_success_pct_derived: "Save percentage", penalty_saves: "Penalty saves", shootout_saves: "Shoot-out saves", punches: "Punches", dives_at_feet: "Dives at feet", saving_crosses: "Crosses claimed", save_punch_to_clearance: "Punch to clearance", goals_conceded: "Goals conceded", penalty_goals_conceded: "Penalty goals conceded", shootout_goals_conceded: "Shootout goals conceded"
};
const detailedStatGroups = [
    { label: "Attack & chances", keys: ["goals_derived", "assists", "npk_expected_goals", "expected_assists", "shots", "shots_on_target", "shots_off_target_derived", "shots_blocked", "key_passes", "fk_goals", "pk_goals", "offsides", "corners_won"] },
    { label: "Passing & creation", keys: ["passes", "passes_completed", "pass_accuracy_pct_derived", "passes_under_pressure", "passes_completed_under_pressure", "crosses_attempted", "crosses_delivered", "cross_success_pct_derived"] },
    { label: "Dribbling & possession", keys: ["dribbles", "dribbles_completed", "dribble_success_pct_derived", "skillmove_beats", "nutmegs", "possession_won", "possession_lost", "beaten_by_opponent", "beat_with_pass"] },
    { label: "Defending", keys: ["tackles", "stand_tackles", "stand_tackles_won", "stand_tackle_success_pct_derived", "slide_tackles", "slide_tackles_won", "slide_tackle_success_pct_derived", "interceptions", "blocks", "clearances"] },
    { label: "Duels", keys: ["offense_duels_attempted", "offense_duels_won", "offense_duel_success_pct_derived", "defense_duels_attempted", "defense_duels_won", "defense_duel_success_pct_derived", "aerial_duels_attempted", "aerial_duels_won", "aerial_duel_success_pct_derived"] },
    { label: "Discipline", keys: ["fouls_committed", "fouls_won", "yellow_card_events", "red_dismissals", "penalties_committed", "penalties_won"] },
    { label: "Goalkeeping", keys: ["saves", "shots_against", "saving_shots_on_target", "save_success_pct_derived", "penalty_saves", "shootout_saves", "punches", "dives_at_feet", "saving_crosses", "goals_conceded"] }
];
function detailedStatText(key, value) {
    if (value == null || value === "")
        return "–";
    if (key.includes("pct"))
        return `${num(value, 1)} %`;
    if (key === "npk_expected_goals" || key === "expected_assists")
        return num(value, 2);
    return num(value, Number(value) % 1 ? 2 : 0);
}
function detailedPlayerDrawer(p) {
    const s = p.detailedStats || {};
    if (!Object.keys(s).length)
        return "";
    const context = [
        ["xG+xA /90", s.xg_plus_xa_per90 == null ? "–" : num(s.xg_plus_xa_per90, 2)],
        ["xG per shot", s.xg_per_shot == null ? "–" : num(s.xg_per_shot, 3)],
        ["Passes under pressure", s.pressure_pass_accuracy_pct == null ? "–" : `${num(s.pressure_pass_accuracy_pct, 1)} %`],
        ["Duels", s.combined_duel_success_pct == null ? "–" : `${num(s.combined_duel_success_pct, 1)} %`],
        ["Possession balance", Number(s.possession_balance) >= 0 ? `+${num(s.possession_balance)}` : num(s.possession_balance)]
    ];
    return `<details class="match-player-details"><summary>Match profile & all metrics</summary><div class="match-context-strip">${context.map((x) => `<div><span>${esc(x[0])}</span><strong>${esc(x[1])}</strong></div>`).join("")}</div><div class="detailed-stat-groups">${detailedStatGroups.map((g) => { const items = g.keys.filter((k) => s[k] != null); return items.length ? `<div class="detailed-stat-group"><h4>${esc(g.label)}</h4>${items.map((k) => `<div><span>${esc(detailedStatLabels[k] || k)}</span><strong>${detailedStatText(k, s[k])}</strong></div>`).join("")}</div>` : ""; }).join("")}</div></details>`;
}
function matchComparisonRow(label, left, right, format = (v) => num(v)) {
    const hasLeft = left != null && Number.isFinite(Number(left)), hasRight = right != null && Number.isFinite(Number(right));
    const lv = hasLeft ? Number(left) : 0, rv = hasRight ? Number(right) : 0, max = Math.max(lv, rv, 0.0001);
    const bars = hasLeft && hasRight ? `<div class="match-stat-bars"><i class="home" style="width:${Math.max(2, lv / max * 100)}%"></i><i class="away" style="width:${Math.max(2, rv / max * 100)}%"></i></div>` : `<small class="match-stat-unavailable">Comparison unavailable for one or both teams</small>`;
    return `<div class="match-stat-row"><strong class="left">${left == null ? "–" : format(left)}</strong><div class="match-stat-label"><span>${esc(label)}</span>${bars}</div><strong>${right == null ? "–" : format(right)}</strong></div>`;
}
async function renderMatch() {
    const d = await api(`/api/snapshots/${state.snapshotId}/matches/${Number(state.routeData.id)}`), m = d.match;
    const stadium = d.stadium, detailed = d.detailedStats || {}, hasDetailed = !!detailed.available;
    const stadiumSection = stadium ? `<section class="card stadium-match-card"><header class="card-header"><div><h2>${esc(stadium.name || "Stadium")}</h2><p>${d.stadiumSource === "fixture" ? "Stadium exported for this match" : "Home stadium fallback — the actual venue may differ for neutral finals"}</p></div><div class="row-actions">${statusBadge(stadium.stadiumTypeLabel || "Unknown type", stadium.stadiumType === "authentic" ? "good" : stadium.stadiumType === "generic" ? "blue" : "")}${statusBadge(d.stadiumSource === "fixture" ? "Fixture data" : "Fallback", d.stadiumSource === "fixture" ? "good" : "")}</div></header><div class="stadium-gallery">${(stadium.variants || []).length ? (stadium.variants || []).map((variant, index) => `<figure class="stadium-variant ${index === 0 ? "primary" : ""}">${mediaImg(variant, stadium.name, "stadium-match-image", false)}<figcaption>Variant ${esc(variant.variant || index + 1)}</figcaption></figure>`).join("") : `<div class="card-body muted">A stadium is assigned, but no image has been imported yet.</div>`}</div></section>` : "";
    const teamById = new Map((detailed.teams || []).map((t) => [Number(t.teamEaId), t]));
    const homeStats = (teamById.get(Number(m.home_team_ea_id)) || {}).stats || {}, awayStats = (teamById.get(Number(m.away_team_ea_id)) || {}).stats || {};
    const statComparisons = [];
    statComparisons.push(["Team-xG", homeStats.expected_goals_derived, awayStats.expected_goals_derived, (v) => num(v, 2)]);
    statComparisons.push(["NPK-xG", homeStats.npk_expected_goals, awayStats.npk_expected_goals, (v) => num(v, 2)]);
    statComparisons.push(["NPK-xG per shot", homeStats.xg_per_shot, awayStats.xg_per_shot, (v) => num(v, 3)]);
    statComparisons.push(["xA", homeStats.expected_assists, awayStats.expected_assists, (v) => num(v, 2)]);
    statComparisons.push(["Shots", homeStats.shots, awayStats.shots, (v) => num(v)]);
    statComparisons.push(["On target", homeStats.shots_on_target, awayStats.shots_on_target, (v) => num(v)]);
    statComparisons.push(["Passes", homeStats.passes, awayStats.passes, (v) => num(v)]);
    statComparisons.push(["Pass accuracy", homeStats.pass_accuracy_pct_derived, awayStats.pass_accuracy_pct_derived, (v) => `${num(v, 1)} %`]);
    statComparisons.push(["Passes under pressure", homeStats.pressure_pass_accuracy_pct, awayStats.pressure_pass_accuracy_pct, (v) => `${num(v, 1)} %`]);
    statComparisons.push(["Key passes", homeStats.key_passes, awayStats.key_passes, (v) => num(v)]);
    statComparisons.push(["Dribbles completed", homeStats.dribbles_completed, awayStats.dribbles_completed, (v) => num(v)]);
    statComparisons.push(["Possession won", homeStats.possession_won, awayStats.possession_won, (v) => num(v)]);
    statComparisons.push(["Possession lost", homeStats.possession_lost, awayStats.possession_lost, (v) => num(v)]);
    statComparisons.push(["Interceptions", homeStats.interceptions, awayStats.interceptions, (v) => num(v)]);
    statComparisons.push(["Tackles", homeStats.tackles, awayStats.tackles, (v) => num(v)]);
    statComparisons.push(["Defensive duel success", homeStats.defense_duel_success_pct_derived, awayStats.defense_duel_success_pct_derived, (v) => `${num(v, 1)} %`]);
    statComparisons.push(["Aerial duels won", homeStats.aerial_duels_won, awayStats.aerial_duels_won, (v) => num(v)]);
    statComparisons.push(["Fouls", homeStats.fouls_committed, awayStats.fouls_committed, (v) => num(v)]);
    const comparisonRows = statComparisons.filter(([, left, right]) => left != null || right != null).map(([label, left, right, format]) => matchComparisonRow(label, left, right, format));
    const comparison = hasDetailed ? `<section class="card match-comparison-card"><header class="card-header"><div><h2>Match statistics</h2><p>Direct FC26 match data · team xG augments the direct NPK-xG base only when penalty context is reliable</p></div></header><div class="match-comparison-head"><span>${esc(m.home_team_name)}</span><b>Comparison</b><span>${esc(m.away_team_name)}</span></div><div class="match-stat-comparison">${comparisonRows.join("") || '<p class="muted">No comparable team metrics were exported for this match.</p>'}</div><div class="data-note">${esc(detailed.xgNote || "")} ${esc(detailed.eventTimingNote || "")}</div></section>` : "";
    const eventNames = new Map(d.performances.map((p) => [Number(p.player_ea_id), p.display_name]));
    const teamByIndex = new Map((detailed.teams || []).map((t) => [Number(t.teamIndex), t]));
    const eventTeamName = (idx) => { const team = teamByIndex.get(Number(idx)), id = Number(team?.teamEaId); return id === Number(m.home_team_ea_id) ? m.home_team_name : id === Number(m.away_team_ea_id) ? m.away_team_name : `Team ${num(Number(idx) + 1)}`; };
    const events = hasDetailed ? `<section class="card"><header class="card-header"><div><h2>Event overview</h2><p>Exported events — no inferred chronology or match minute</p></div></header><div class="match-event-grid">${(detailed.events || []).length ? (detailed.events || []).map((e) => `<div class="match-event ${esc(e.type)}"><span class="event-icon">${e.type === "yellow_card" ? "▰" : e.type === "red_card" ? "■" : e.type === "motm" ? "★" : e.type === "goal" || e.type === "penalty_goal" ? "●" : "•"}</span><div><strong>${esc(eventNames.get(Number(e.playerEaId)) || e.displayName || `Player ${e.playerEaId}`)}</strong><small>${esc(e.label)}${Number(e.count) > 1 ? ` ×${num(e.count)}` : ""}</small></div><span>${esc(eventTeamName(e.teamIndex))}</span></div>`).join("") : `<div class="card-body muted">No exported events for this match.</div>`}</div><div class="data-note">${esc(detailed.eventTimingNote || "")}</div></section>` : "";
    const performanceRow = (p) => {
        const s = p.detailedStats || p.reconstructedStats || {};
        const detailedRow = !!p.detailedStats;
        return `<tr>
        <td><div class="player-line">${playerPortrait(p.media, p.display_name, "table-portrait")}<div class="player-line-copy">${playerLink(p.player_ea_id, p.display_name)}${detailedRow ? detailedPlayerDrawer(p) : ""}</div></div></td>
        <td class="center" data-sort="${positionOrder(p.actual_position_source === 'career_playermatchratinghistory_position' ? p.actual_position : p.primary_position, p.primary_position_id)}">${p.actual_position_source === 'career_playermatchratinghistory_position' ? `${positionBadge(p.actual_position)}<small class="match-position-source">Observed</small>` : `${positionBadge(p.primary_position)}<small class="match-position-source">Registered · observed N/D</small>`}</td><td class="num">${num(s.minutes_played ?? p.minutes_played)}</td><td class="num"><b>${s.game_rating != null ? num(s.game_rating, 1) : p.rating ? num(p.rating, 1) : "–"}</b></td>
        <td class="num">${detailedRow ? `${num(s.goals_derived)}/${num(s.assists)}` : s.source ? `${num(s.goals)}/${num(s.assists)}` : "–"}</td><td class="num">${detailedRow ? num(s.npk_expected_goals, 2) : "–"}</td><td class="num">${detailedRow ? num(s.expected_assists, 2) : "–"}</td><td class="num">${detailedRow ? `${num(s.shots_on_target)}/${num(s.shots)}` : "–"}</td><td class="num">${detailedRow && s.pass_accuracy_pct_derived != null ? `${num(s.pass_accuracy_pct_derived, 1)} %` : "–"}</td><td class="num">${detailedRow ? num(s.key_passes) : "–"}</td><td class="num">${detailedRow ? num(s.possession_won) : "–"}</td><td class="num">${detailedRow ? num(s.possession_lost) : "–"}</td><td>${detailedRow ? statusBadge("FC26 Detail", "good") : s.source ? statusBadge("Snapshot-Delta", "blue") : statusBadge(p.join_status || "Direct")}</td></tr>`;
    };
    const performanceHeaders = [{ label: "Player" }, { label: "Pos.", cls: "center" }, { label: "Min.", cls: "num" }, { label: "Rating", cls: "num" }, { label: "G/A", cls: "num" }, { label: "NPK-xG", cls: "num" }, { label: "xA", cls: "num" }, { label: "SoT/Sh", cls: "num" }, { label: "Pass %", cls: "num" }, { label: "Key P.", cls: "num" }, { label: "Ball +", cls: "num" }, { label: "Ball -", cls: "num" }, { label: "Source" }];
    const homeTeamId = Number(m.home_team_ea_id), awayTeamId = Number(m.away_team_ea_id), managedTeamId = Number(d.snapshot?.managed_team_ea_id);
    const primaryTeamId = managedTeamId === homeTeamId || managedTeamId === awayTeamId ? managedTeamId : homeTeamId;
    const secondaryTeamId = primaryTeamId === homeTeamId ? awayTeamId : homeTeamId;
    const teamName = (id) => id === homeTeamId ? m.home_team_name : id === awayTeamId ? m.away_team_name : `Team ${id}`;
    const performanceTeam = (p) => Number(p.match_team_ea_id ?? p.team_ea_id);
    const primaryPerformances = d.performances.filter((p) => performanceTeam(p) === primaryTeamId);
    const secondaryPerformances = d.performances.filter((p) => performanceTeam(p) === secondaryTeamId);
    const unknownPerformances = d.performances.filter((p) => !Number.isFinite(performanceTeam(p)) || ![homeTeamId, awayTeamId].includes(performanceTeam(p)));
    if (unknownPerformances.length)
        primaryPerformances.push(...unknownPerformances);
    const hasTeamSplit = primaryPerformances.length > 0 && secondaryPerformances.length > 0;
    const performanceTable = (items) => items.length ? table(performanceHeaders, items.map(performanceRow)) : `<div class="card-body muted">No player performances were exported for this team.</div>`;
    const duplicateNote = Number(d.performanceDiagnostics?.suppressedSnapshotDuplicates || 0) > 0 ? `<div class="data-note">Tracker combined ${num(d.performanceDiagnostics.suppressedSnapshotDuplicates)} duplicate snapshot rating row${Number(d.performanceDiagnostics.suppressedSnapshotDuplicates) === 1 ? "" : "s"} for this match.</div>` : "";
    const performanceBody = hasTeamSplit ? `<div class="card-body" style="padding-bottom:0"><div class="tabbar match-performance-tabs"><button class="active" data-match-performance-team="primary">${esc(teamName(primaryTeamId))} <b>${num(primaryPerformances.length)}</b></button><button data-match-performance-team="secondary">${esc(teamName(secondaryTeamId))} <b>${num(secondaryPerformances.length)}</b></button></div></div><div data-match-performance-panel="primary">${performanceTable(primaryPerformances)}</div><div data-match-performance-panel="secondary" hidden>${performanceTable(secondaryPerformances)}</div>${duplicateNote}` : `${performanceTable(d.performances)}${duplicateNote}`;
    const detailedPlayers = new Map((detailed.players || []).map((p) => [Number(p.playerEaId), p]));
    const participants = new Map();
    for (const p of d.performances || []) {
        if (performanceTeam(p) === primaryTeamId && Number(p.minutes_played || 0) > 0)
            participants.set(Number(p.player_ea_id), { ...p, detailedStats: p.detailedStats || detailedPlayers.get(Number(p.player_ea_id))?.stats || null });
    }
    for (const p of detailed.players || []) {
        if (Number(p.teamEaId) === primaryTeamId && Number(p.stats?.minutes_played || 0) > 0 && !participants.has(Number(p.playerEaId)))
            participants.set(Number(p.playerEaId), { player_ea_id: Number(p.playerEaId), display_name: p.displayName || `Player ${p.playerEaId}`, minutes_played: p.stats?.minutes_played, actual_position: "", primary_position: p.primaryPosition, detailedStats: p.stats, match_team_ea_id: primaryTeamId });
    }
    const ownPlayers = [...participants.values()].sort((a, b) => Number(b.minutes_played || 0) - Number(a.minutes_played || 0));
    const selectedPlayer = ownPlayers[0] || null, selectedId = Number(selectedPlayer?.player_ea_id || 0);
    const posLayout = { GK: [50, 89], LB: [17, 70], LWB: [17, 64], LCB: [38, 71], CB: [50, 71], RCB: [62, 71], RB: [83, 70], RWB: [83, 64], LDM: [39, 55], CDM: [50, 56], RDM: [61, 55], LCM: [38, 49], CM: [50, 49], RCM: [62, 49], LM: [18, 35], LW: [18, 31], LF: [29, 27], CAM: [50, 34], RM: [82, 35], RW: [82, 31], RF: [71, 27], ST: [50, 17], CF: [50, 22] };
    const positionMapPlayers = ownPlayers.filter((p) => p.actual_position_source === 'career_playermatchratinghistory_position' && posLayout[String(p.actual_position || "").toUpperCase()]);
    const markerHtml = positionMapPlayers.map((p, index) => { const pos = String(p.actual_position || "").toUpperCase(), xy = posLayout[pos], same = positionMapPlayers.filter((q) => String(q.actual_position || "").toUpperCase() === pos), slot = same.indexOf(p), lane = (slot % 5) - Math.min(2, (same.length - 1) / 2), row = Math.floor(slot / 5), x = Math.max(8, Math.min(92, xy[0] + lane * 8)), y = Math.max(8, Math.min(92, xy[1] + row * 4)); return `<button class="commission-pitch-player ${Number(p.player_ea_id) === selectedId ? "selected" : ""}" style="left:${x}%;top:${y}%" data-match-player-select="${p.player_ea_id}" aria-label="${esc(p.display_name)} · observed ${esc(pos)}"><span>${esc(pos)}</span><small>${esc(String(p.display_name || "Player").split(" ").slice(-1)[0])}</small></button>`; }).join("");
    const playerCard = (p) => { const s = p?.detailedStats || {}, rated = p?.rating ?? s.game_rating, minutes = p?.minutes_played ?? s.minutes_played, goals = s.goals_derived ?? s.npk_goals, name = p?.display_name || "Select a player"; return `<div class="match-player-ai-card"><div class="card-title-row"><div><h3>${esc(name)}</h3><span>${p?.actual_position_source === 'career_playermatchratinghistory_position' ? `Observed ${esc(p.actual_position)}` : `Observed position N/D · registered ${esc(p?.primary_position || "N/D")}`} · ${minutes == null ? "N/D" : `${num(minutes)} min`}</span></div>${rated == null ? statusBadge("Rating N/D") : statusBadge(`Rating ${num(rated, 1)}`, "good")}</div><div class="match-player-ai-metrics"><span>G/A <b>${goals == null ? "N/D" : `${num(goals)}/${num(s.assists)}`}</b></span><span>NPK-xG <b>${s.npk_expected_goals == null ? "N/D" : num(s.npk_expected_goals, 2)}</b></span><span>Finalizações <b>${s.shots == null ? "N/D" : num(s.shots)}</b></span><span>Passes certos <b>${s.pass_accuracy_pct_derived == null ? "N/D" : `${num(s.pass_accuracy_pct_derived, 1)} %`}</b></span><span>Desarmes <b>${s.tackles == null ? "N/D" : num(s.tackles)}</b></span><span>Interceptações <b>${s.interceptions == null ? "N/D" : num(s.interceptions)}</b></span></div><div class="row-actions"><button class="button primary" data-commission-report data-report-target="match-player-${p?.player_ea_id}" data-mode="match_player" data-fixture-id="${m.fixture_id}" data-player-ea-id="${p?.player_ea_id}" data-snapshot-id="${state.snapshotId}">Analyze this player</button>${p?.player_ea_id ? `<button class="button" data-player="${p.player_ea_id}">Open player profile</button>` : ""}</div><div data-commission-report-output data-report-slot="match-player-${p?.player_ea_id}" class="commission-report-output" aria-live="polite">Select this player to view or generate the match-specific analysis.</div></div>`; };
    const playerCards = ownPlayers.map((p) => `<div data-match-player-panel="${num(p.player_ea_id)}" ${Number(p.player_ea_id) === selectedId ? "" : "hidden"}>${playerCard(p)}</div>`).join("");
    const reportCache = m.is_completed ? await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(state.snapshotId)}&mode=match&fixture_id=${Number(m.fixture_id)}`).catch(() => ({ state: "missing" })) : ({ state: "missing" });
    const savedReport = reportCache.result || {}, savedBody = savedReport.report || {}, savedCatalog = new Map((savedReport.fact_catalog || []).map((f) => [f.id, f.label]));
    const savedRefs = (ids) => esc((ids || []).map((id) => savedCatalog.get(id) || id).join(" · "));
    const kindLabel = (kind) => kind === "fact" ? tr("claimFact") : kind === "hypothesis" ? tr("claimHypothesis") : tr("claimInference");
    const savedItems = (items) => items?.length ? `<ul>${items.map((item) => `<li><span class="commission-claim-kind ${esc(item.kind || "inference")}">${esc(kindLabel(item.kind))}</span> ${esc(item.text)}${item.kind === "hypothesis" && item.limitations ? `<small class="commission-claim-limit">${tr("claimLimit")}: ${esc(item.limitations)}</small>` : ""}<small class="table-subline">Atlas sources: ${savedRefs(item.fact_refs)}</small></li>`).join("")}</ul>` : "";
    const commissionNote = savedBody.commission_note?.text ? `<p class="commission-note"><strong>${tr("commissionNote")}:</strong> ${esc(savedBody.commission_note.text)}<small>${savedRefs(savedBody.commission_note.fact_refs)}</small></p>` : "";
    const reportReview = savedReport.review_required ? `<p class="chart-note">Some claims were filtered by source-scope checks; the remaining analysis is still shown.</p>` : "";
    const matchReportOutput = reportCache.state === "ready" || reportCache.state === "stale" ? `${reportReview}<div class="commission-report-head"><strong>${esc(savedBody.summary?.text || "Saved technical report")}</strong><small><span class="commission-claim-kind ${esc(savedBody.summary?.kind || "inference")}">${esc(kindLabel(savedBody.summary?.kind))}</span> · ${esc(savedReport.model || "Ollama local")} · ${esc(reportCache.generated_at || "")}</small></div>${savedBody.summary?.limitations ? `<p class="commission-claim-limit">Limit: ${esc(savedBody.summary.limitations)}</p>` : ""}${commissionNote}${savedItems(savedBody.observations)}${savedItems(savedBody.recommendations)}${commissionFollowupForm(savedBody.information_requests, { snapshot_id: Number(state.snapshotId), mode: "match", fixture_id: Number(m.fixture_id), model: savedReport.model, coach_context: savedReport.fact_catalog?.find((f) => f.id === "coach_context")?.value })}<details class="report-provenance"><summary>Evidence coverage and validation</summary><small>${num(savedReport.validation?.accepted_claims)} claims kept · ${num(savedReport.validation?.rejected_claims)} filtered · ${esc(savedReport.validation?.interpretation_quality || "Interpretation quality not independently scored")} · ${savedRefs(savedBody.summary?.fact_refs)}</small></details>` : reportCache.state === "queued" || reportCache.state === "running" ? "The Technical Commission is analyzing this match in the background. You can keep using Atlas." : "Generate a contextual report from this match and its prior recorded performances. The analysis is saved with this career's data.";
    const matchReportSection = `<section class="card"><header class="card-header"><div><h2>Technical Commission diagnosis</h2><p>Match indicators in context of prior recorded performances</p></div><span class="status-badge ${reportCache.state === "ready" ? "good" : ""}">${esc(reportCache.state || "missing")}</span></header><div class="card-body"><div data-commission-report-output data-report-slot="match-overall" class="commission-report-output" aria-live="polite">${matchReportOutput}</div>${m.is_completed ? `<button class="button primary" data-commission-report data-mode="match" data-fixture-id="${m.fixture_id}" data-snapshot-id="${num(state.snapshotId)}" data-force-refresh="${reportCache.state === "ready" ? "1" : "0"}">${reportCache.state === "ready" ? "Refresh match analysis" : "Generate match analysis"}</button>` : '<p class="muted">Analysis becomes available when the match is complete.</p>'}</div></section>`;
    const observedPositionSection = `<section class="grid match-commission-layout"><section class="card"><header class="card-header"><div><h2>Recorded player positions</h2><p>Only positions from the match-rating history are plotted. This is not a starting formation.</p></div><span class="status-badge ${positionMapPlayers.length ? "good" : "amber"}">${positionMapPlayers.length ? `${positionMapPlayers.length} observed` : "no reliable positions"}</span></header><div class="match-pitch-wrap"><div class="match-pitch-direction">Opponent goal ↑<span>Observed position labels</span></div><div class="commission-match-pitch"><i class="pitch-half"></i><i class="pitch-circle"></i><i class="pitch-area top"></i><i class="pitch-area bottom"></i>${markerHtml || '<span class="pitch-empty">No reliable match-specific positions recorded.<br>Unknown positions stay in the player list below.</span>'}</div><p class="pitch-caveat">Dots show recorded positions only. They do not prove role, movement, formation, or starting status.</p></div><div class="card-body match-player-list">${ownPlayers.length ? ownPlayers.map((p) => `<button class="match-player-list-row ${Number(p.player_ea_id) === selectedId ? "active" : ""}" data-match-player-select="${p.player_ea_id}"><span class="match-player-token">${esc(p.actual_position_source === 'career_playermatchratinghistory_position' ? p.actual_position : "N/D")}</span><span><b>${esc(p.display_name || "Player")}</b><small>${p.actual_position_source === 'career_playermatchratinghistory_position' ? `Observed ${esc(p.actual_position)}` : `Observed N/D · registered ${esc(p.primary_position || "N/D")}`} · ${num(p.minutes_played ?? p.detailedStats?.minutes_played)} min</small></span><strong>${p.rating != null ? num(p.rating, 1) : p.detailedStats?.game_rating != null ? num(p.detailedStats.game_rating, 1) : "N/D"}</strong></button>`).join("") : '<span class="muted">No managed-team appearances were recorded for this fixture.</span>'}</div></section><section class="card match-player-analysis"><header class="card-header"><div><h2>Individual match analysis</h2><p>Compare this performance with the player's own recent data</p></div></header>${playerCards || '<div class="card-body muted">No detailed player rows are linked to this match.</div>'}</section></section>`;

    // P0: uses only canonical MatchStats and pre-match evidence already available in Atlas.
    const p0Lexicon = {
        "pt-BR":{nav:"Seções da partida",stats:"Estatísticas",commission:"Comissão técnica",players:"Jogadores",positions:"Posições observadas",key:"Indicadores da partida",npkxg:"NPK-xG",shots:"Finalizações",target:"No alvo",passing:"Passes certos",keypasses:"Passes-chave",won:"Recuperações de posse",match:"Nesta partida",last5:"Até 5 anteriores",season:"Histórico anterior",indicator:"Indicador",context:"Partida em contexto",contextNote:"Médias por partida, calculadas apenas sobre registros anteriores vinculados.",noHistory:"O histórico comparável aparecerá após a análise contextual, quando houver dados suficientes.",noStats:"MatchStats detalhados indisponíveis; os dados existentes permanecem acessíveis.",highlights:"Destaques objetivos",highlightsNote:"Líderes estatísticos, não classificação tática.",rating:"Maior nota registrada",xg:"Maior NPK-xG individual",recovery:"Mais recuperações registradas",noPlayers:"Sem desempenho individual detalhado suficiente.",coverage:"Cobertura e proveniência"},
        "en-GB":{nav:"Match sections",stats:"Statistics",commission:"Technical commission",players:"Players",positions:"Observed positions",key:"Match indicators",npkxg:"NPK-xG",shots:"Shots",target:"On target",passing:"Pass accuracy",keypasses:"Key passes",won:"Possession won",match:"This match",last5:"Up to 5 earlier",season:"Prior history",indicator:"Indicator",context:"Match in context",contextNote:"Per-match averages from linked records strictly before this fixture.",noHistory:"Comparable history appears after contextual analysis, when sufficient data is available.",noStats:"Detailed MatchStats unavailable; existing records remain accessible.",highlights:"Objective highlights",highlightsNote:"Statistical leaders, not a tactical ranking.",rating:"Highest recorded rating",xg:"Highest individual NPK-xG",recovery:"Most possession won",noPlayers:"Insufficient detailed player data.",coverage:"Coverage and provenance"},
        "es-ES":{nav:"Secciones del partido",stats:"Estadísticas",commission:"Comisión técnica",players:"Jugadores",positions:"Posiciones observadas",key:"Indicadores del partido",npkxg:"NPK-xG",shots:"Remates",target:"A puerta",passing:"Precisión de pase",keypasses:"Pases clave",won:"Recuperaciones",match:"Este partido",last5:"Hasta 5 anteriores",season:"Historial anterior",indicator:"Indicador",context:"Partido en contexto",contextNote:"Medias por partido de registros anteriores vinculados.",noHistory:"El historial comparable aparece tras el análisis contextual, cuando hay datos suficientes.",noStats:"MatchStats detallados no disponibles; los registros existentes siguen accesibles.",highlights:"Destacados objetivos",highlightsNote:"Líderes estadísticos, no una clasificación táctica.",rating:"Mayor nota registrada",xg:"Mayor NPK-xG individual",recovery:"Más recuperaciones",noPlayers:"Sin datos individuales detallados suficientes.",coverage:"Cobertura y procedencia"}
    };
    const p0T = atlasLanguage()==="en-GB" ? p0Lexicon["en-GB"] : atlasLanguage()==="es-ES" ? p0Lexicon["es-ES"] : p0Lexicon["pt-BR"];
    const p0Metrics = [
        {label:p0T.npkxg,home:homeStats.npk_expected_goals,away:awayStats.npk_expected_goals,precision:2,suffix:""},
        {label:p0T.shots,home:homeStats.shots,away:awayStats.shots,precision:0,suffix:""},
        {label:p0T.target,home:homeStats.shots_on_target,away:awayStats.shots_on_target,precision:0,suffix:""},
        {label:p0T.passing,home:homeStats.pass_accuracy_pct_derived,away:awayStats.pass_accuracy_pct_derived,precision:1,suffix:"%"}
    ];
    const p0QuickStats = hasDetailed ? `<section class="match-p0-metrics"><div class="match-p0-legend"><strong>${esc(m.home_team_name)}</strong><span>${esc(p0T.key)}</span><strong>${esc(m.away_team_name)}</strong></div><div class="match-p0-metric-grid">${p0Metrics.map(item=>`<article class="match-p0-metric"><span>${esc(item.label)}</span><div class="match-p0-values"><b>${num(item.home,item.precision)}${item.home==null?"":item.suffix}</b><i aria-hidden="true">/</i><b>${num(item.away,item.precision)}${item.away==null?"":item.suffix}</b></div></article>`).join("")}</div></section>`
        : `<section class="card pad match-p0-unavailable">${esc(p0T.noStats)}</section>`;
    const p0Facts = Array.isArray(savedReport.fact_catalog) ? savedReport.fact_catalog : [];
    const p0HistoryFact = p0Facts.find((item)=>item.id==="pre_match_team_context");
    const p0History = reportCache.state==="ready" ? (p0HistoryFact?.value||null) : null;
    const p0ManagedHome = Number(m.home_team_ea_id)===Number(d.snapshot?.managed_team_ea_id);
    const p0ManagedStats = p0ManagedHome ? homeStats : awayStats;
    const p0HistoricalIndicators = [
        {label:p0T.npkxg,key:"npk_expected_goals",digits:2},
        {label:p0T.shots,key:"shots",digits:1},
        {label:p0T.keypasses,key:"key_passes",digits:1},
        {label:p0T.won,key:"possession_won",digits:1}
    ];
    const p0HistoricalTable = hasDetailed && p0History && Number(p0History.lookback_matches||0)>0
        ? `<div class="match-p0-table-scroll"><table class="match-p0-context-table"><thead><tr><th scope="col">${esc(p0T.indicator)}</th><th scope="col">${esc(p0T.match)}</th><th scope="col">${esc(p0T.last5)} (${num((p0History.recent_five||[]).length)})</th><th scope="col">${esc(p0T.season)} (${num(p0History.lookback_matches)})</th></tr></thead><tbody>${p0HistoricalIndicators.map(item=>`<tr><th scope="row">${esc(item.label)}</th><td>${num(p0ManagedStats[item.key],item.digits)}</td><td>${num(p0History.last_five_reference?.for?.[item.key],item.digits)}</td><td>${num(p0History.season_to_date_reference?.for?.[item.key],item.digits)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="match-p0-empty muted">${esc(p0T.noHistory)}</p>`;
    const p0ContextPanel = `<section class="card match-p0-context"><header class="card-header"><div><h2>${esc(p0T.context)}</h2><p>${esc(p0T.contextNote)}</p></div></header>${p0HistoricalTable}</section>`;
    const p0HighestRating = ownPlayers.filter((p)=>(p.rating??p.detailedStats?.game_rating)!=null).sort((a,b)=>Number(b.rating??b.detailedStats?.game_rating)-Number(a.rating??a.detailedStats?.game_rating))[0];
    const p0HighestXg = ownPlayers.filter((p)=>Number(p.detailedStats?.npk_expected_goals||0)>0).sort((a,b)=>Number(b.detailedStats.npk_expected_goals)-Number(a.detailedStats.npk_expected_goals))[0];
    const p0HighestWon = ownPlayers.filter((p)=>p.detailedStats?.possession_won!=null).sort((a,b)=>Number(b.detailedStats.possession_won)-Number(a.detailedStats.possession_won))[0];
    const p0Leaders = [
        {label:p0T.rating,player:p0HighestRating,value:p0HighestRating==null?"":num(p0HighestRating.rating??p0HighestRating.detailedStats?.game_rating,1)},
        {label:p0T.xg,player:p0HighestXg,value:p0HighestXg==null?"":num(p0HighestXg.detailedStats?.npk_expected_goals,2)},
        {label:p0T.recovery,player:p0HighestWon,value:p0HighestWon==null?"":num(p0HighestWon.detailedStats?.possession_won)}
    ].filter(item=>item.player);
    const p0HighlightsPanel = `<section class="card match-p0-highlights"><header class="card-header"><div><h2>${esc(p0T.highlights)}</h2><p>${esc(p0T.highlightsNote)}</p></div></header><div class="match-p0-leaders">${p0Leaders.length?p0Leaders.map(item=>`<div class="match-p0-leader"><span>${esc(item.label)}</span><strong>${playerLink(item.player.player_ea_id,item.player.display_name)}</strong><b>${item.value}</b></div>`).join(""):`<p class="muted">${esc(p0T.noPlayers)}</p>`}</div></section>`;
    const p0Navigation = `<nav class="match-p0-nav" aria-label="${esc(p0T.nav)}"><a href="#p0-match-comparison">${esc(p0T.stats)}</a><a href="#p0-match-commission">${esc(p0T.commission)}</a><a href="#p0-match-players">${esc(p0T.players)}</a><a href="#p0-match-positions">${esc(p0T.positions)}</a></nav>`;

    content.innerHTML = `<div class="content-inner wide">${pageHead("Match report", `${dateText(m.date)} · ${esc(timeText(m.time))}`, `<button class="button" data-route="match-center">Match Center</button>`)}
      <section class="card fixture-hero"><div class="fixture-meta"><span class="inline-identity">${identityLogo(d.competitionIdentity, m.competition_name, "inline-logo")}${competitionLink(m.competition_object_id, m.competition_name)}</span> · ${m.is_completed ? "COMPLETED" : "SCHEDULED"}</div><div class="fixture-scoreboard"><div class="fixture-club">${identityLogo(d.homeIdentity, m.home_team_name, "fixture-club-logo")}<h2>${clubLink(m.home_team_ea_id, m.home_team_name)}</h2></div><div class="fixture-score">${m.is_completed ? `${num(m.home_score)} : ${num(m.away_score)}` : "VS"}<small>${m.home_penalties != null || m.away_penalties != null ? `Penalty shoot-out ${num(m.home_penalties)}:${num(m.away_penalties)}` : esc(m.managed_team_result || "")}</small></div><div class="fixture-club">${identityLogo(d.awayIdentity, m.away_team_name, "fixture-club-logo")}<h2>${clubLink(m.away_team_ea_id, m.away_team_name)}</h2></div></div></section>
      ${p0Navigation}${p0QuickStats}<div class="match-p0-main"><div class="match-p0-primary" id="p0-match-comparison">${comparison||`<section class="card pad">${esc(p0T.noStats)}</section>`}${p0ContextPanel}</div><aside class="match-p0-secondary"><div id="p0-match-commission">${matchReportSection}</div>${p0HighlightsPanel}</aside></div>${events}
      <section id="p0-match-players" class="card match-performance-section"><header class="card-header"><div><h2>Player performances</h2><p>${hasDetailed ? "Direct FC26 match data for exported participants" : "Detailed MatchStats unavailable; ratings and conservative snapshot reconstruction are shown when recorded"}</p></div></header>${d.performances.length ? performanceBody : `<div class="card-body muted">No player performances were exported for this match.</div>`}</section>
      <details id="p0-match-positions" class="match-p0-fold"><summary>${esc(p0T.positions)}</summary>${observedPositionSection}</details>${stadiumSection}<details class="match-p0-fold match-p0-provenance"><summary>${esc(p0T.coverage)}</summary><section class="card pad match-coverage-section"><h3 class="card-title">Data coverage</h3><div class="grid metrics compact">${metric("Match ratings", d.capabilities?.matchRatings ? "Available" : "Partial", "ratings and minutes")}${metric("Detailed FC26 data", hasDetailed ? "Available" : "Not available", hasDetailed ? `${num(detailed.players?.length || 0)} participants` : "snapshot data fallback", hasDetailed ? "green" : "amber")}${metric("Events", hasDetailed ? num(detailed.events?.length || 0) : "–", hasDetailed ? "not chronological · no confirmed minutes" : "no detailed source")}${metric("Link confidence", hasDetailed ? `${num(detailed.linkageConfidence * 100, 0)} %` : "–", "import linkage metadata")}${metric("xG model", hasDetailed ? (homeStats.expected_goals_derived != null || awayStats.expected_goals_derived != null ? "Team-xG + NPK-xG" : "NPK-xG") : "–", hasDetailed ? (homeStats.expected_goals_derived != null || awayStats.expected_goals_derived != null ? "Team-xG = NPK-xG + 0.7 × penalty attempts" : "direct FC26 NPK value") : "")}</div><p class="data-note">${esc(detailed.xgNote || "")} ${esc(detailed.eventTimingNote || "")}</p></section></details>
    </div>`;
    $$('[data-match-player-select]', content).forEach((button) => button.onclick = async () => { const id = String(button.dataset.matchPlayerSelect); $$('[data-match-player-select]', content).forEach((node) => node.classList.toggle("selected", String(node.dataset.matchPlayerSelect) === id)); $$('[data-match-player-panel]', content).forEach((panel) => panel.hidden = panel.dataset.matchPlayerPanel !== id); $$('.match-player-list-row', content).forEach((node) => node.classList.toggle("active", String(node.dataset.matchPlayerSelect) === id)); const output = $(`[data-report-slot="match-player-${id}"]`, content); if (!output)
        return; output.textContent = "Checking the saved analysis for this player and match…"; const cached = await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(state.snapshotId)}&mode=match_player&fixture_id=${Number(m.fixture_id)}&player_ea_id=${Number(id)}`).catch(() => ({ state: "missing" })); const result = cached.result || {}, report = result.report || {}, catalog = new Map((result.fact_catalog || []).map((f) => [f.id, f.label])), refs = (items) => esc((items || []).map((ref) => catalog.get(ref) || ref).join(" · ")), kindLabel = (kind) => kind === "fact" ? tr("claimFact") : kind === "hypothesis" ? tr("claimHypothesis") : tr("claimInference"), renderItems = (items) => items?.length ? `<ul>${items.map((item) => `<li><span class="commission-claim-kind ${esc(item.kind || "inference")}">${esc(kindLabel(item.kind))}</span> ${esc(item.text)}${item.kind === "hypothesis" && item.limitations ? `<small class="commission-claim-limit">${tr("claimLimit")}: ${esc(item.limitations)}</small>` : ""}<small class="table-subline">Atlas sources: ${refs(item.fact_refs)}</small></li>`).join("")}</ul>` : ""; output.innerHTML = cached.state === "ready" || cached.state === "stale" ? `<div class="commission-report-head"><strong>${esc(report.summary?.text || "Saved player analysis")}</strong><small><span class="commission-claim-kind ${esc(report.summary?.kind || "inference")}">${esc(kindLabel(report.summary?.kind))}</span> · ${esc(result.model || "Ollama local")} · ${esc(cached.generated_at || "")}</small></div>${report.summary?.limitations ? `<p class="commission-claim-limit">${tr("claimLimit")}: ${esc(report.summary.limitations)}</p>` : ""}${renderItems(report.strengths)}${renderItems(report.development_areas)}${renderItems(report.training_suggestions)}${renderItems(report.observations)}${renderItems(report.recommendations)}${commissionFollowupForm(report.information_requests, { snapshot_id: Number(state.snapshotId), mode: "match_player", fixture_id: Number(m.fixture_id), player_ea_id: Number(id), model: result.model, coach_context: result.fact_catalog?.find((f) => f.id === "coach_context")?.value })}<details class="report-provenance"><summary>Evidence coverage and validation</summary><small>${num(result.validation?.accepted_claims)} claims kept · ${num(result.validation?.rejected_claims)} filtered · ${esc(result.validation?.interpretation_quality || "Interpretation quality not independently scored")} · ${refs(report.summary?.fact_refs)}</small></details>` : cached.state === "queued" || cached.state === "running" ? "The local model is preparing this player's match analysis in the background." : "No saved analysis exists for this player in this match yet."; });
    $$("[data-match-performance-team]", content).forEach((button) => button.onclick = () => {
        const key = button.dataset.matchPerformanceTeam;
        $$("[data-match-performance-team]", content).forEach((item) => item.classList.toggle("active", item.dataset.matchPerformanceTeam === key));
        $$("[data-match-performance-panel]", content).forEach((panel) => panel.hidden = panel.dataset.matchPerformancePanel !== key);
    });
}
async function renderCompetitions() {
    const d = await api(`/api/snapshots/${state.snapshotId}/competitions`);
    const mode = state.competitionListTab || "deeper";
    const q = state.competitionQuery.toLowerCase();
    const deeper = (d.competitions || []).filter((c) => !q || String(c.competition_name || "").toLowerCase().includes(q));
    const atlas = (d.worldCompetitions || []).filter((c) => !q || String(c.leagueName || "").toLowerCase().includes(q));
    const tabs = `<div class="tabbar"><button data-competition-list-tab="deeper" class="${mode === "deeper" ? "active" : ""}">Deeper Simulation <b>${num((d.competitions || []).length)}</b></button><button data-competition-list-tab="atlas" class="${mode === "atlas" ? "active" : ""}">atlas-world-simulation <b>${num((d.worldCompetitions || []).length)}</b></button></div>`;
    const deeperCards = `<div class="grid competition-grid">${deeper.map((c) => `<button class="competition-card card" data-competition="${c.competition_object_id}"><div class="competition-top">${identityLogo(c.identity, c.competition_name, "competition-logo-card")}<div><h3>${esc(c.competition_name)}</h3><p>Object ID ${num(c.competition_object_id)}${c.identity?.mediaCompetitionId ? ` · Media ID ${num(c.identity.mediaCompetitionId)}` : ""}</p></div></div><div class="competition-format-line">${statusBadge(c.notStarted ? "Not started" : (c.format?.label || "Detecting format"), c.notStarted ? "blue" : c.format?.type === "league" ? "good" : c.format?.type === "hybrid" ? "amber" : "")}</div><div class="competition-stats"><div><strong>${num(c.fixture_count)}</strong><small>Matches</small></div><div><strong>${num(c.completed)}</strong><small>Completed</small></div><div><strong>${num(c.managed_matches)}</strong><small>Your club</small></div></div><div class="change-fields">${(c.sources || []).map((source) => `<span class="mini-tag">${esc(source)}</span>`).join("")}</div></button>`).join("")}</div>`;
    const atlasCards = `<div class="grid competition-grid">${atlas.map((league) => `<button class="competition-card card atlas-world-card" data-world-competition="${rawNumber(league.leagueEaId)}"><div class="competition-top">${identityLogo(league.identity, league.leagueName, "competition-logo-card")}<div><h3>${esc(league.leagueName)}</h3><p>League ID ${num(league.leagueEaId)} · ${num(league.teamCount)} clubs</p></div></div><div class="competition-format-line">${statusBadge(league.tableSourceLabel || "Atlas World Simulation", league.tableSource === "fc_aggregate" ? "good" : "blue")}</div><div class="competition-stats"><div><strong>${num(league.matchesPlayed)}</strong><small>Matches per team</small></div><div><strong>${num(league.completedRounds)}</strong><small>of ${num(league.totalRounds)} rounds</small></div><div><strong>${num(Number(league.progress || 0) * 100)} %</strong><small>Season progress</small></div></div><div class="data-note">Season ${dateText(league.seasonStart)}–${dateText(league.seasonEnd)}${league.lastUpdateDate ? ` · last simulation state ${dateText(league.lastUpdateDate)}` : " · not started yet"}</div></button>`).join("")}</div>`;
    const count = mode === "deeper" ? deeper.length : atlas.length;
    content.innerHTML = `<div class="content-inner">${pageHead("Competitions", "Reliable EA competitions and clearly separated Atlas league models")}${tabs}<div class="filter-row"><input id="competitionQuery" class="filter-input" value="${esc(state.competitionQuery)}" placeholder="Search competitions…"><span class="chip">${num(count)} competitions</span></div>${mode === "deeper" ? deeperCards : atlasCards}</div>`;
    $("#competitionQuery", content).oninput = (event) => { state.competitionQuery = event.target.value; render(); };
}
async function renderWorldCompetition() {
    const d = await api(`/api/snapshots/${state.snapshotId}/world-leagues/${Number(state.routeData.id)}`);
    const calendar = d.calendar || {}, isFc = d.tableSource === "fc_aggregate", partial = (d.items || []).some((item) => item.aggregate_only);
    const rows = (d.items || []).map((r) => `<tr><td class="center"><b>${num(r.position)}</b></td><td><span class="inline-identity">${identityLogo(r.identity, r.team_name, "table-club-logo")}${clubLink(r.team_ea_id, r.team_name)}</span></td><td class="num">${num(r.matches_played)}</td><td class="num">${r.aggregate_only ? "–" : num(r.wins)}</td><td class="num">${r.aggregate_only ? "–" : num(r.draws)}</td><td class="num">${r.aggregate_only ? "–" : num(r.losses)}</td><td class="num">${r.aggregate_only ? "–" : `${num(r.goals_for)}:${num(r.goals_against)}`}</td><td class="num">${r.aggregate_only ? "–" : `${Number(r.goal_difference) > 0 ? "+" : ""}${num(r.goal_difference)}`}</td><td class="num"><b>${num(r.points)}</b></td></tr>`);
    const split = (title, items) => items?.length ? `<details class="league-split-table"><summary>${esc(title)}</summary>${table([{ label: "#", cls: "center" }, { label: "Club" }, { label: "P", cls: "num" }, { label: "W", cls: "num" }, { label: "D", cls: "num" }, { label: "L", cls: "num" }, { label: "Goals", cls: "num" }, { label: "GD", cls: "num" }, { label: "Pts", cls: "num" }], items.map((r) => `<tr><td class="center"><b>${num(r.position)}</b></td><td><span class="inline-identity">${identityLogo(r.identity, r.team_name, "table-club-logo")}${clubLink(r.team_ea_id, r.team_name)}</span></td><td class="num">${num(r.matches_played)}</td><td class="num">${num(r.wins)}</td><td class="num">${num(r.draws)}</td><td class="num">${num(r.losses)}</td><td class="num">${num(r.goals_for)}:${num(r.goals_against)}</td><td class="num">${Number(r.goal_difference) > 0 ? "+" : ""}${num(r.goal_difference)}</td><td class="num"><b>${num(r.points)}</b></td></tr>`).join(""))}</details>` : "";
    content.innerHTML = `<div class="content-inner wide">${pageHead(d.leagueName || `League ${num(d.leagueEaId)}`, `Atlas World · League ID ${num(d.leagueEaId)}`, `<button class="button" data-route="competitions">All competitions</button>`)}
      <section class="card competition-identity-hero" ${identityStyle(d.identity)}><div>${identityLogo(d.identity, d.leagueName, "competition-hero-logo")}</div><div><p>ATLAS WORLD</p><h2>${esc(d.leagueName || `League ${d.leagueEaId}`)}</h2><div class="profile-badges"><span class="chip">League ID ${num(d.leagueEaId)}</span>${d.identity?.logo ? statusBadge("Competition logo assigned", "good") : statusBadge("No logo found")}${statusBadge(isFc ? "FC26 table + Atlas player statistics" : (d.modelId || "Atlas World Simulation"), isFc ? "good" : "blue")}</div></div>${trophyImage(d.identity, d.leagueName, "competition-trophy")}</section>
      <div class="grid metrics">${metric("Clubs", num((d.items || []).length), "current league participants")}${metric("Rounds", `${num(calendar.completedRounds)} / ${num(calendar.totalRounds)}`, calendar.lastUpdateDate ? `As of ${dateText(calendar.lastUpdateDate)}` : "Season not started yet", "green")}${metric("Progress", `${num(Number(calendar.progress || 0) * 100)} %`, `${dateText(calendar.seasonStart)}–${dateText(calendar.seasonEnd)}`, "blue")}${metric("Matches per team", num(Math.max(0, ...(d.items || []).map((item) => Number(item.matches_played || 0)))), isFc ? "FC26 table" : "simulated table")}</div>
      <div class="grid split-65">
        <div><section class="card"><header class="card-header"><div><h2>League table</h2><p>${isFc ? (partial ? "Partial FC26 aggregate from an older snapshot" : "Complete FC26 table; player statistics are linked to it") : "Consistent Tracker table advanced every Saturday"}</p></div>${statusBadge(isFc ? "FC26 table" : "Atlas simulation", isFc ? "good" : "blue")}</header>${rows.length ? table([{ label: "#", cls: "center" }, { label: "Club" }, { label: "P", cls: "num" }, { label: "W", cls: "num" }, { label: "D", cls: "num" }, { label: "L", cls: "num" }, { label: "Goals", cls: "num" }, { label: "GD", cls: "num" }, { label: "Pts", cls: "num" }], rows) : `<div class="card-body muted">No table is available for this league on the selected date.</div>`}${split("Home table", d.homeItems || [])}${split("Away table", d.awayItems || [])}<div class="data-note">${esc(d.notice || "")}</div></section></div>
        <aside class="grid">
          <section class="card"><header class="card-header"><h2>Top scorers</h2></header><div class="card-body list">${leaderList(d.topScorers, "Goals", (p) => num(p.goals))}</div></section>
          <section class="card"><header class="card-header"><h2>Top assists</h2></header><div class="card-body list">${leaderList(d.topAssists, "Assists", (p) => num(p.assists))}</div></section>
          <section class="card"><header class="card-header"><div><h2>Top ratings</h2><p>At least ${num(d.ratingMinimumAppearances)} appearances</p></div></header><div class="card-body list">${leaderList(d.topRatings, "Avg rating", (p) => ratingValue(p.average_rating, true))}</div></section>
        </aside>
      </div>
    </div>`;
}
function leaderList(rows, metricName, formatter) { return rows?.length ? rows.map((p, index) => `<div class="list-row leader-row"><span class="leader-rank">${index + 1}</span>${playerPortrait(p.media, p.display_name, "list-portrait")}<div class="list-main">${playerLink(p.player_ea_id, p.display_name)}<small>${clubLink(p.represented_team_ea_id, p.represented_team_name)} · ${num(p.appearances)} appearances</small></div><div class="list-value"><strong>${formatter(p)}</strong><small>${esc(metricName)}</small></div></div>`).join("") : '<span class="muted">No matching season statistics.</span>'; }
function competitionFixtureTable(fixtures) {
    return table([{ label: "Date" }, { label: "Home" }, { label: "Result", cls: "center" }, { label: "Away" }, { label: "Status" }, { label: "", sortable: false }], fixtures.map((m) => {
        const advanced = Number(m.advanced_team_id);
        const homeAdvanced = Number.isFinite(advanced) && advanced === Number(m.home_team_ea_id);
        const awayAdvanced = Number.isFinite(advanced) && advanced === Number(m.away_team_ea_id);
        const homeWon = m.is_completed && Number(m.home_score) > Number(m.away_score);
        const awayWon = m.is_completed && Number(m.away_score) > Number(m.home_score);
        const decision = m.decision_label || "Advanced";
        const scoreExtra = m.aggregate_score ? `<small class="aggregate-note">Aggregate ${esc(m.aggregate_score)}</small>` : (m.penalty_home_score != null || m.penalty_away_score != null ? `<small class="aggregate-note">${num(m.penalty_home_score)}:${num(m.penalty_away_score)} pens</small>` : "");
        const teamCell = (side, isAdvanced, isWinner) => {
            const identity = side === "home" ? m.homeIdentity : m.awayIdentity;
            const id = side === "home" ? m.home_team_ea_id : m.away_team_ea_id;
            const name = side === "home" ? m.home_team_name : m.away_team_name;
            return `<span class="inline-identity knockout-team ${isAdvanced ? "knockout-advanced" : isWinner ? "match-winner" : ""}">${identityLogo(identity, name, "table-club-logo")}${clubLink(id, name)}${isAdvanced ? statusBadge(decision, decision === "Cup winner" ? "winner" : "good") : ""}</span>`;
        };
        return `<tr class="${homeAdvanced || awayAdvanced ? "knockout-decided" : ""}"><td data-sort="${esc(m.date || "")}">${dateText(m.date)}</td><td>${teamCell("home", homeAdvanced, homeWon)}</td><td class="center"><b>${m.is_completed ? `${num(m.home_score)}:${num(m.away_score)}` : "–"}</b>${scoreExtra}</td><td>${teamCell("away", awayAdvanced, awayWon)}</td><td>${m.is_completed ? statusBadge("Completed", "good") : statusBadge("Scheduled")}</td><td>${matchLink(m.fixture_id, "Details")}</td></tr>`;
    }));
}
function competitionGroups(groups, mode, formatType) {
    const filtered = groups.map((group) => ({ ...group, fixtures: group.fixtures.filter((match) => mode === "results" ? match.is_completed : !match.is_completed) })).filter((group) => group.fixtures.length);
    if (!filtered.length)
        return { html: '<div class="card-body muted">No matches in this view.</div>', groups: [] };
    const defaultIndex = mode === "results" ? filtered.length - 1 : 0;
    const prefix = formatType === "league" ? "Matchday" : formatType === "hybrid" ? "Phase / matchday" : "Round";
    const html = `<div class="fixture-groups">${filtered.map((group, index) => `<details class="fixture-group" data-fixture-group="${index}" ${index === defaultIndex ? "open" : ""}><summary><div><strong>${esc(group.label.replace("Matchday / round", prefix))}</strong><small>${num(group.fixtures.length)} matches</small></div><span>${mode === "results" ? `${num(group.fixtures.filter((m) => m.is_completed).length)} Results` : `${num(group.fixtures.filter((m) => !m.is_completed).length)} open`}</span></summary><div class="fixture-group-lazy" data-loaded="${index === defaultIndex ? "1" : "0"}">${index === defaultIndex ? competitionFixtureTable(group.fixtures) : '<div class="lazy-fixture-placeholder">Load when opened</div>'}</div></details>`).join("")}</div>`;
    return { html, groups: filtered };
}
function bindCompetitionGroups(view) {
    $$('.fixture-group[data-fixture-group]', content).forEach((details) => details.addEventListener('toggle', () => {
        if (!details.open)
            return;
        const host = $('.fixture-group-lazy', details);
        if (!host || host.dataset.loaded === '1')
            return;
        const index = Number(details.dataset.fixtureGroup);
        const group = view.groups[index];
        if (!group)
            return;
        host.innerHTML = competitionFixtureTable(group.fixtures);
        host.dataset.loaded = '1';
        bindSortableTables();
        $$('[data-player]', host).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate("player", { id: Number(n.dataset.player), tab: "overview" }); });
        $$('[data-club]', host).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate("club", { id: Number(n.dataset.club) }); });
        $$('[data-match]', host).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate("match", { id: Number(n.dataset.match) }); });
    }));
}
async function renderCompetition() {
    const d = await api(`/api/snapshots/${state.snapshotId}/competitions/${Number(state.routeData.id)}`), c = d.competition;
    const formatType = d.format?.type || "knockout";
    const mode = state.routeData.tab || state.competitionTab || "results";
    state.competitionTab = mode;
    const tableTitle = formatType === "hybrid" ? "Reconstructed league phase" : "Reconstructed table";
    const tableNote = formatType === "hybrid"
        ? "Calculated only from matchdays identified as the league phase"
        : "Calculated from completed fixtures available in the snapshot";
    const groupView = competitionGroups(d.fixtureGroups, mode, formatType);
    content.innerHTML = `<div class="content-inner wide">${pageHead(c.competition_name, `Competition ID ${num(c.competition_object_id)} · Snapshot ${dateText(d.snapshot.career_date)}`, `<button class="button" data-route="competitions">All competitions</button>`)}
      <section class="card competition-identity-hero" ${identityStyle(d.identity)}>
        <div>${identityLogo(d.identity, c.competition_name, "competition-hero-logo")}</div>
        <div><p>COMPETITION</p><h2>${esc(c.competition_name)}</h2><div class="profile-badges"><span class="chip">Object ID ${num(c.competition_object_id)}</span>${d.identity?.mediaCompetitionId ? `<span class="chip">Media ID ${num(d.identity.mediaCompetitionId)}</span>` : ""}${statusBadge(d.format?.label || "Unknown format", formatType === "league" ? "good" : formatType === "hybrid" ? "amber" : "")}</div></div>
        ${trophyImage(d.identity, c.competition_name, "competition-trophy")}
      </section>
      <div class="grid metrics">
        ${metric("Format", esc(d.format?.label || "Unknown"), `${esc(d.format?.source || "no source")} · ${num((d.format?.confidence || 0) * 100)} %`)}
        ${metric("Participants", num(d.summary.participant_count), "identified from fixtures")}
        ${metric("Matches", num(d.summary.fixture_count), `${num(d.summary.group_count)} matchdays / rounds`)}
        ${metric("Completed", num(d.summary.completed), "available results", "green")}
        ${metric("Open", num(d.summary.upcoming), "upcoming fixtures", "blue")}
      </div>
      <div class="grid split-65">
        <div class="grid">
          ${d.format?.hasTable ? `<section class="card"><header class="card-header"><div><h2>${tableTitle}</h2><p>${tableNote}</p></div></header>${table([
        { label: "#", cls: "center" }, { label: "Club" }, { label: "P", cls: "num" }, { label: "W", cls: "num" },
        { label: "D", cls: "num" }, { label: "L", cls: "num" }, { label: "Goals", cls: "num" }, { label: "GD", cls: "num" }, { label: "Pts", cls: "num" }
    ], d.standings.map((r) => `<tr>
            <td class="center"><b>${num(r.position)}</b></td>
            <td><span class="inline-identity">${identityLogo(r.identity, r.team_name, "table-club-logo")}${clubLink(r.team_id, r.team_name)}</span></td>
            <td class="num">${num(r.played)}</td><td class="num">${num(r.won)}</td><td class="num">${num(r.drawn)}</td><td class="num">${num(r.lost)}</td>
            <td class="num">${num(r.goals_for)}:${num(r.goals_against)}</td><td class="num">${r.goal_difference > 0 ? "+" : ""}${num(r.goal_difference)}</td><td class="num"><b>${num(r.points)}</b></td>
          </tr>`))}</section>` : ""}
          <section class="card"><header class="card-header"><div><h2>${mode === "results" ? "Results" : "Schedule"}</h2><p>Grouped by ${formatType === "league" ? "matchdays" : formatType === "hybrid" ? "phases and matchdays" : "rounds"}</p></div>
            <div class="segmented"><button data-competition-tab="results" class="${mode === "results" ? "active" : ""}">Results</button><button data-competition-tab="schedule" class="${mode === "schedule" ? "active" : ""}">Schedule</button></div>
          </header>${groupView.html}</section>
        </div>
        <aside class="grid">
          <section class="card"><header class="card-header"><h2>Top scorers</h2></header><div class="card-body list">${leaderList(d.topScorers, "Goals", (p) => num(p.goals))}</div></section>
          <section class="card"><header class="card-header"><h2>Top assists</h2></header><div class="card-body list">${leaderList(d.topAssists, "Assists", (p) => num(p.assists))}</div></section>
          <section class="card"><header class="card-header"><div><h2>Top ratings</h2><p>At least ${num(d.ratingMinimumAppearances)} appearances</p></div></header><div class="card-body list">${leaderList(d.topRatings, "Avg rating", (p) => ratingValue(p.average_rating, true))}</div></section>
          <section class="card"><header class="card-header"><h2>Participants</h2></header><div class="card-body list compact-list">${d.participants.slice(0, 30).map((t) => `<div class="list-row">${identityLogo(t.identity, t.team_name, "list-club-logo")}<div class="list-main">${clubLink(t.team_id, t.team_name)}<small>EA Team ID ${num(t.team_id)}</small></div></div>`).join("")}</div></section>
          ${d.progress.length ? `<section class="card pad"><h3 class="card-title">Competition progress</h3><div class="list">${d.progress.map((p) => `<div class="list-row"><div class="list-main">${clubLink(p.team_ea_id, p.team_name || p.raw?.team_name)}<small>Stage ${num(p.stage_id)} · Season ${num(p.season)}</small></div>${statusBadge(p.has_team_won ? "Winner" : "Active")}</div>`).join("")}</div></section>` : ""}
        </aside>
      </div>
    </div>`;
    bindCompetitionGroups(groupView);
}
async function renderContracts() {
    const d = await api(`/api/snapshots/${state.snapshotId}/contracts`);
    const structure = d.wageStructure || { distribution: [], byPosition: [], topEarners: [], risks: [] };
    const distribution = (structure.distribution || []).map((row) => ({ ...row, season_label: row.label }));
    content.innerHTML = `<div class="content-inner wide">${pageHead("Contracts & wage structure", `Snapshot ${dateText(d.snapshot.career_date)} · imported FC26 contracts only`)}
      <div class="grid metrics">${metric("Contracts", num(d.summary.count), `${num(d.summary.missing_count)} without a wage value`)}${metric("Weekly payroll", money(d.summary.weekly_wage), "managed club export scope", "green")}${metric("Annual payroll", money(d.summary.annual_wage), "52 weeks", "blue")}${metric("Average", money(d.summary.average_wage), `Median ${money(d.summary.median_wage)}`)}${metric("Highest wage", money(d.summary.highest_wage), `lowest ${money(d.summary.lowest_wage)}`, "amber")}${metric("Top-five share", `${num(d.summary.top_five_share, 1)} %`, "share of total payroll")}</div>
      <div class="data-note">${esc(structure.sourceLabel || "Imported wages from contracts.csv only")}. Estimated wages for other clubs are never mixed into this table.</div>
      <div class="grid two-col analysis-grid"><section class="card pad"><div class="card-title-row"><h3 class="card-title">Wage distribution</h3><span>players per band</span></div>${simpleBarChart(distribution, [{ key: "count", label: "Players" }])}</section><section class="card"><header class="card-header"><h2>Payroll by position group</h2></header>${table([{ label: "Group" }, { label: "Players", cls: "num" }, { label: "Known", cls: "num" }, { label: "Total", cls: "num" }, { label: "Average", cls: "num" }, { label: "Share", cls: "num" }], (structure.byPosition || []).map((row) => `<tr><td><strong>${esc(row.group)}</strong></td><td class="num">${num(row.count)}</td><td class="num">${num(row.known_count)}</td><td class="num">${money(row.weekly_wage)}</td><td class="num">${row.average_wage == null ? "–" : money(row.average_wage)}</td><td class="num">${num(row.share, 1)} %</td></tr>`))}</section></div>
      <div class="grid split-65"><section class="card"><header class="card-header"><h2>Top earners</h2><span>read-only imported contract data</span></header>${table([{ label: "Player" }, { label: "Pos.", cls: "center" }, { label: "Age", cls: "num" }, { label: "OVR", cls: "center" }, { label: "Est. market value", cls: "num" }, { label: "Apps", cls: "num" }, { label: "Wage", cls: "num" }, { label: "Share", cls: "num" }], (structure.topEarners || []).map((c) => `<tr><td>${playerLink(c.player_ea_id, c.display_name)}</td><td class="center">${positionBadge(c.primary_position)}</td><td class="num">${c.age == null ? "–" : num(c.age)}</td><td class="center">${overallBadge(c.overall)}</td><td class="num" title="Project Atlas Tracker estimate">${money(c.market_value)}</td><td class="num">${num(c.appearances)}</td><td class="num"><b>${money(c.wage)}</b></td><td class="num">${d.summary.weekly_wage ? `${num(Number(c.wage || 0) / Number(d.summary.weekly_wage) * 100, 1)} %` : "–"}</td></tr>`))}</section><aside class="grid"><section class="card pad"><h3 class="card-title">Contract watchlist</h3><div class="list">${(structure.risks || []).map((r) => `<div class="list-row"><div class="list-main">${playerLink(r.player_ea_id, r.display_name)}<small>${esc((r.reasons || []).join(" · "))}</small></div><div class="list-value"><strong>${money(r.wage)}</strong><small>${r.duration_months == null ? "Term unknown" : `${num(r.duration_months)} months`}</small></div></div>`).join("") || '<span class="muted">No short-term/high-wage combination detected.</span>'}</div></section></aside></div>
      <section class="card"><header class="card-header"><h2>All contracts</h2><span>snapshot values</span></header>${table([
        { label: "Player" }, { label: "Age", cls: "center" }, { label: "Pos.", cls: "center" }, { label: "OVR", cls: "center" }, { label: "Role" },
        { label: "Wage", cls: "num" }, { label: "Term", cls: "num" }, { label: "Valid until", cls: "center" }, { label: "Signing bonus", cls: "num" }
    ], d.contracts.map((c) => `<tr>
        <td><div class="player-line">${playerPortrait(c.media, c.display_name || c.raw?.display_name, "table-portrait")}<div class="player-line-copy">${playerLink(c.player_ea_id, c.display_name || c.raw?.display_name)}<small>#${num(c.jersey_number)}</small></div></div></td>
        <td class="center" data-sort="${c.age ?? 999}">${c.age == null ? "–" : num(c.age)}</td><td class="center" data-sort="${positionOrder(c.primary_position, c.primary_position_id)}">${positionBadge(c.primary_position)}</td><td class="center">${overallBadge(c.overall)}</td>
        <td>${esc(c.player_role_label || "Not available")}<small class="raw-hint">Raw value ${c.player_role_raw ?? "–"}</small></td><td class="num"><b>${c.wage == null ? "–" : money(c.wage)}</b></td><td class="num">${c.duration_months == null ? "–" : `${num(c.duration_months)} months`}</td><td class="center">${esc(c.contract_valid_until || "–")}</td><td class="num">${c.raw?.signon_bonus ? money(c.raw.signon_bonus) : "–"}</td>
      </tr>`))}</section>
    </div>`;
}
function seasonPicker(options, selected, attr) {
    return `<label class="page-filter"><span>Season</span><select ${attr}>${options.map((option) => `<option value="${option.season_index}" ${Number(option.season_index) === Number(selected) ? "selected" : ""}>${esc(option.label)}${option.is_current ? " · current" : ""}</option>`).join("")}</select></label>`;
}
function movementSourceBadge(item) {
    const rawLabel = item.source_label || (item.source === "manual" ? "Manual" : item.source === "snapshot" ? "Imported" : "Derived");
    const translations = {
        "Abgeleitet": "Derived", "Beobachtet": "Observed", "Abgeleitet + beobachtet": "Derived + observed",
        "Importiert": "Imported", "Nachgetragen": "Manually added", "Vollzogen": "Completed"
    };
    const label = translations[String(rawLabel)] || String(rawLabel);
    const tone = item.source === "manual" ? "good" : String(item.source || "").includes("presigned") ? "blue" : "";
    return statusBadge(label, tone);
}
function movementManualEditor(kind, d, data, existing) {
    const incoming = existing ? String(existing.direction_raw || existing.direction || "incoming").toLowerCase().includes("incoming") || ["incoming", "arrival", "loan in"].includes(String(existing.direction || "").toLowerCase()) : true;
    const counterpartyName = existing ? (incoming ? existing.from_team_name : existing.to_team_name) : "";
    const counterpartyId = existing ? (incoming ? existing.from_team_ea_id : existing.to_team_ea_id) : null;
    const prefs = manualPreferences();
    const preferredDirection = existing ? (incoming ? "incoming" : "outgoing") : (prefs.direction || "incoming");
    const preferredCounterparty = counterpartyName || prefs.counterpartyTeamName || "";
    const feeUnknown = existing ? existing.fee == null : Boolean(prefs.feeUnknown);
    const title = existing ? (kind === "loan" ? "Edit historical loan" : "Edit historical transfer") : (kind === "loan" ? "Add historical loan" : "Add historical transfer");
    return `<section class="card pad movement-manual-editor"><div class="card-title-row"><h3 class="card-title">${title}</h3>${statusBadge("Manual", "good")}</div>
      <form id="movementManualForm" class="manual-form">
        <input type="hidden" name="id" value="${existing?.manual_id || ""}"><input type="hidden" name="transactionType" value="${kind}"><input type="hidden" name="seasonIndex" value="${rawNumber(d.seasonIndex)}">
        <div class="manual-form-grid">
          <label><span>Direction</span><select name="direction"><option value="incoming" ${preferredDirection === "incoming" ? "selected" : ""}>${kind === "loan" ? "Loan in" : "Arrival"}</option><option value="outgoing" ${preferredDirection === "outgoing" ? "selected" : ""}>${kind === "loan" ? "Loan out" : "Outgoing"}</option></select></label>
          <label><span>Season</span><input value="${esc(d.seasonLabel || String(Number(d.seasonIndex) + 1))}" disabled></label>
          ${manualPlayerPicker(existing?.display_name || "", existing?.player_ea_id)}
          <label><span>Other club</span><input name="counterpartyTeamName" list="manualTeamNames" required value="${esc(preferredCounterparty)}" placeholder="selling / buying club"></label>
          <label><span>Other club EA ID</span><input name="counterpartyTeamEaId" type="number" min="1" value="${counterpartyId ?? ""}" placeholder="optional"></label>
          ${kind === "transfer" ? `<label><span>Fee</span><input name="fee" type="number" min="0" step="1" value="${existing?.fee ?? ""}" placeholder="in euros"></label><label class="manual-check"><span>Fee known?</span><span><input name="feeUnknown" type="checkbox" ${feeUnknown ? "checked" : ""}> Unknown</span></label>` : ""}
          <label><span>${kind === "loan" ? "Loan start" : "Date"}</span><input name="transactionDate" type="date" value="${esc(existing?.date || "")}"></label>
          ${kind === "loan" ? `<label><span>Loan end</span><input name="loanEndDate" type="date" value="${esc(existing?.loan_end_date || "")}"></label>` : ""}
          <label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="2000">${esc(existing?.notes || "")}</textarea></label>
        </div><div class="manual-form-actions"><small>Ctrl+Enter saves</small><button type="button" class="button" data-movement-editor-cancel>Cancel</button><button type="submit" class="button primary">Save</button></div>
      </form>${manualDataLists(data)}</section>`;
}
async function renderLoans() {
    const fallbackSeason = Number(currentSnapshot()?.season_index ?? 0);
    const selected = state.movementSeasonIndex ?? fallbackSeason;
    const d = await api(`/api/snapshots/${state.snapshotId}/loans?season_index=${selected}`);
    state.movementSeasonIndex = Number(d.seasonIndex);
    const scope = state.loanScope || "club";
    const editorOpen = state.movementEditKind === "loan";
    const manualData = editorOpen ? await api(`/api/careers/${state.careerId}/manual-data`) : null;
    const editing = editorOpen && state.movementEditId ? d.all.find((item) => Number(item.manual_id) === Number(state.movementEditId)) : undefined;
    const actions = (item) => item.source === "manual" ? `<div class="movement-manual-actions"><button class="entity-link" data-movement-editor-edit="loan" data-id="${rawNumber(item.manual_id)}">Edit</button><button class="entity-link danger-link" data-movement-editor-delete="loan" data-id="${rawNumber(item.manual_id)}">Delete</button></div>` : "";
    const loanCard = (l, direction) => `<article class="movement-card">
      <div class="movement-player">${playerPortrait(l.media, l.display_name || l.raw?.display_name, "movement-portrait")}<div>${l.player_ea_id ? playerLink(l.player_ea_id, l.display_name || l.raw?.display_name) : `<strong>${esc(l.display_name || "Unknown player")}</strong>`}<small>${l.primary_position ? positionBadge(l.primary_position) : ""} ${l.overall ? overallBadge(l.overall) : ""}</small></div></div>
      <div class="movement-route"><div>${identityLogo(l.parentIdentity, l.parent_team_name, "movement-logo")}${l.parent_team_ea_id ? clubLink(l.parent_team_ea_id, l.parent_team_name || l.raw?.parent_team_name) : esc(l.parent_team_name || "–")}</div><span class="movement-arrow">→</span><div>${identityLogo(l.loanIdentity, l.loan_team_name, "movement-logo")}${l.loan_team_ea_id ? clubLink(l.loan_team_ea_id, l.loan_team_name || l.raw?.loan_team_name) : esc(l.loan_team_name || "–")}</div></div>
      <footer><span>${direction || "Loan"}</span><strong>${l.loan_end_date ? `until ${dateText(l.loan_end_date)}` : l.date ? `from ${dateText(l.date)}` : "Unknown period"}</strong>${l.is_loan_to_buy ? statusBadge("Purchase option", "amber") : ""}${movementSourceBadge(l)}</footer>${actions(l)}
    </article>`;
    const ownBody = `<div class="grid two-col"><section class="card"><header class="card-header"><h2>Loans in</h2></header><div class="card-body movement-list">${d.incoming.length ? d.incoming.map((l) => loanCard(l, "Loan in")).join("") : '<span class="muted">No loans in this season.</span>'}</div></section><section class="card"><header class="card-header"><h2>Loans out</h2></header><div class="card-body movement-list">${d.outgoing.length ? d.outgoing.map((l) => loanCard(l, "Loan out")).join("") : '<span class="muted">No loans out this season.</span>'}</div></section></div>`;
    const allBody = `<section class="card">${table([{ label: "Player" }, { label: "Parent club" }, { label: "Loan club" }, { label: "Start" }, { label: "End" }, { label: "Source" }, { label: "Actions", sortable: false }], d.all.map((l) => `<tr><td>${l.player_ea_id ? playerLink(l.player_ea_id, l.display_name) : `<strong>${esc(l.display_name)}</strong>`}</td><td>${l.parent_team_ea_id ? clubLink(l.parent_team_ea_id, l.parent_team_name) : esc(l.parent_team_name || "–")}</td><td>${l.loan_team_ea_id ? clubLink(l.loan_team_ea_id, l.loan_team_name) : esc(l.loan_team_name || "–")}</td><td>${l.date ? dateText(l.date) : "–"}</td><td>${l.loan_end_date ? dateText(l.loan_end_date) : "–"}</td><td>${movementSourceBadge(l)}</td><td>${actions(l)}</td></tr>`))}</section>`;
    content.innerHTML = `<div class="content-inner wide">${pageHead("Loans", `Loan activity for season ${esc(d.seasonLabel || String(Number(d.seasonIndex) + 1))}`, `<button class="button primary" data-movement-editor-open="loan">Add historical loan</button><button class="button" data-route="transfers">Transfers</button>`)}
      <div class="page-filter-bar">${seasonPicker(d.seasonOptions, d.seasonIndex, "data-movement-season")}</div>${editorOpen && manualData ? movementManualEditor("loan", d, manualData, editing) : ""}
      <div class="grid metrics">${metric("Loans in", num(d.summary.incoming), "players at your club", "green")}${metric("Loans out", num(d.summary.outgoing), "players at other clubs", "blue")}${metric("Imported", num(d.summary.imported), "snapshot observations")}${metric("Manual", num(d.summary.manual), "added manually", "amber")}</div>
      <div class="segmented page-tabs"><button data-loan-scope="club" class="${scope === "club" ? "active" : ""}">Your club</button><button data-loan-scope="all" class="${scope === "all" ? "active" : ""}">All loans</button></div>${scope === "club" ? ownBody : allBody}
    </div>`;
    if (editorOpen)
        bindMovementManualEditor();
}
function transferMoneyFull(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount))
        return "–";
    return new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(amount);
}
function transferCalendarDisplay(value) {
    const text = String(value || "");
    const match = text.match(/^(\d{2})-(\d{2})$/);
    return match ? `${match[2]}/${match[1]}` : text;
}
function transferClub(teamId, name, identity) {
    const label = name || (teamId ? `Team ${teamId}` : "–");
    return `<span class="inline-identity transfer-club">${identity ? identityLogo(identity, label, "table-club-logo") : ""}${teamId ? clubLink(teamId, label) : esc(label)}</span>`;
}
function transferPlayerCell(item) {
    const player = item.player || item;
    const id = player.playerEaId ?? item.player_ea_id, name = player.displayName ?? item.display_name ?? `Player ${id}`;
    return `<div class="player-line transfer-player-line">${playerPortrait(player.media ?? item.media, name, "table-portrait")}<div class="player-line-copy">${id ? playerLink(id, name) : esc(name)}${player.age == null ? "" : `<small>${num(player.age)} years${player.position ? ` · ${esc(player.position)}` : ""}</small>`}</div></div>`;
}
async function renderLegacyTransfers() {
    const fallbackSeason = Number(currentSnapshot()?.season_index ?? 0), selected = state.movementSeasonIndex ?? fallbackSeason;
    const d = await api(`/api/snapshots/${state.snapshotId}/transfers?season_index=${selected}`);
    state.movementSeasonIndex = Number(d.seasonIndex);
    const incoming = (d.own || []).filter((t) => t.direction === "Incoming"), outgoing = (d.own || []).filter((t) => t.direction === "Outgoing");
    const editorOpen = state.movementEditKind === "transfer";
    const manualData = editorOpen ? await api(`/api/careers/${state.careerId}/manual-data`) : null;
    const editing = editorOpen && state.movementEditId ? (d.own || []).find((item) => Number(item.manual_id) === Number(state.movementEditId)) : undefined;
    const actions = (t) => t.source === "manual" ? `<div class="movement-manual-actions"><button class="entity-link" data-movement-editor-edit="transfer" data-id="${rawNumber(t.manual_id)}">Edit</button><button class="entity-link danger-link" data-movement-editor-delete="transfer" data-id="${rawNumber(t.manual_id)}">Delete</button></div>` : "";
    const feeSum = (rows) => rows.reduce((sum, t) => sum + (t.fee == null ? 0 : Number(t.fee) || 0), 0);
    const incomingFees = feeSum(incoming), outgoingFees = feeSum(outgoing), balance = outgoingFees - incomingFees;
    const unknownIncoming = incoming.filter((t) => t.fee == null).length, unknownOutgoing = outgoing.filter((t) => t.fee == null).length;
    const rows = (items) => items.map((t) => `<tr><td>${transferPlayerCell(t)}</td><td>${transferClub(t.from_team_ea_id, t.from_team_name, t.fromIdentity)}</td><td class="center transfer-arrow" aria-label="moves to">→</td><td>${transferClub(t.to_team_ea_id, t.to_team_name, t.toIdentity)}</td><td>${t.date ? dateText(t.date) : "–"}</td><td class="num" data-sort="${t.fee == null ? -1 : Number(t.fee) || 0}"><strong class="transfer-fee" title="${esc(t.source_label || "Historical fee")}">${t.fee == null ? "unknown" : transferMoneyFull(t.fee)}</strong></td><td>${movementSourceBadge(t)}${actions(t)}</td></tr>`);
    const movementTable = (title, items, empty) => `<section class="card transfer-history-section"><header class="card-header"><div><h2>${title}</h2><span>${num(items.length)} movements</span></div></header>${items.length ? table([{ label: "Player" }, { label: "From" }, { label: "", cls: "center" }, { label: "To" }, { label: "Date" }, { label: "Fee", cls: "num" }, { label: "Source" }], rows(items)) : `<div class="card-body muted">${empty}</div>`}</section>`;
    const editor = editorOpen && manualData ? movementManualEditor("transfer", d, manualData, editing) : "";
    const output = `<div class="page-filter-bar">${seasonPicker(d.seasonOptions, d.seasonIndex, "data-movement-season")}<button class="button primary" data-movement-editor-open="transfer">Add historical transfer</button></div>${editor}<div class="grid metrics transfer-history-metrics">${metric("Arrivals", transferMoneyFull(incomingFees), `${num(incoming.length)} players${unknownIncoming ? ` · ${num(unknownIncoming)} fees unknown` : ""}`, "blue")}${metric("Departures", transferMoneyFull(outgoingFees), `${num(outgoing.length)} players${unknownOutgoing ? ` · ${num(unknownOutgoing)} fees unknown` : ""}`, "green")}${metric("Transfer balance", `${balance >= 0 ? "+" : "−"}${transferMoneyFull(Math.abs(balance))}`, "Departures minus Arrivals", balance >= 0 ? "green" : "amber")}</div><div class="grid transfer-history-split">${movementTable("Arrivals", incoming, "No arrivals this season.")}${movementTable("Departures", outgoing, "No departures this season.")}</div><div class="data-note">Totals include all known fees. Movements without a recorded fee remain in the player count but not in the monetary total.</div>`;
    if (editorOpen)
        setTimeout(() => bindMovementManualEditor(), 0);
    return output;
}
async function renderTransfers() {
    const history = await renderLegacyTransfers();
    content.innerHTML = `<div class="content-inner wide">${pageHead("Transfer history", "Observed and manually recorded career movements", `<button class="button" data-route="loans">Loan history</button>`)}${history}</div>`;
}
async function renderYouth() {
    const d = await api(`/api/snapshots/${state.snapshotId}/youth`);
    const rows = d.players || [];
    content.innerHTML = `<div class="content-inner wide">${pageHead("FC26 youth players", `Snapshot ${dateText(d.snapshot.career_date)} · imported records only`)}
      <div class="data-note"><b>Read-only:</b> this page contains only youth players confirmed by the FC26 snapshot exporter. Project Atlas Tracker does not generate, reveal, edit or inject youth players.</div>
      <div class="grid metrics">${metric("Players", num(d.summary.count), "confirmed in the selected snapshot")}${metric("Average OVR", d.summary.average_overall == null ? "–" : num(d.summary.average_overall, 1), "current ability", "green")}${metric("Average POT", d.summary.average_potential == null ? "–" : num(d.summary.average_potential, 1), "FC26 potential", "blue")}${metric("85+ POT", num(d.summary.elite), "high-potential players", "amber")}</div>
      <section class="card">${rows.length ? table([{ label: "Player" }, { label: "Age", cls: "center" }, { label: "Pos.", cls: "center" }, { label: "OVR", cls: "center" }, { label: "POT", cls: "center" }, { label: "Est. market value", cls: "num" }, { label: "Est. wage", cls: "num" }], rows.map((p) => `<tr><td><div class="player-line">${playerPortrait(p.media, p.display_name, "table-portrait")}<div class="player-line-copy">${p.player_ea_id ? playerLink(p.player_ea_id, p.display_name) : esc(p.display_name || "Unknown player")}<small>FC26 youth export</small></div></div></td><td class="center">${p.age == null ? "–" : num(p.age)}</td><td class="center">${positionBadge(p.primary_position)}</td><td class="center">${overallBadge(p.overall)}</td><td class="center">${overallBadge(p.potential)}</td><td class="num" title="Project Atlas Tracker estimate">${money(p.market_value)}</td><td class="num" title="Project Atlas Tracker estimate">${money(p.weekly_wage)}</td></tr>`)) : '<div class="card-body muted">No FC26-confirmed youth players were found in this snapshot.</div>'}</section>
    </div>`;
}
function playerSeasonStatsTable(rows) {
    if (!rows.length)
        return `<div class="card-body muted">No season statistics available yet.</div>`;
    const groups = new Map();
    for (const row of rows) {
        const key = String(row.start_year ?? row.season_label ?? row.season_index ?? "unknown");
        if (!groups.has(key))
            groups.set(key, []);
        groups.get(key).push(row);
    }
    const body = [];
    [...groups.values()].sort((a, b) => Number(a[0].start_year ?? 9999) - Number(b[0].start_year ?? 9999)).forEach(seasonRows => {
        seasonRows.sort((a, b) => String(a.competition_name || "").localeCompare(String(b.competition_name || ""), "en"));
        const first = seasonRows[0];
        const yearLabel = first.season_label || (first.start_year && first.end_year ? `${first.start_year}/${String(first.end_year).slice(-2)}` : "Season unknown");
        seasonRows.forEach((row, index) => {
            const competition = row.competition_object_id ? competitionLink(row.competition_object_id, row.competition_name) : esc(row.competition_name || "–");
            const sourceBadge = row.source === "manual" ? statusBadge("Manual", "good") : row.source === "atlas_simulation" ? statusBadge("Atlas simulation", "blue") : statusBadge("Imported");
            const shotsFaced = Number(row.saves || 0) + Number(row.goals_conceded || 0), savePct = shotsFaced > 0 ? `${num(Number(row.saves || 0) / shotsFaced * 100, 1)} %` : "–";
            body.push(`<tr>${index === 0 ? `<td class="season-stat-season" rowspan="${seasonRows.length}"><strong>${esc(yearLabel)}</strong><small>${row.career_season_number ? `${num(row.career_season_number)}. Career season` : ""}</small></td>` : ""}<td>${competition}</td><td>${sourceBadge}</td><td>${row.represented_team_ea_id ? clubLink(row.represented_team_ea_id, row.represented_team_name) : esc(row.represented_team_name || "–")}</td><td class="num">${num(row.appearances)}</td><td class="num"><b>${num(row.goals)}</b></td><td class="num">${num(row.assists)}</td><td class="num">${num(row.man_of_the_match)}</td><td class="num">${num(row.clean_sheets)}</td><td class="num">${ratingValue(row.average_rating, true)}</td><td class="num">${row.saves == null ? "–" : num(row.saves)}</td><td class="num">${row.goals_conceded == null ? "–" : num(row.goals_conceded)}</td><td class="num">${savePct}</td><td class="num">${row.yellow_cards == null ? "–" : num(row.yellow_cards)}</td><td class="num">${row.second_yellow_cards == null ? "–" : num(row.second_yellow_cards)}</td><td class="num">${row.red_cards == null ? "–" : num(row.red_cards)}</td></tr>`);
        });
    });
    return `<div class="table-wrap"><table class="data-table season-stat-table"><thead><tr><th>Season</th><th>Competition</th><th>Source</th><th>Team</th><th class="num">Apps</th><th class="num">G</th><th class="num">A</th><th class="num">MOTM</th><th class="num">CS</th><th class="num">Avg. rating</th><th class="num">Saves</th><th class="num">GC</th><th class="num">Save %</th><th class="num">YC</th><th class="num">2YC</th><th class="num">RC</th></tr></thead><tbody>${body.join("")}</tbody></table></div>`;
}
function playerCareerPathView(path) {
    const stations = path?.stations || [], movements = path?.movements || [];
    const stationCards = stations.length ? `<div class="player-club-timeline">${stations.map((station, index) => `<article class="player-club-station"><div class="player-club-station-index">${index + 1}</div><div class="player-club-station-main">${station.identity ? identityLogo(station.identity, station.team_name, "career-club-logo") : `<span class="career-club-fallback">${esc(initials(station.team_name || "?"))}</span>`}<div><span>${esc(station.season_label || "Season unknown")}${station.career_season_number ? ` · ${num(station.career_season_number)}. Career season` : ""}</span><strong>${station.team_ea_id ? clubLink(station.team_ea_id, station.team_name) : esc(station.team_name || "Unknown club")}</strong><small>${station.first_date ? `${dateText(station.first_date)}${station.last_date && station.last_date !== station.first_date ? ` to ${dateText(station.last_date)}` : ""}` : "Observed season context"}</small></div></div><div class="player-club-station-values"><span>OVR <b>${num(station.overall)}</b></span><span>POT <b>${num(station.potential)}</b></span><span title="${esc(station.market_value_hint || "Estimated market value")}">Market value <b>${money(station.market_value)}</b></span></div></article>`).join("")}</div>` : '<div class="muted">No observed club history yet.</div>';
    const movementTable = movements.length ? table([
        { label: "Season / date" }, { label: "Movement" }, { label: "From" }, { label: "To" }, { label: "Fee / Loan end", cls: "num" }, { label: "Market value", cls: "num" }, { label: "Source" }
    ], movements.map((event) => `<tr><td><strong>${esc(event.season_label || "–")}</strong><small class="table-subline">${dateText(event.date)}</small></td><td>${event.event_type === "loan" ? statusBadge("Loan", "blue") : statusBadge("Transfer", "good")}</td><td>${event.from_team_ea_id ? clubLink(event.from_team_ea_id, event.from_team_name) : esc(event.from_team_name || "–")}</td><td>${event.to_team_ea_id ? clubLink(event.to_team_ea_id, event.to_team_name) : esc(event.to_team_name || "–")}</td><td class="num">${event.event_type === "loan" ? (event.loan_end_date ? `until ${dateText(event.loan_end_date)}` : "Loan end unknown") : (event.fee == null ? "Fee unknown" : money(event.fee))}</td><td class="num">${event.market_value == null ? "–" : money(event.market_value)}${event.market_value_date ? `<small class="table-subline">As of ${dateText(event.market_value_date)}</small>` : ""}</td><td>${movementSourceBadge(event)}</td></tr>`)) : '<div class="card-body muted">No transfers or loans recorded for this player yet.</div>';
    return `<section class="card pad"><div class="card-title-row"><h3 class="card-title">Club history</h3><span>${num(stations.length)} clubs</span></div>${stationCards}</section><section class="card"><header class="card-header"><h2>Transfers and loans</h2><span>${num(movements.length)} movements</span></header>${movementTable}<div class="data-note">${(path?.notes || []).map((note) => esc(note)).join(" · ")}</div></section>`;
}
function detailedAggregateGroups(stats) {
    if (!stats || !Object.keys(stats).length)
        return '<span class="muted">No detailed FC26 statistics available.</span>';
    return `<div class="detailed-stat-groups season">${detailedStatGroups.map((g) => { const items = g.keys.filter((k) => stats[k] != null && (Number(stats[k]) !== 0 || k.includes("pct") || k.includes("expected"))); return items.length ? `<div class="detailed-stat-group"><h4>${esc(g.label)}</h4>${items.map((k) => `<div><span>${esc(detailedStatLabels[k] || k)}</span><strong>${detailedStatText(k, stats[k])}</strong></div>`).join("")}</div>` : ""; }).join("")}</div>`;
}
function playerDetailedSeasonView(detail) {
    if (!detail?.available)
        return `<section class="card pad"><h3 class="card-title">Detailed FC26 statistics</h3><div class="muted">No validated detailed match export is linked for the current season yet.</div></section>`;
    const s = detail.aggregate || {};
    const share = detail.teamShare || {};
    const coverage = detail.coveragePct == null ? `${num(detail.matchesCovered)} detailed matches` : `${num(detail.matchesCovered)} / ${num(detail.officialAppearances)} appearances · ${num(detail.coveragePct, 0)} %`;
    return `<section class="card"><header class="card-header"><div><h2>Detailed season statistics</h2><p>${coverage}</p></div>${statusBadge("FC26 Detail", "good")}</header><div class="card-body"><div class="grid metrics compact">${metric("Minutes", num(s.minutes_played), `${num(s.minutes_per_match, 1)} per match`)}${metric("Goals / assists", `${num(s.goals_derived)} / ${num(s.assists)}`, `${num(s.npk_expected_goals, 2)} NPK-xG · ${num(s.expected_assists, 2)} xA`, "green")}${metric("xG+xA /90", s.xg_plus_xa_per90 == null ? "–" : num(s.xg_plus_xa_per90, 2), `NPK finishing Δ ${Number(s.npk_finishing_delta) >= 0 ? "+" : ""}${num(s.npk_finishing_delta, 2)}`, "green")}${metric("Avg rating", s.average_game_rating == null ? "–" : num(s.average_game_rating, 2), `${num(s.man_of_the_match)}× MOTM`, "blue")}${metric("Shots /90", s.shots_per90 == null ? "–" : num(s.shots_per90, 2), `${num(s.shot_on_target_pct, 1)} % on target · xG/shot ${num(s.xg_per_shot, 3)}`)}${metric("Key passes /90", s.key_passes_per90 == null ? "–" : num(s.key_passes_per90, 2), `${num(share.key_passes, 1)} % of team key passes`)}${metric("Possession won /90", s.possession_won_per90 == null ? "–" : num(s.possession_won_per90, 2), `${num(share.possession_won, 1)} % team share`)}${metric("Duels", s.combined_duel_success_pct == null ? "–" : `${num(s.combined_duel_success_pct, 1)} %`, `possession balance ${Number(s.possession_balance) >= 0 ? "+" : ""}${num(s.possession_balance)}`)}</div>${detailedAggregateGroups(s)}${(detail.competitions || []).length ? `<details class="season-competition-details"><summary>Break down by competition</summary>${table([{ label: "Competition" }, { label: "Apps", cls: "num" }, { label: "Min.", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "NPK-xG", cls: "num" }, { label: "xA", cls: "num" }, { label: "Avg rating", cls: "num" }], detail.competitions.map((c) => { const x = c.stats || {}; return `<tr><td>${esc(c.competitionName)}</td><td class="num">${num(x.matches)}</td><td class="num">${num(x.minutes_played)}</td><td class="num">${num(x.goals_derived)}</td><td class="num">${num(x.assists)}</td><td class="num">${num(x.npk_expected_goals, 2)}</td><td class="num">${num(x.expected_assists, 2)}</td><td class="num">${x.average_game_rating == null ? "–" : num(x.average_game_rating, 2)}</td></tr>`; }))}</details>` : ""}</div><div class="data-note">xG is the direct non-penalty xG value from FC26. Tracker does not add penalty xG unless penalty attempts can be assigned reliably to the taker.</div></section>`;
}
function detailedSeasonHistoryView(history) {
    if (!history?.length)
        return "";
    return `<section class="card"><header class="card-header"><div><h2>Detailed season history</h2><p>All seasons with unambiguously linked FC26 match data</p></div></header>${table([{ label: "Season" }, { label: "Coverage", cls: "num" }, { label: "Min.", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "NPK-xG", cls: "num" }, { label: "xA", cls: "num" }, { label: "Avg rating", cls: "num" }, { label: "Shots", cls: "num" }, { label: "Key P.", cls: "num" }], history.map((row) => { const x = row.aggregate || {}; return `<tr><td><strong>Season ${num(Number(row.seasonIndex) + 1)}</strong></td><td class="num">${row.coveragePct == null ? num(row.matchesCovered) : `${num(row.matchesCovered)}/${num(row.officialAppearances)} · ${num(row.coveragePct, 0)}%`}</td><td class="num">${num(x.minutes_played)}</td><td class="num">${num(x.goals_derived)}</td><td class="num">${num(x.assists)}</td><td class="num">${num(x.npk_expected_goals, 2)}</td><td class="num">${num(x.expected_assists, 2)}</td><td class="num">${x.average_game_rating == null ? "–" : num(x.average_game_rating, 2)}</td><td class="num">${num(x.shots)}</td><td class="num">${num(x.key_passes)}</td></tr>`; }))}<div class="data-note">Season numbers follow the EA career-season index. Only matches with an unambiguous detailed import are aggregated.</div></section>`;
}
function detailedPlayerMatchesView(matches) {
    if (!matches?.length)
        return '<div class="card-body muted">No linked detailed FC26 matches in this season yet.</div>';
    return table([{ label: "Season" }, { label: "Date" }, { label: "Match" }, { label: "Competition" }, { label: "Min.", cls: "num" }, { label: "Rating", cls: "num" }, { label: "G/A", cls: "num" }, { label: "NPK-xG", cls: "num" }, { label: "xA", cls: "num" }, { label: "SoT/Sh", cls: "num" }, { label: "Pass %", cls: "num" }, { label: "Key P.", cls: "num" }, { label: "Duels", cls: "num" }], matches.map((m) => { const s = m.stats || {}; const attempts = Number(s.offense_duels_attempted || 0) + Number(s.defense_duels_attempted || 0) + Number(s.aerial_duels_attempted || 0), wins = Number(s.offense_duels_won || 0) + Number(s.defense_duels_won || 0) + Number(s.aerial_duels_won || 0); return `<tr><td>S${num(Number(m.seasonIndex) + 1)}</td><td>${dateText(m.date)}</td><td>${matchLink(m.fixtureId, `${m.homeTeamName || "?"} – ${m.awayTeamName || "?"}`)}<details class="inline-match-detail"><summary>All values</summary>${detailedAggregateGroups(s)}</details></td><td>${esc(m.competitionName || "–")}</td><td class="num">${num(s.minutes_played)}</td><td class="num"><b>${s.game_rating == null ? "–" : num(s.game_rating, 1)}</b></td><td class="num">${num(s.goals_derived)}/${num(s.assists)}</td><td class="num">${num(s.npk_expected_goals, 2)}</td><td class="num">${num(s.expected_assists, 2)}</td><td class="num">${num(s.shots_on_target)}/${num(s.shots)}</td><td class="num">${s.pass_accuracy_pct_derived == null ? "–" : num(s.pass_accuracy_pct_derived, 1)}</td><td class="num">${num(s.key_passes)}</td><td class="num">${attempts ? `${num(wins)}/${num(attempts)}` : "–"}</td></tr>`; }));
}
async function renderPlayer() {
    const d = await api(`/api/snapshots/${state.snapshotId}/players/${Number(state.routeData.id)}`), p = d.player || {}, r = d.roster || {}, raw = p.raw || {}, financial = d.financial || {}, atlasFinance = d.playerFinance || {}, market = atlasFinance.market || financial.market_value || {}, wageModel = atlasFinance.wage || {}, wage = { value: wageModel.display, label: wageModel.displayLabel, annual: wageModel.annualDisplay }, tabs = ["overview", "stats", "matches", "development", "analysis", "commission", "attributes", "career"];
    state.playerTab = state.routeData.tab || state.playerTab || "overview";
    if (!tabs.includes(state.playerTab))
        state.playerTab = "overview";
    const tabLabels = { overview: "Overview", stats: "Season statistics", matches: "Matches", development: "Development", analysis: "Analysis", commission: "Technical commission", attributes: "Attributes", career: "Contract & history" };
    let body = "";
    if (state.playerTab === "overview")
        body = `<div class="grid split-65"><div class="grid"><section class="card pad"><h3 class="card-title">Current status</h3><div class="grid three-col">${metric("Appearances", num(d.totals.appearances), "across competitions")}${metric("Goals", num(d.totals.goals), "season total", "green")}${metric("Assists", num(d.totals.assists), "season total", "blue")}</div></section><section class="card"><header class="card-header"><h2>Development</h2><button class="entity-link" data-player-tab="development">Details</button></header><div class="card-body">${lineChart(d.history)}</div></section></div><aside class="grid"><section class="card pad"><h3 class="card-title">Player data</h3><div class="list"><div class="list-row"><div class="list-main"><strong>Club</strong></div>${p.team_ea_id ? clubLink(p.team_ea_id, p.team_name) : "–"}</div><div class="list-row"><div class="list-main"><strong>Shirt number</strong></div><b>${r.jersey_number ? `#${num(r.jersey_number)}` : "–"}</b></div><div class="list-row"><div class="list-main"><strong>Age</strong></div><b>${p.age == null ? "–" : `${num(p.age)} years`}</b></div><div class="list-row"><div class="list-main"><strong>Date of birth</strong></div><b>${p.birth_date ? dateText(p.birth_date) : "–"}</b></div><div class="list-row"><div class="list-main"><strong>Height / weight</strong></div><b>${num(p.height)} cm · ${num(p.weight)} kg</b></div><div class="list-row"><div class="list-main"><strong>Nationality</strong></div>${d.nationality ? nationalityFlag(d.nationality, "nationality-flag-small") : "–"}</div><div class="list-row" title="${financialHint(financial, "market")}"><div class="list-main"><strong>Market value</strong></div><b>${money(market.value)}</b></div><div class="list-row" title="${esc(wage.label || "Tracker wage estimate")}"><div class="list-main"><strong>Wage</strong><small>${esc(wage.label || "per week")}</small></div><b>${money(wage.value)} / week<small class="table-subline">${money(wage.annual)} / year</small></b></div><div class="list-row"><div class="list-main"><strong>Foot</strong></div><b>${Number(p.preferred_foot_id) === 1 ? "Right" : Number(p.preferred_foot_id) === 2 ? "Left" : "–"}</b></div><div class="list-row"><div class="list-main"><strong>Contract until</strong></div><b>${esc(p.contract_valid_until || "–")}</b></div></div></section><section class="card pad"><h3 class="card-title">Status</h3><div class="profile-badges">${p.is_captain ? statusBadge("Captain", "blue") : ""}${d.youth ? statusBadge("Youth player", "good") : ""}${d.loan ? statusBadge("Active loan") : ""}${r.injury ? statusBadge("Injured", "bad") : statusBadge("Available", "good")}${wage.value != null ? statusBadge(`${money(wage.value)} / week`) : ""}</div></section></aside></div>`;
    else if (state.playerTab === "stats")
        body = `<div class="grid">${playerDetailedSeasonView(d.detailedSeasonStats)}${detailedSeasonHistoryView(d.detailedSeasonHistory || [])}<section class="card"><header class="card-header"><h2>Official season totals by competition</h2><span class="source-legend">${statusBadge("Imported")} ${statusBadge("Atlas simulation", "blue")} ${statusBadge("Manual", "good")}</span></header>${playerSeasonStatsTable(d.seasonStats || [])}<div class="data-note">Detailed FC26 match data augments the official cumulative season totals. Imported, simulated and manual data remains separate.</div></section>${playerManualEditor(d, p)}</div>`;
    else if (state.playerTab === "matches")
        body = `<div class="grid"><section class="card"><header class="card-header"><div><h2>Detailed matches</h2><p>Direct FC26 metrics for each linked match across the career</p></div>${d.detailedMatches?.length ? statusBadge("FC26 Detail", "good") : ""}</header>${detailedPlayerMatchesView(d.detailedMatches || [])}<div class="data-note">Goals, cards, xG/xA, passes, duels, defending and goalkeeper metrics come from the match exporter. Event minutes are not estimated.</div></section>${!d.detailedMatches?.length ? `<section class="card"><header class="card-header"><h2>Fallback: snapshot match data</h2></header>${d.performances.length ? table([{ label: "Date" }, { label: "Match" }, { label: "Competition" }, { label: "Pos.", cls: "center" }, { label: "Min.", cls: "num" }, { label: "Rating", cls: "num" }], d.performances.map((m) => `<tr><td>${dateText(m.date)}</td><td>${m.fixture_id ? matchLink(m.fixture_id, `${m.home_team_name || "?"} – ${m.away_team_name || "?"}`) : esc(m.fixture_key || "Not linked")}</td><td>${esc(m.competition_name || "–")}</td><td class="center">${positionBadge(m.actual_position)}</td><td class="num">${num(m.minutes_played)}</td><td class="num">${ratingValue(m.rating, false)}</td></tr>`)) : '<div class="card-body muted">No match data available.</div>'}</section>` : ""}</div>`;
    else if (state.playerTab === "development") {
        const development = d.developmentHistory || d.history || [];
        body = `<div class="grid"><section class="card"><header class="card-header"><h2>OVR and POT</h2><span>${statusBadge("Imported")} ${statusBadge("Manual", "good")}</span></header><div class="card-body">${lineChart(development, ["overall", "potential"], { decimals: 0, min: 1, max: 99, ariaLabel: "OVR and POT development" })}</div></section><section class="card"><header class="card-header"><h2>Market value development</h2><span>estimated</span></header><div class="card-body">${lineChart(development, ["market_value"], { format: "money", ariaLabel: "Estimated market value development" })}</div><div class="data-note">Manual market values use the entry's OVR/POT plus age, position and club from the nearest observed snapshot. Current-state modifiers and remaining contract duration are labelled as assumptions.</div></section><section class="card">${table([{ label: "Season / date" }, { label: "Point in time" }, { label: "Source" }, { label: "Club" }, { label: "OVR", cls: "center" }, { label: "Δ", cls: "num" }, { label: "POT", cls: "center" }, { label: "Market value", cls: "num" }, { label: "Wage", cls: "num" }], development.map((h, i) => `<tr><td><strong>${esc(h.season_label || "Season unknown")}</strong><small class="raw-hint">${dateText(h.effective_date || h.career_date)}${h.career_season_number ? ` · ${num(h.career_season_number)}. Career season` : ""}</small></td><td>${esc(h.stage_label || "Snapshot")}</td><td>${h.source === "manual" ? statusBadge("Manual", "good") : statusBadge("Imported")}</td><td>${h.team_ea_id ? clubLink(h.team_ea_id, h.team_name) : esc(h.team_name || "–")}</td><td class="center">${overallBadge(h.overall)}</td><td class="num">${i ? delta((Number(h.overall) || 0) - (Number(development[i - 1].overall) || 0)) : "–"}</td><td class="center">${overallBadge(h.potential)}</td><td class="num" title="${financialHint(h.financial, "market")}">${h.market_value == null ? "–" : money(h.market_value)}</td><td class="num">${h.source === "manual" ? "–" : money(h.wage)}</td></tr>`))}</section>${playerDevelopmentEditor(d, p)}</div>`;
    }
    else if (state.playerTab === "analysis") {
        const a = d.analysis || {}, performance = a.performance || {}, quality = a.dataQuality || {};
        const scope = state.playerComparisonScope || "club";
        const mode = state.playerComparisonMode || "group";
        const comparison = a.comparisons?.[scope]?.[mode] || a.comparison || {};
        const categoryComparisons = comparison.categoryComparisons || a.categoryComparisons || [];
        const roleRows = (a.roles || []).map((row)=>({label:row.label,score:row.score}));
        const rankText = (rank,total) => rank && total ? `#${num(rank)} of ${num(total)}` : "–";
        const comparisonTabs = `<div class="comparison-controls"><div class="page-tabs compact"><button class="${scope === "club" ? "active" : ""}" data-player-comparison-scope="club">At club</button><button class="${scope === "league" ? "active" : ""}" data-player-comparison-scope="league">League-wide</button></div><label class="comparison-mode"><span>Compare by</span><select data-player-comparison-mode><option value="group" ${mode === "group" ? "selected" : ""}>Position group</option><option value="position" ${mode === "position" ? "selected" : ""}>Exact position</option></select></label></div>`;

        const p1Scope = {snapshot_id:Number(state.snapshotId),mode:"player",player_ea_id:Number(p.ea_player_id)};
        const p1Cache = await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${p1Scope.snapshot_id}&mode=player&player_ea_id=${p1Scope.player_ea_id}`.trim()).catch(()=>({state:"error"}));
        const p1Saved = p1Cache.result || {};
        const p1Text = atlasLanguage()==="en-GB"
            ? {ai:"Technical commission",context:"AI interpretation · Atlas evidence",generate:"Generate analysis",refresh:"Refresh analysis",detail:"Complete report",metrics:"MatchStats / 90 min",coverage:"Available linked detailed matches",without:"No linked detailed FC26 matches in the selected season",contract:"Attribute percentiles by current club/league and registered position, not on-pitch output",peer:"Attribute comparison highlights",stale:"Outdated context · refresh the analysis",review:"Some AI findings require review",fallback:"Summary based on deterministic fallback",offline:"No saved local AI report; the existing Atlas analysis remains available",working:"The local analysis is being prepared"}
            : atlasLanguage()==="es-ES"
            ? {ai:"Comisión técnica",context:"Interpretación IA · evidencias del Atlas",generate:"Generar análisis",refresh:"Actualizar análisis",detail:"Informe completo",metrics:"MatchStats / 90 min",coverage:"Partidos detallados vinculados",without:"Sin partidos detallados vinculados en esta temporada",contract:"Percentiles de atributos por club/liga y posición registrada; no son rendimiento real",peer:"Diferencias de atributos",stale:"Contexto desactualizado · actualiza el análisis",review:"Algunas conclusiones requieren revisión",fallback:"Resumen basado en apoyo determinístico",offline:"Sin informe IA local guardado; el análisis del Atlas sigue disponible",working:"La evaluación local está en curso"}
            : {ai:"Comissão Técnica",context:"Interpretação da IA · evidências do Atlas",generate:"Gerar análise",refresh:"Atualizar análise",detail:"Relatório completo",metrics:"MatchStats / 90 min",coverage:"Partidas detalhadas vinculadas",without:"Sem partidas detalhadas vinculadas nesta temporada",contract:"Percentis de atributos no clube/na liga e por posição cadastrada; não medem rendimento em campo",peer:"Destaques dos atributos",stale:"Contexto desatualizado · atualize a análise",review:"Algumas conclusões exigem revisão",fallback:"Resumo baseado em fallback determinístico",offline:"Ainda sem relatório local de IA; a análise original do Atlas continua disponível",working:"A avaliação local está em processamento"};
        const p1Ready = p1Cache.state==="ready" || p1Cache.state==="stale";
        const p1Warnings = [p1Cache.state==="stale"?p1Text.stale:null,p1Saved.review_required?p1Text.review:null,p1Saved.report?.summary?.model_generated===false?p1Text.fallback:null].filter(Boolean);
        const p1Reading = p1Ready ? commissionReportMarkup(p1Saved,p1Scope) : `<div class="player-p1-empty">${esc(p1Cache.state==="running"||p1Cache.state==="queued"?p1Text.working:p1Text.offline)}</div>`;
        const p1AiCard = `<section class="card player-p1-ai"><header class="card-header"><div><h2>${esc(p1Text.ai)}</h2><p>${esc(p1Text.context)}</p></div><span class="status-badge ${p1Cache.state==="ready"?"good":"amber"}">${esc(p1Cache.state||"missing")}</span></header><div class="card-body">${p1Warnings.length?`<div class="player-p1-warnings">${p1Warnings.map(item=>`<p>${esc(item)}</p>`).join("")}</div>`:""}<div data-commission-report-output data-report-slot="player-p1-integrated" class="player-p1-report-output">${p1Reading}</div><div class="player-p1-actions"><button class="button primary" data-commission-report data-report-target="player-p1-integrated" data-mode="player" data-player-ea-id="${num(p.ea_player_id)}" data-snapshot-id="${num(state.snapshotId)}" data-force-refresh="${p1Cache.state==="ready"?"1":"0"}">${esc(p1Cache.state==="ready"?p1Text.refresh:p1Text.generate)}</button><button class="button" data-player-tab="commission">${esc(p1Text.detail)}</button></div></div></section>`;
        const p1DetailedStats = d.detailedSeasonStats?.available ? d.detailedSeasonStats.aggregate||{} : null;
        const p1DetailedFields = [{label:"xG+xA / 90",key:"xg_plus_xa_per90"},{label:"Passes-chave / 90",key:"key_passes_per90"},{label:"Recuperações / 90",key:"possession_won_per90"},{label:"Finalizações / 90",key:"shots_per90"}];
        const p1DetailStrip = `<section class="card pad player-p1-season"><div class="card-title-row"><div><h3 class="card-title">${esc(p1Text.metrics)}</h3><span class="chart-note">${p1DetailedStats?`${num(d.detailedSeasonStats.matchesCovered)} ${esc(p1Text.coverage)} · ${num(p1DetailedStats.minutes_played)} min`:esc(p1Text.without)}</span></div></div><div class="player-p1-season-grid">${p1DetailedFields.map(item=>`<div><span>${esc(item.label)}</span><strong>${p1DetailedStats?num(p1DetailedStats[item.key],2):"–"}</strong></div>`).join("")}</div></section>`;
        const p1Comparables = Array.isArray(categoryComparisons)?categoryComparisons:[];
        const p1Percentiles = p1Comparables.filter((item)=>item.percentile!=null && Number.isFinite(Number(item.percentile)) && Number(item.peer_count||0)>0).sort((a,b)=>Number(b.percentile)-Number(a.percentile));
        const p1PeerFirst = p1Percentiles[0];
        const p1PeerLast = p1Percentiles[p1Percentiles.length-1];
        const p1PeerHighlights = p1PeerFirst ? `<div class="player-p1-peer-insights"><strong>${esc(p1Text.peer)} · ${esc(comparison.scope_label||scope)} / ${esc(comparison.mode_label||mode)}</strong><div>${[p1PeerFirst,p1PeerLast].filter((item,index)=>index===0||item?.label!==p1PeerFirst.label).map(item=>`<span>${esc(item.label)} <b>${num(item.percentile)}%</b> <small>n=${num(item.peer_count)}</small></span>`).join("")}</div><small>${esc(p1Text.contract)}</small></div>`:"";

        body = `<div class="player-p1-layout"><section class="card pad player-analysis-radar"><div class="card-title-row"><h3 class="card-title">Attribute profile</h3><span>${esc(a.position_group_label || "Position group")}</span></div>${radarChart(a.categories || [])}</section>${p1AiCard}<section class="card pad player-p1-role"><div class="card-title-row"><h3 class="card-title">Role profile</h3><span>rule-based</span></div>${horizontalBars(roleRows,"score","label")}</section></div>${p1DetailStrip}
          <div class="grid two-col"><section class="card pad"><h3 class="card-title">Strengths</h3><div class="analysis-trait-list">${(a.strengths || []).map((row,index)=>`<div class="analysis-trait strength"><span>${index+1}</span><div><strong>${esc(row.label)}</strong><small>${num(row.value,1)} / 99</small></div></div>`).join("") || '<span class="muted">Not enough attributes.</span>'}</div></section><section class="card pad"><h3 class="card-title">Areas to develop</h3><div class="analysis-trait-list">${(a.developmentAreas || []).map((row,index)=>`<div class="analysis-trait development"><span>${index+1}</span><div><strong>${esc(row.label)}</strong><small>${num(row.value,1)} / 99</small></div></div>`).join("") || '<span class="muted">Not enough attributes.</span>'}</div></section></div>
          <section class="card pad player-comparison-card"><div class="card-title-row"><div><h3 class="card-title">Position comparison</h3><span>${esc(comparison.scope_label || (scope === "club" ? "At club" : "League-wide"))} · ${esc(comparison.mode_label || "Position group")}</span></div><b>${num(comparison.peer_count)} comparison players</b></div>${comparisonTabs}<div class="grid metrics">${metric("OVR rank", rankText(comparison.overall_rank,comparison.peer_count), `among ${num(comparison.peer_count)} comparison players`,"green")}${metric("POT rank", rankText(comparison.potential_rank,comparison.peer_count), `Avg. POT ${num(comparison.average_peer_potential,1)}`,"blue")}${metric("Physical profile", `${num(a.physical?.height)} cm · ${num(a.physical?.weight)} kg`, `Peer avg ${num(comparison.average_peer_height,1)} cm · ${num(comparison.average_peer_weight,1)} kg`)}${metric("Contributions per match", performance.contributions_per_game == null ? "–" : num(performance.contributions_per_game,2), `${num(performance.goals)} goals · ${num(performance.assists)} assists`,"amber")}</div><div class="percentile-list">${categoryComparisons.map((row)=>`<div class="percentile-row"><div><strong>${esc(row.label)}</strong><small>${row.percentile == null ? "Insufficient comparison data" : `better than ${num(row.percentile)} % · peer avg ${num(row.peer_average,1)} · best ${num(row.peer_best,1)}`}</small></div><div class="percentile-track"><i style="width:${Math.max(0,Math.min(100,Number(row.percentile)||0))}%"></i></div><b>${row.percentile == null ? "–" : `${num(row.percentile)} %`}</b></div>`).join("") || '<span class="muted">No suitable comparison values available.</span>'}</div></section>${p1PeerHighlights}
          <div class="grid two-col"><section class="card"><header class="card-header"><h2>Performance profile</h2><span>${num(performance.appearances)} Appearances</span></header>${table([{label:"Metric"},{label:"Value",cls:"num"}], [`<tr><td>Goals per match</td><td class="num">${performance.goals_per_game == null ? "–" : num(performance.goals_per_game,2)}</td></tr>`,`<tr><td>Assists per match</td><td class="num">${performance.assists_per_game == null ? "–" : num(performance.assists_per_game,2)}</td></tr>`,`<tr><td>Contributions per match</td><td class="num"><strong>${performance.contributions_per_game == null ? "–" : num(performance.contributions_per_game,2)}</strong></td></tr>`,`<tr><td>Average rating</td><td class="num">${ratingValue(performance.average_rating,true)}</td></tr>`,`<tr><td>Clean sheets</td><td class="num">${num(performance.clean_sheets)}</td></tr>`])}</section><section class="card pad"><h3 class="card-title">Context</h3><div class="list"><div class="list-row"><div class="list-main"><strong>Comparison scope</strong><small>${scope === "club" ? "current club" : "current league"}</small></div><b>${esc(comparison.scope_label || "–")}</b></div><div class="list-row"><div class="list-main"><strong>Position filter</strong></div><b>${esc(comparison.mode_label || "–")}</b></div><div class="list-row"><div class="list-main"><strong>Peer group avg OVR</strong></div><b>${num(comparison.average_peer_overall,1)}</b></div><div class="list-row"><div class="list-main"><strong>Attribute coverage</strong><small>${num(quality.available_attributes)} of ${num(quality.expected_attributes)} relevant values</small></div><b>${num(quality.coverage,1)} %</b></div></div></section></div>
          <div class="data-note">This analysis is rule-based and uses attributes, position, height, weight, comparison data and available season statistics. League-wide comparisons use the selected snapshot.</div>`;
    }
    else if (state.playerTab === "commission") {
        const cache = await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(state.snapshotId)}&mode=player&player_ea_id=${Number(p.ea_player_id)}`).catch(() => ({ state: "missing" }));
        const saved = cache.result || {}, report = saved.report || {}, catalog = new Map((saved.fact_catalog || []).map((f) => [f.id, f.label]));
        const refs = (ids) => esc((ids || []).map((id) => catalog.get(id) || id).join(" · "));
        const kindLabel = (kind) => kind === "fact" ? tr("claimFact") : kind === "hypothesis" ? tr("claimHypothesis") : tr("claimInference");
        const list = (items) => items?.length ? `<ul>${items.map((item) => `<li><span class="commission-claim-kind ${esc(item.kind || "inference")}">${esc(kindLabel(item.kind))}</span> ${esc(item.text)}${item.kind === "hypothesis" && item.limitations ? `<small class="commission-claim-limit">${tr("claimLimit")}: ${esc(item.limitations)}</small>` : ""}<small class="table-subline">Atlas facts: ${refs(item.fact_refs)}</small></li>`).join("")}</ul>` : '<p class="muted">No supported findings in this sample.</p>';
        const aiSummary = cache.state === "ready" || cache.state === "stale" ? `<div class="commission-report-head"><strong>${esc(report.summary?.text || "Saved player analysis")}</strong><small><span class="commission-claim-kind ${esc(report.summary?.kind || "inference")}">${esc(kindLabel(report.summary?.kind))}</span> · ${esc(saved.model || "Ollama local")} · ${esc(cache.generated_at || "")} · ${refs(report.summary?.fact_refs)}</small></div>${report.summary?.limitations ? `<p class="commission-claim-limit">${tr("claimLimit")}: ${esc(report.summary.limitations)}</p>` : ""}<details class="report-provenance"><summary>Evidence coverage and validation</summary><small>${num(saved.validation?.accepted_claims)} claims kept · ${num(saved.validation?.rejected_claims)} filtered · ${esc(saved.validation?.interpretation_quality || "Interpretation quality not independently scored")}</small></details>` : cache.state === "queued" || cache.state === "running" ? "Ollama is analyzing the player in the background." : "No saved Ollama report for this player and data version yet.";
        body = `<div class="grid metrics">${metric("Sample", esc(d.analysis?.dataQuality?.coverage == null ? "N/D" : `${num(d.analysis.dataQuality.coverage, 0)} % attributes`), "registered profile")}${metric("Appearances", num(d.totals.appearances), "selected career data")}${metric("Average rating", ratingValue(d.totals.average_rating, true), "recorded ratings")}${metric("Detailed matches", num(d.detailedMatches?.length || 0), "linked MatchStats")}</div><div class="grid two-col"><section class="card"><header class="card-header"><div><h2>Evidence-based player analysis</h2><p>Strengths, development areas, and training suggestions linked to attributes and match statistics</p></div><span class="status-badge ${cache.state === "ready" ? "good" : ""}">${esc(cache.state || "missing")}</span></header><div class="card-body"><div data-commission-report-output data-report-slot="commission-player" class="commission-report-output">${aiSummary}${commissionFollowupForm(report.information_requests, { snapshot_id: Number(state.snapshotId), mode: "player", player_ea_id: Number(p.ea_player_id), model: saved.model, coach_context: saved.fact_catalog?.find((f) => f.id === "coach_context")?.value })}${report.strengths?.length ? `<h4>Strengths supported by evidence</h4>${list(report.strengths)}` : ""}${report.development_areas?.length ? `<h4>Areas to develop</h4>${list(report.development_areas)}` : ""}${report.training_suggestions?.length ? `<h4>Commission training suggestions</h4>${list(report.training_suggestions)}` : ""}${report.observations?.length ? `<h4>Performance observations</h4>${list(report.observations)}` : ""}${report.recommendations?.length ? `<h4>Commission recommendations</h4>${list(report.recommendations)}` : ""}</div><button class="button primary" data-commission-report data-report-target="commission-player" data-mode="player" data-player-ea-id="${num(p.ea_player_id)}" data-snapshot-id="${num(state.snapshotId)}" data-force-refresh="${cache.state === "ready" ? "1" : "0"}">${cache.state === "ready" ? "Refresh Ollama analysis" : "Generate Ollama analysis"}</button><p class="data-note">The report is saved by career, player, season, model, and source facts. It reuses the saved answer until those facts change. Missing statistics are never treated as zero.</p></div></section><aside class="grid"><section class="card pad"><h3 class="card-title">Rule-based attribute strengths</h3>${horizontalBars(d.analysis?.strengths || [], "value", "label") || '<span class="muted">No attribute evidence.</span>'}</section><section class="card pad"><h3 class="card-title">Rule-based development areas</h3>${horizontalBars(d.analysis?.developmentAreas || [], "value", "label") || '<span class="muted">No attribute evidence.</span>'}<p class="chart-note">These are attribute comparisons. Ollama cross-checks them against recorded match performance before suggesting work.</p></section></aside></div>`;
    }
    else if (state.playerTab === "attributes") {
        const groups = { Pace: ["acceleration", "sprint_speed", "agility", "balance"], Technique: ["ball_control", "dribbling", "finishing", "shot_power", "long_shots", "volleys", "penalties", "crossing", "free_kick_accuracy", "curve"], BuildUp: ["vision", "short_passing", "long_passing", "positioning", "reactions", "composure"], Defending: ["interceptions", "heading_accuracy", "defensive_awareness", "standing_tackle", "sliding_tackle", "aggression"], Physical: ["jumping", "stamina", "strength"], Goalkeeping: ["gk_diving", "gk_handling", "gk_kicking", "gk_reflexes", "gk_positioning"] };
        body = `<div class="grid attribute-groups">${Object.entries(groups).map(([name, fields]) => `<section class="card pad"><h3 class="card-title">${esc(name)}</h3><div class="attribute-list">${fields.map((f) => { const v = Number(raw[f] ?? d.growth?.raw?.[f]); return Number.isFinite(v) ? `<div class="attribute-row"><div><span>${esc(f.replaceAll("_", " "))}</span><div class="attribute-bar"><i style="width:${Math.min(100, v)}%"></i></div></div><strong>${num(v)}</strong></div>` : ""; }).join("")}</div></section>`).join("")}</div>`;
    }
    else
        body = `<div class="grid"><div class="grid two-col"><section class="card pad"><h3 class="card-title">Current contract</h3>${d.contract ? `<div class="list"><div class="list-row"><div class="list-main"><strong>Weekly wage</strong></div><b>${money(d.contract.wage)}</b></div><div class="list-row"><div class="list-main"><strong>Duration</strong></div><b>${num(d.contract.duration_months)} months</b></div><div class="list-row"><div class="list-main"><strong>FC26 squad role</strong><small>technical game value; Tracker makes no playing-time promise</small></div><b>${esc(d.contract.player_role_label || "Not recorded")}<small class="raw-hint">Raw value ${d.contract.player_role_raw ?? "–"}</small></b></div><div class="list-row"><div class="list-main"><strong>Signing bonus</strong></div><b>${money(d.contract.raw?.signon_bonus)}</b></div></div>` : '<span class="muted">No contract in the confirmed export scope.</span>'}</section><section class="card pad"><h3 class="card-title">Loan / youth / awards</h3><div class="list">${d.loan ? `<div class="list-row"><div class="list-main"><strong>Active loan</strong><small>until ${dateText(d.loan.loan_end_date)}</small></div>${clubLink(d.loan.loan_team_ea_id, d.loan.raw?.loan_team_name)}</div>` : ""}${d.youth ? `<div class="list-row"><div class="list-main"><strong>Youth export</strong><small>${num(d.youth.raw?.months_in_squad)} months in squad</small></div>${statusBadge(`Tier ${d.youth.raw?.player_tier || "–"}`)}</div>` : ""}${d.awards.map((a) => `<div class="list-row"><div class="list-main"><strong>Award ${esc(a.award_type_id)}</strong><small>Season ${esc(a.season)}</small></div><b>${num(a.count)}×</b></div>`).join("") || (!d.loan && !d.youth ? '<span class="muted">No further records.</span>' : "")}</div></section></div>${playerCareerPathView(d.careerPath || {})}</div>`;
    const activeKit = d.teamIdentity?.kits?.find((k) => Number(k.kitType) === (String(p.primary_position).toUpperCase() === "GK" ? 2 : 0));
    content.innerHTML = `<div class="content-inner">${pageHead("Player profile", `Snapshot ${dateText(d.snapshot.career_date)}`)}<section class="card profile-hero media-profile-hero player-profile-banner" ${identityStyle(d.teamIdentity)}><div class="profile-media-stage"><div class="profile-kit-display">${activeKit ? kitCard(activeKit) : ""}</div><div class="profile-portrait-display">${playerPortrait(d.media, p.display_name, "player-portrait-large")}</div></div><div class="profile-copy"><div class="profile-club-line">${d.teamIdentity ? identityLogo(d.teamIdentity, p.team_name, "profile-club-logo") : ""}${p.team_ea_id ? clubLink(p.team_ea_id, p.team_name) : "Free agent"}</div><h1>${esc(p.display_name)}</h1><div class="profile-ea-id">EA ID ${num(p.ea_player_id)}</div><div class="profile-badges">${p.is_captain ? statusBadge("Captain", "blue") : ""}${positionBadge(p.primary_position)}${overallBadge(p.overall)}${overallBadge(p.potential)}${d.nationality ? nationalityFlag(d.nationality) : ""}<span class="chip player-age-chip"><b>Age</b>&nbsp; ${p.age == null ? "–" : `${num(p.age)} years`}</span><span class="chip" title="Estimated by Project Atlas Tracker"><b>Market value</b>&nbsp; ${money(market.value)}</span><span class="chip" title="${esc(wage.label || "Tracker wage estimate")} · ${money(wage.annual)} per year"><b>Wage/week</b>&nbsp; ${money(wage.value)}</span><span class="chip">${num(p.height)} cm</span><span class="chip">${num(p.weight)} kg</span>${d.youth ? statusBadge("Youth", "good") : ""}</div><div class="profile-hero-stats"><div><span>Appearances</span><strong>${num(d.totals.appearances)}</strong></div><div><span>Goals</span><strong>${num(d.totals.goals)}</strong></div><div><span>Assists</span><strong>${num(d.totals.assists)}</strong></div><div><span>Avg rating</span><strong>${ratingValue(d.totals.average_rating, true)}</strong></div></div></div><div class="profile-number" aria-label="Shirt number ${r.jersey_number ? num(r.jersey_number) : "not assigned"}">${r.jersey_number ? num(r.jersey_number) : "–"}</div></section><div class="tabbar" style="margin-top:14px">${tabs.map((t) => `<button data-player-tab="${t}" class="${state.playerTab === t ? "active" : ""}">${tabLabels[t]}</button>`).join("")}</div>${body}</div>`;
    if (state.playerTab === "stats")
        bindPlayerManualEditor(d, p);
    if (state.playerTab === "development")
        bindPlayerDevelopmentEditor(d, p);
}
function clubLeagueTable(data, currentTeamId, aliases = new Map()) {
    const items = data?.items || [];
    if (!items.length)
        return emptyState("No Atlas league table", "This league is either simulated in greater depth by EA or the Atlas season has not started yet.");
    const rows = items.map((row) => { const displayName = aliases.get(Number(row.team_ea_id)) || row.team_name, partial = !!row.aggregate_only, isFc = row.source === "fc_aggregate"; return `<tr class="${Number(row.team_ea_id) === Number(currentTeamId) ? "current-team" : ""}"><td class="center"><strong>${num(row.position)}</strong></td><td><span class="inline-identity">${identityLogo(row.identity, displayName, "table-club-logo")}${row.team_ea_id ? clubLink(row.team_ea_id, displayName) : esc(displayName || "–")}</span></td><td class="num">${num(row.matches_played)}</td><td class="num">${partial ? "–" : num(row.wins)}</td><td class="num">${partial ? "–" : num(row.draws)}</td><td class="num">${partial ? "–" : num(row.losses)}</td><td class="num">${partial ? "–" : `${num(row.goals_for)}:${num(row.goals_against)}`}</td><td class="num">${partial ? "–" : `${Number(row.goal_difference) > 0 ? "+" : ""}${num(row.goal_difference)}`}</td><td class="num"><strong>${num(row.points)}</strong></td><td>${statusBadge(isFc ? "FC26 table" : (row.source_label || "Atlas simulation"), isFc ? "good" : "blue")}</td></tr>`; });
    const calendar = data.calendar || {};
    const splitTable = (title, splitItems) => {
        if (!splitItems?.length)
            return "";
        const splitRows = splitItems.map((row) => { const displayName = aliases.get(Number(row.team_ea_id)) || row.team_name; return `<tr class="${Number(row.team_ea_id) === Number(currentTeamId) ? "current-team" : ""}"><td class="center"><strong>${num(row.position)}</strong></td><td><span class="inline-identity">${identityLogo(row.identity, displayName, "table-club-logo")}${row.team_ea_id ? clubLink(row.team_ea_id, displayName) : esc(displayName || "–")}</span></td><td class="num">${num(row.matches_played)}</td><td class="num">${num(row.wins)}</td><td class="num">${num(row.draws)}</td><td class="num">${num(row.losses)}</td><td class="num">${num(row.goals_for)}:${num(row.goals_against)}</td><td class="num">${Number(row.goal_difference) > 0 ? "+" : ""}${num(row.goal_difference)}</td><td class="num"><strong>${num(row.points)}</strong></td></tr>`; }).join("");
        return `<details class="league-split-table"><summary>${esc(title)}</summary>${table([{ label: "#", cls: "center" }, { label: "Club" }, { label: "P", cls: "num" }, { label: "W", cls: "num" }, { label: "D", cls: "num" }, { label: "L", cls: "num" }, { label: "Goals", cls: "num" }, { label: "GD", cls: "num" }, { label: "Pts", cls: "num" }], splitRows)}</details>`;
    };
    const splitTables = splitTable("Home table", data.homeItems || []) + splitTable("Away table", data.awayItems || []);
    return `<section class="card club-league-table"><header class="card-header"><div><h2>${esc(data.leagueName || "League table")}</h2><span>${calendar.lastUpdateDate ? `As of ${dateText(calendar.lastUpdateDate)} · ` : ""}${num(calendar.completedRounds)} of ${num(calendar.totalRounds)} rounds</span></div>${statusBadge(data.modelId || "Atlas World Simulation", "blue")}</header>${table([{ label: "#", cls: "center" }, { label: "Club" }, { label: "P", cls: "num" }, { label: "W", cls: "num" }, { label: "D", cls: "num" }, { label: "L", cls: "num" }, { label: "Goals", cls: "num" }, { label: "GD", cls: "num" }, { label: "Pts", cls: "num" }, { label: "Source" }], rows)}${splitTables}<div class="data-note">${esc(data.notice || "")}</div></section>`;
}
async function renderClub() {
    const [d, clubNames] = await Promise.all([
        api(`/api/snapshots/${state.snapshotId}/clubs/${Number(state.routeData.id)}`),
        api(`/api/careers/${state.careerId}/club-names`),
    ]);
    const t = d.team || {}, l = d.leagueState || {}, identity = d.identity || {};
    const aliases = new Map((clubNames.items || []).map((item) => [Number(item.eaTeamId), String(item.displayName)]));
    const clubNameOverride = (clubNames.items || []).find((item) => Number(item.eaTeamId) === Number(t.ea_team_id));
    const displayName = clubNameOverride?.displayName || t.team_name;
    t.team_name = displayName;
    const stadium = identity.stadiums?.[0], stadiumWithImage = identity.stadiums?.find((item) => item.variants?.length), stadiumImage = stadiumWithImage?.variants?.[0];
    const activeTab = state.clubTab || "overview";
    const tabs = [
        ["overview", "Overview"], ["squad", "Squad"], ["matches", "Matches"], ["competitions", "Competitions"],
        ["league", "League & development"], ["media", "Media & name"],
    ];
    const scorer = `<section class="card"><header class="card-header"><h2>Scorer</h2></header><div class="card-body list">${(d.leaders || []).map((p) => `<div class="list-row">${playerPortrait(p.media, p.display_name, "list-portrait")}<div class="list-main">${playerLink(p.player_ea_id, p.display_name)}<small>${num(p.appearances)} appearances · ${esc(p.source === "hybrid" ? "Snapshot + Atlas league" : p.source === "simulated" ? "Atlas simulation" : "Snapshot")}</small></div><div class="list-value"><strong>${num(p.goals)} G</strong><small>${num(p.assists)} A</small></div></div>`).join("") || '<span class="muted">No scoring data.</span>'}</div></section>`;
    const competitions = `<section class="card pad"><h3 class="card-title">Competitions</h3><div class="list">${(d.competitions || []).map((c) => `<div class="list-row">${identityLogo(c.identity, c.competition_name, "inline-logo")}<div class="list-main">${c.competition_object_id ? competitionLink(c.competition_object_id, c.competition_name) : esc(c.competition_name || "–")}<small>${num(c.completed)} of ${num(c.matches)} completed${c.source_label ? ` · ${esc(c.source_label)}` : ""}</small></div></div>`).join("") || '<span class="muted">No competitions.</span>'}</div></section>`;
    const squad = `<section class="card"><header class="card-header"><h2>Squad</h2><span>${num(d.squad?.length)} players</span></header>${table([{ label: "#", cls: "center" }, { label: "Player" }, { label: "Age", cls: "center" }, { label: "Pos.", cls: "center" }, { label: "OVR", cls: "center" }, { label: "POT", cls: "center" }, { label: "Market value", cls: "num" }, { label: "Wage", cls: "num" }, { label: "Contract" }], (d.squad || []).map((p) => `<tr><td class="center">${num(p.jersey_number)}</td><td><div class="player-line">${playerPortrait(p.media, p.display_name, "table-portrait")}<div class="player-line-copy">${playerLink(p.ea_player_id, p.display_name)}</div></div></td><td class="center" data-sort="${p.age ?? 999}">${p.age == null ? "–" : num(p.age)}</td><td class="center" data-sort="${positionOrder(p.primary_position, p.raw?.primary_position_id || p.primary_position_id)}">${positionBadge(p.primary_position)}</td><td class="center">${overallBadge(p.overall)}</td><td class="center">${overallBadge(p.potential)}</td><td class="num" title="${financialHint(p.financial, "market")}">${money(p.market_value)}</td><td class="num" title="${financialHint(p.financial, "wage")}">${money(p.weekly_wage)}</td><td>${esc(p.contract_valid_until || "–")}</td></tr>`))}</section>`;
    const matches = `<section class="card"><header class="card-header"><h2>Matches</h2><span>${num(d.matches?.length)} in snapshot</span></header>${renderMatchRows((d.matches || []).slice().reverse())}</section>`;
    const leagueHistory = `<div class="grid two-col"><section class="card pad"><h3 class="card-title">Club development</h3>${lineChart(d.history || [], ["overall", "attack"])}</section><section class="card pad"><div class="card-title-row"><h3 class="card-title">League path</h3><span>${num((d.leagueHistory || []).length)} seasons</span></div>${leaguePositionChart(d.leagueHistory || [])}${(d.leagueHistory || []).length ? `<div class="compact-history-list league-season-results">${d.leagueHistory.map((h) => `<div><strong>${esc(h.season_label)}</strong><span>${esc(h.league_name)}</span><b>${esc(h.position_display || "–")}</b>${h.movement === "promotion" ? statusBadge("Promotion", "good") : h.movement === "relegation" ? statusBadge("Relegation", "bad") : h.movement === "same" ? statusBadge("same league") : statusBadge(h.movement === "first" ? "Start" : "unknown")}${statusBadge(h.source_label, h.source === "manual" ? "good" : "")}</div>`).join("")}</div>` : ""}</section></div>${clubLeagueTable(d.leagueTable || {}, Number(t.ea_team_id), aliases)}`;
    const mediaAndName = `${(identity.kits?.length || identity.stadiums?.length || t.stadium_capacity) ? `<div class="grid two-col"><section class="card pad"><h3 class="card-title">Kits</h3><div class="kit-grid">${(identity.kits || []).map(kitCard).join("") || '<span class="muted">No kits found.</span>'}</div></section><section class="card pad"><h3 class="card-title">Stadium</h3>${identity.stadiums?.length ? identity.stadiums.map((item) => `<div class="stadium-block"><div class="card-title-row"><strong>${esc(item.name)}</strong>${statusBadge(item.stadiumTypeLabel || "Unknown type", item.stadiumType === "authentic" ? "good" : "blue")}</div><div class="stadium-facts"><span>Capacity <b>${t.stadium_capacity == null ? "–" : num(t.stadium_capacity)}</b></span><span>Stadium ID <b>${num(item.stadiumId)}</b></span></div><small>Capacity comes from the selected club snapshot.</small><div class="stadium-gallery">${item.variants?.length ? item.variants.map((v) => `<figure><img src="${esc(v.url)}" alt="${esc(item.name)}" loading="lazy"><figcaption>Variant ${esc(v.variant || "–")}</figcaption></figure>`).join("") : '<span class="muted">No stadium images imported yet.</span>'}</div></div>`).join("") : '<span class="muted">No stadium assigned.</span>'}</section></div>` : ""}<section class="card pad club-name-editor"><div class="card-title-row"><div><h3 class="card-title">Club name in Tracker</h3><span>Snapshot name: ${esc(t.team_name_original || clubNameOverride?.originalName || t.team_name)}</span></div>${clubNameOverride?.overridden ? statusBadge("Manually adjusted", "good") : statusBadge("Snapshot")}</div><form data-club-name-form class="manual-form"><input type="hidden" name="eaTeamId" value="${esc(String(t.ea_team_id))}"><div class="manual-form-grid"><label class="span-2"><span>Display club name</span><input name="displayName" required maxlength="120" value="${esc(displayName)}"></label><label class="span-2"><span>Note</span><input name="note" maxlength="300" value="${esc(clubNameOverride?.note || "")}" placeholder="e.g. licensed or modded name"></label></div><div class="manual-form-actions">${clubNameOverride?.overridden ? `<button type="button" class="button" data-club-name-reset="${esc(String(t.ea_team_id))}">Reset to snapshot name</button>` : ""}<button type="submit" class="button primary">Save club name</button></div></form></section>`;
    let body = "";
    if (activeTab === "overview")
        body = `<div class="grid metrics club-metrics">${metric("Squad", num(d.summary.squad_count), "players")}${metric("Avg. OVR", num(d.summary.average_overall, 1), "squad strength", "green")}${metric("Avg. POT", num(d.summary.average_potential, 1), "squad potential", "blue")}${metric("Squad value", money(t.club_worth), "club value")}${metric("Wages", money(d.summary.wage_total), "per week", "amber")}${metric("Stadium capacity", t.stadium_capacity == null ? "–" : num(t.stadium_capacity), stadium?.name || "snapshot value")}</div><div class="grid two-col">${scorer}${competitions}</div>`;
    else if (activeTab === "squad")
        body = squad;
    else if (activeTab === "matches")
        body = matches;
    else if (activeTab === "competitions")
        body = competitions;
    else if (activeTab === "league")
        body = leagueHistory;
    else
        body = mediaAndName;
    content.innerHTML = `<div class="content-inner wide">${pageHead(displayName, `EA Team ID ${num(t.ea_team_id)} · ${esc(t.league_name || "")}`)}<section class="card hero club-profile-hero" style="--club-primary:${esc(identity.colors?.[0] || '#123653')};--club-secondary:${esc(identity.colors?.[1] || '#0b1929')};--club-accent:${esc(identity.colors?.[2] || identity.colors?.[1] || '#20df83')};${stadiumImage ? `background-image:linear-gradient(90deg,rgba(4,12,22,.94),rgba(4,12,22,.65)),url('${esc(stadiumImage.url)}')` : ''}"><div class="hero-content">${identityLogo(identity, displayName, "hero-club-logo")}<div class="hero-copy"><p>CLUB PROFILE</p><h1>${esc(displayName)}</h1><p>${esc(t.league_name || "League unavailable")} · Table position ${l.current_table_position ? `#${num(l.current_table_position)}` : "–"}${l.position_source_label ? ` · ${esc(l.position_source_label)}` : ""}</p><div class="hero-meta"><span class="chip accent">OVR ${num(t.overall)}</span><span class="chip">ATT ${num(t.attack)}</span><span class="chip">MID ${num(t.midfield)}</span><span class="chip">DEF ${num(t.defence)}</span></div></div></div></section><div class="tabbar club-profile-tabs">${tabs.map(([id, label]) => `<button data-club-tab="${id}" class="${activeTab === id ? "active" : ""}">${label}</button>`).join("")}</div>${body}</div>`;
}
async function renderCompare() {
    const snaps = state.snapshots.slice().sort((a, b) => a.import_sequence - b.import_sequence);
    if (!state.compareFrom)
        state.compareFrom = Number(snaps[0]?.id);
    if (!state.compareTo)
        state.compareTo = Number(snaps.at(-1)?.id);
    const opts = (id) => snaps.map((s) => `<option value="${s.id}" ${Number(id) === Number(s.id) ? "selected" : ""}>${dateText(s.career_date)} · #${s.import_sequence}</option>`).join("");
    let result = null;
    if (state.compareFrom && state.compareTo && Number(state.compareFrom) !== Number(state.compareTo))
        result = await api(`/api/careers/${state.careerId}/compare?from=${state.compareFrom}&to=${state.compareTo}`);
    content.innerHTML = `<div class="content-inner">${pageHead("Snapshot comparison", "Squad, development, statistics and result changes between two states")}<section class="card pad"><div class="compare-pickers"><label><span class="card-title">From</span><select id="compareFrom" class="filter-select" style="width:100%">${opts(state.compareFrom)}</select></label><div class="compare-arrow">→</div><label><span class="card-title">To</span><select id="compareTo" class="filter-select" style="width:100%">${opts(state.compareTo)}</select></label></div></section>${!result ? `<div style="margin-top:14px">${emptyState("Choose two different snapshots", "At least two imported states are required for a comparison.")}</div>` : `<div class="grid metrics" style="margin-top:14px">${metric("New players", num(result.summary.added_players), "in the squad", "green")}${metric("Departures", num(result.summary.removed_players), "no longer in the squad", "red")}${metric("Changed", num(result.summary.changed_players), "OVR, POT, contract…", "blue")}${metric("New results", num(result.summary.new_results), "completed matches")}${metric("Loan changes", num(result.summary.new_loans + result.summary.ended_loans), "starts and ends", "amber")}</div><div class="grid two-col"><section class="card"><header class="card-header"><h2>New players</h2></header><div class="card-body list">${result.addedPlayers.map((p) => `<div class="list-row">${playerPortrait(p.media, p.display_name, "list-portrait")}<div class="list-main">${playerLink(p.ea_player_id, p.display_name)}<small>${pos(p.primary_position)}</small></div>${overallBadge(p.overall)}</div>`).join("") || '<span class="muted">No arrivals.</span>'}</div></section><section class="card"><header class="card-header"><h2>Departures</h2></header><div class="card-body list">${result.removedPlayers.map((p) => `<div class="list-row">${playerPortrait(p.media, p.display_name, "list-portrait")}<div class="list-main">${playerLink(p.ea_player_id, p.display_name)}<small>${pos(p.primary_position)}</small></div>${overallBadge(p.overall)}</div>`).join("") || '<span class="muted">No departures.</span>'}</div></section></div><section class="card" style="margin-top:14px"><header class="card-header"><h2>Player development and contract changes</h2></header>${table([{ label: "Players" }, { label: "Old OVR", cls: "center" }, { label: "New OVR", cls: "center" }, { label: "Δ", cls: "num" }, { label: "POT Δ", cls: "num" }, { label: "Wage Δ", cls: "num" }, { label: "Changed" }], result.changedPlayers.map((p) => `<tr><td>${playerLink(p.player_id, p.display_name)}</td><td class="center">${overallBadge(p.before.overall)}</td><td class="center">${overallBadge(p.after.overall)}</td><td class="num">${delta(p.overall_delta)}</td><td class="num">${delta(p.potential_delta)}</td><td class="num">${p.wage_delta ? `${p.wage_delta > 0 ? "+" : ""}${money(p.wage_delta)}` : "–"}</td><td>${p.changed_fields.map((f) => `<span class="mini-tag">${esc(f)}</span>`).join(" ")}</td></tr>`))}</section><div class="grid two-col" style="margin-top:14px"><section class="card"><header class="card-header"><h2>New results</h2></header>${renderMatchRows(result.newResults)}</section><section class="card"><header class="card-header"><h2>Statistics gained</h2></header><div class="card-body list">${result.statDeltas.slice(0, 20).map((p) => `<div class="list-row"><div class="list-main">${playerLink(p.player_id, p.display_name)}<small>+${num(p.appearances)} apps</small></div><div class="list-value"><strong>+${num(p.goals)} G</strong><small>+${num(p.assists)} A</small></div></div>`).join("") || '<span class="muted">No statistical changes.</span>'}</div></section></div>`}</div>`;
    const f = $("#compareFrom", content), t = $("#compareTo", content);
    f.onchange = () => { state.compareFrom = Number(f.value); renderCompare(); };
    t.onchange = () => { state.compareTo = Number(t.value); renderCompare(); };
}
function chronologyEntityLink(event) {
    if (event.fixture_id)
        return matchLink(event.fixture_id, "Open match");
    if (event.player_id)
        return playerLink(event.player_id, "Player profile");
    if (event.competition_id)
        return competitionLink(event.competition_id, "Competition");
    if (event.club_id)
        return clubLink(event.club_id, "Club profile");
    return "";
}
function chronologyIcon(type) { const icons = { match: "⚽", contract: "✍", loan: "↔", transfer: "⇄", season: "S", competition_result: "★", youth: "◇", award: "★", squad: "+", development: "↗", snapshot: "●", milestone: "◆" }; return icons[String(type)] || "•"; }
async function renderChronology() {
    const d = await api(`/api/careers/${state.careerId}/chronology?snapshot_id=${state.snapshotId}`);
    const types = Object.keys(d.summary.by_type || {}).sort();
    const query = state.chronologyQuery.toLowerCase();
    const events = d.events.filter((event) => (state.chronologyType === "all" || event.type === state.chronologyType) && (!query || `${event.title} ${event.description}`.toLowerCase().includes(query)));
    const groups = new Map();
    events.forEach((event) => {
        const key = event.date ? event.date.slice(0, 7) : "no-date";
        if (!groups.has(key))
            groups.set(key, []);
        groups.get(key).push(event);
    });
    content.innerHTML = `<div class="content-inner">${pageHead("Career timeline", "Combined from imported data and manually maintained historical seasons", `<button class="button" data-route="compare">Compare snapshots</button>`)}<div class="grid metrics">${metric("Events", num(d.summary.event_count), "up to the selected snapshot")}${metric("Exact dates", num(d.summary.exact), "source includes a date", "green")}${metric("Snapshot-based", num(d.summary.snapshot_based), "detected between snapshots", "blue")}${metric("Estimated", num(d.summary.estimated), "clearly labelled", "amber")}${metric("Manual", num(d.summary.manual), "added as historical data", "green")}</div><div class="filter-row"><input id="chronologyQuery" class="filter-input" value="${esc(state.chronologyQuery)}" placeholder="Search timeline…"><select id="chronologyType" class="filter-select"><option value="all">All events</option>${types.map((type) => `<option value="${esc(type)}" ${type === state.chronologyType ? "selected" : ""}>${esc(type)} (${num(d.summary.by_type[type])})</option>`).join("")}</select><span class="chip">${num(events.length)} visible</span></div>${events.length ? `<div class="career-chronology">${[...groups.entries()].map(([month, monthEvents]) => `<section class="chronology-month"><header><h2>${month === "no-date" ? "No date" : new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(new Date(`${month}-15T12:00:00`))}</h2><span>${num(monthEvents.length)} events</span></header><div class="chronology-line">${monthEvents.map((event) => `<article class="chronology-event type-${esc(event.type)} importance-${num(event.importance)}"><div class="chronology-marker">${chronologyIcon(event.type)}</div><div class="chronology-card card"><div class="chronology-meta"><time>${dateText(event.date)}</time>${statusBadge(event.type)}${event.precision === "estimated" ? statusBadge("estimated", "warn") : event.precision === "snapshot" ? statusBadge("Snapshot", "") : event.precision === "manual" ? statusBadge("manual", "good") : statusBadge("exact", "good")}</div><h3>${esc(event.title)}</h3><p>${esc(event.description)}</p><footer><span class="source-note">Source: ${esc(event.source)}</span>${chronologyEntityLink(event)}</footer></div></article>`).join("")}</div></section>`).join("")}</div>` : emptyState("No matching events", "Adjust the filters or search term.")}</div>`;
    const q = $("#chronologyQuery", content), type = $("#chronologyType", content);
    q.oninput = () => { state.chronologyQuery = q.value; renderChronology(); };
    type.onchange = () => { state.chronologyType = type.value; renderChronology(); };
}
async function renderSnapshots() { const coverage = await api(`/api/snapshots/${state.snapshotId}/coverage`); content.innerHTML = `<div class="content-inner">${pageHead("Snapshot timeline", "Immutable career states", `<button class="button primary" data-route="compare">Compare snapshots</button>`)}<div class="grid split-65"><section class="card"><header class="card-header"><h2>Career history</h2></header><div class="card-body timeline">${state.snapshots.slice().sort((a, b) => a.import_sequence - b.import_sequence).map((s) => `<div class="timeline-item ${Number(s.id) === Number(state.snapshotId) ? "current" : ""}"><h3><button class="entity-link" data-snapshot="${s.id}">${dateText(s.career_date)}</button></h3><p>Season ${Number(s.season_index) + 1} · Sequence ${num(s.import_sequence)} · ${esc(s.exporter_version || "")}</p></div>`).join("")}</div></section><aside class="grid"><section class="card pad"><h3 class="card-title">Data coverage for the selected snapshot</h3><div class="grid coverage-grid">${Object.entries(coverage.counts).map(([k, v]) => `<div class="coverage-card card"><strong>${num(v)}</strong><small>${esc(k.replaceAll("_", " "))}</small></div>`).join("")}</div></section><section class="card"><header class="card-header"><h2>Imported files</h2></header>${table([{ label: "File" }, { label: "Rows", cls: "num" }, { label: "Size", cls: "num" }, { label: "Status" }], coverage.files.map((f) => `<tr><td class="mono">${esc(f.file_name)}</td><td class="num">${num(f.row_count)}</td><td class="num">${compact(f.byte_size)}B</td><td>${statusBadge(f.status || "–", f.status === "ok" ? "good" : "")}</td></tr>`))}</section></aside></div></div>`; }
async function renderImports() {
    const [rows, clock] = await Promise.all([
        api("/api/imports"),
        state.careerId ? api(`/api/careers/${state.careerId}/clock`) : Promise.resolve(null),
    ]), ms = state.status?.matchStats || {};
    if (clock)
        state.careerClock = clock;
    const roots = (ms.roots || []).map((root) => `<code>${esc(root)}</code>`).join("<br>") || "–";
    const pulses = clock?.recentPulses || [];
    const resetSnapshots = state.snapshots.slice().sort((a, b) => a.import_sequence - b.import_sequence);
    const resetOptions = resetSnapshots.map((s) => `<option value="${s.id}">${dateText(s.career_date)} · Snapshot #${num(s.import_sequence)}${s.import_sequence === 1 ? " · first snapshot" : ""}</option>`).join("");
    content.innerHTML = `<div class="content-inner">${pageHead("Import log", "Snapshots, daily/transfer pulses and detailed FC26 match data", `<button class="button primary" data-action="scan">Scan now</button>`)}
      <div class="grid metrics">${metric("Career date", clock?.careerDate ? dateText(clock.careerDate) : "–", clock?.source === "transfer_pulse" ? `Transfer pulse · snapshot data from ${dateText(clock.snapshotDate)}` : "Full snapshot", "green")}${metric("Daily/transfer pulses", num(clock?.pulseCount || 0), pulses.length ? `latest ${dateText(pulses[0]?.career_date)}` : "none imported yet", "blue")}${metric("MatchStats exports", num(ms.exports || 0), `${num(ms.linked || 0)} linked unambiguously`, "green")}${metric("Unlinked exports", num(ms.pending || 0), Number(ms.pending || 0) ? "left unlinked for review" : "no unlinked detailed matches", Number(ms.pending || 0) ? "amber" : "blue")}</div>
      <section class="card pad"><div class="card-title-row"><div><h3 class="card-title">AutoCapture and import detection</h3><span>Tracker handles full snapshots, lightweight daily pulses and MatchStats separately.</span></div>${statusBadge("AutoCapture", "good")}</div><p class="chart-note">Transfer pulses advance the global career clock between full snapshots and record transfers and loans. Full snapshots remain the source for attributes, statistics and squad state. MatchStats are imported separately from <code>match_stats\\ready</code>.</p><div class="data-note">Watched MatchStats paths:<br>${roots}</div></section>
      <section class="card"><header class="card-header"><h2>Latest daily/transfer pulses</h2><span>${num(pulses.length)} shown</span></header>${pulses.length ? table([{ label: "Career date" }, { label: "Players", cls: "num" }, { label: "Loans", cls: "num" }, { label: "Imported" }, { label: "Pulse-ID" }], pulses.map((p) => `<tr><td>${dateText(p.career_date)}</td><td class="num">${num(p.player_count)}</td><td class="num">${num(p.loan_count)}</td><td>${dateText(p.imported_at)}</td><td class="mono">${esc(p.public_id || "–")}</td></tr>`)) : '<div class="card-body muted">No daily/transfer pulse has been imported yet.</div>'}</section>
      <section class="card"><header class="card-header"><h2>Snapshot and importer events</h2></header>${table([{ label: "Time" }, { label: "Level" }, { label: "Code" }, { label: "Message" }, { label: "Snapshot" }], rows.map((e) => `<tr><td>${esc(e.occurred_at)}</td><td>${statusBadge(e.level, e.level === "error" ? "bad" : e.level === "info" ? "good" : "")}</td><td class="mono">${esc(e.code)}</td><td>${esc(e.message)}</td><td class="mono">${esc(e.snapshot_external_id || "–")}</td></tr>`))}</section>
      <section class="card pad" style="margin-top:14px"><div class="card-title-row"><div><h3 class="card-title">Reset career data</h3><span>For testing or a clean restart from an earlier full snapshot.</span></div>${statusBadge("destructive", "warn")}</div><p class="chart-note">A hard reset keeps all full snapshots up to and including the selected target. Later snapshots, daily/transfer pulses, MatchStats and career-specific Tracker state are removed. Global settings, reference data and media are retained. Tracker creates a database backup before every reset.</p><div class="grid two-col" style="margin-top:12px"><label><span class="card-title">Keep target state</span><select class="filter-select" style="width:100%;margin-top:6px" data-reset-target>${resetOptions}</select></label><label class="setting-toggle" style="margin-top:18px"><input type="checkbox" data-reset-delete-files><span><strong>Permanently delete raw files</strong><small>By default, Tracker moves removed export folders into a reset archive and only removes them from the active career.</small></span></label></div><div class="workspace-warning" style="margin-top:12px"><strong>Hard reset:</strong> Career-specific Tracker data created after the selected import is also reset. Recovery is possible only from the automatic database backup or the reset archive.</div><div class="page-actions" style="margin-top:12px"><button class="button danger" data-reset-career>Reset to selected snapshot</button></div></section></div>`;
}
function manualSeasonTitle(season) {
    const years = season.start_year && season.end_year ? `${season.start_year}/${String(season.end_year).slice(-2)}` : "";
    return years ? `${season.label} · ${years}` : season.label;
}
function manualSourceBadge() {
    return statusBadge("manual", "good");
}
function manualUpdated(value) {
    return value ? `<small class="manual-updated">Updated ${dateText(String(value).slice(0, 10))}</small>` : "";
}
function manualPreferenceKey() { return `project-atlas-tracker-manual-${state.careerId || "none"}`; }
function manualPreferences() {
    try {
        return JSON.parse(localStorage.getItem(manualPreferenceKey()) || "{}");
    }
    catch {
        return {};
    }
}
function saveManualPreferences(values) {
    localStorage.setItem(manualPreferenceKey(), JSON.stringify({ ...manualPreferences(), ...values }));
}
function bindManualKeyboard(form, saveNext) {
    form.addEventListener("keydown", event => {
        if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter")
            return;
        event.preventDefault();
        if (event.shiftKey && saveNext instanceof HTMLButtonElement)
            saveNext.click();
        else
            form.requestSubmit();
    });
}
function bindUnknownFee(form) {
    const checkbox = $("[name='feeUnknown']", form);
    const input = $("[name='fee']", form);
    if (!checkbox || !input)
        return;
    const sync = () => { input.disabled = checkbox.checked; if (checkbox.checked)
        input.value = ""; };
    checkbox.addEventListener("change", sync);
    sync();
}
function manualFormActions(cancelLabel = "Cancel", saveNext = false) {
    return `<div class="manual-form-actions"><small>Ctrl+Enter saves${saveNext ? " · Ctrl+Shift+Enter saves and opens the next player" : ""}</small><button type="button" class="button" data-manual-cancel>${esc(cancelLabel)}</button>${saveNext ? `<button type="button" class="button" data-manual-save-next><span data-icon="save"></span>Save & next player</button>` : ""}<button type="submit" class="button primary"><span data-icon="save"></span>Save</button></div>`;
}
function manualPlayerPicker(name = "", playerId = "") {
    return `<label class="span-2 manual-player-field"><span>Player</span><div class="manual-player-picker"><input name="displayName" data-manual-player-search required value="${esc(name)}" placeholder="Enter at least two characters" autocomplete="off"><input type="hidden" name="playerEaId" value="${playerId ?? ""}"><div class="manual-player-results" data-manual-player-results hidden></div></div><small data-manual-player-selection>${playerId ? `Linked to EA ID ${num(playerId)}` : "All players in the career are searched; custom names remain possible."}</small></label>`;
}
function manualSeasonForm(season) {
    const current = season || {};
    return `<section class="card pad manual-editor-card"><h3 class="card-title">${season ? "Edit season" : "Create historical season"}</h3>
      <form id="manualSeasonForm" class="manual-form">
        <input type="hidden" name="id" value="${current.id || ""}">
        <div class="manual-form-grid">
          <label><span>Season number</span><input name="seasonNumber" type="number" min="1" max="100" required value="${Number.isFinite(Number(current.season_index)) ? Number(current.season_index) + 1 : ""}" placeholder="1"></label>
          <label><span>Label</span><input name="label" required maxlength="120" value="${esc(current.label || "")}" placeholder="e.g. Season 1"></label>
          <label><span>Start year</span><input name="startYear" type="number" min="1900" max="2200" required value="${current.start_year ?? ""}" placeholder="2023"></label>
          <label><span>End year</span><input name="endYear" type="number" min="1900" max="2201" required value="${current.end_year ?? ""}" placeholder="2024"></label>
          <label class="span-2"><span>Managed club</span><input name="managedTeamName" list="manualTeamNames" value="${esc(current.managed_team_name || "")}" placeholder="Club name"></label>
          <label class="span-2"><span>Notes</span><textarea name="notes" rows="3" maxlength="2000" placeholder="Optional">${esc(current.notes || "")}</textarea></label>
        </div>${manualFormActions()}
      </form></section>`;
}
function manualCompetitionForm(seasonId, competition) {
    const current = competition || {};
    return `<section class="card pad manual-editor-card"><h3 class="card-title">${competition ? "Edit competition" : "Add competition"}</h3>
      <form id="manualCompetitionForm" class="manual-form">
        <input type="hidden" name="id" value="${current.id || ""}"><input type="hidden" name="seasonId" value="${seasonId}">
        <div class="manual-form-grid">
          <label><span>Type</span><select name="competitionType"><option value="league" ${current.competition_type === "league" ? "selected" : ""}>League</option><option value="cup" ${current.competition_type === "cup" ? "selected" : ""}>Cup</option><option value="supercup" ${current.competition_type === "supercup" ? "selected" : ""}>Supercup</option><option value="playoff" ${current.competition_type === "playoff" ? "selected" : ""}>Play-offs</option><option value="other" ${!current.competition_type || current.competition_type === "other" ? "selected" : ""}>Other</option></select></label>
          <label><span>Competition name</span><input name="competitionName" list="manualCompetitionNames" required value="${esc(current.competition_name || "")}" placeholder="z. B. 2. Bundesliga"></label>
          <label><span>League position</span><input name="finalPosition" type="number" min="1" max="999" value="${current.final_position ?? ""}" placeholder="league only"></label>
          <label><span>Final result</span><input name="resultText" maxlength="160" value="${esc(current.result_text || "")}" placeholder="e.g. Quarter-final / Winner"></label>
          <label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="2000">${esc(current.notes || "")}</textarea></label>
        </div>${manualFormActions()}
      </form></section>`;
}
function manualStatForm(seasonCompetitions, stat) {
    const current = stat || {};
    const selectedCompetition = Number(current.manual_competition_id || state.manualDraftCompetitionId || seasonCompetitions[0]?.id);
    return `<section class="card pad manual-editor-card"><h3 class="card-title">${stat ? "Edit player statistics" : "Add player statistics"}</h3>
      <form id="manualStatForm" class="manual-form">
        <input type="hidden" name="id" value="${current.id || ""}">
        <div class="manual-form-grid">
          <label class="span-2"><span>Competition</span><select name="competitionId" required>${seasonCompetitions.map(c => `<option value="${c.id}" ${selectedCompetition === Number(c.id) ? "selected" : ""}>${esc(c.competition_name)}</option>`).join("")}</select></label>
          ${manualPlayerPicker(current.display_name || "", current.player_ea_id)}
          <label><span>Matches</span><input name="appearances" type="number" min="0" max="999" value="${current.appearances ?? 0}"></label>
          <label><span>Goals</span><input name="goals" type="number" min="0" max="999" value="${current.goals ?? 0}"></label>
          <label><span>Assists</span><input name="assists" type="number" min="0" max="999" value="${current.assists ?? 0}"></label>
          <label><span>Clean sheets</span><input name="cleanSheets" type="number" min="0" max="999" value="${current.clean_sheets ?? 0}"></label>
          <label><span>Avg. rating</span><input name="averageRating" type="text" inputmode="decimal" value="${current.average_rating ?? ""}" placeholder="7,25"></label>
          <label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="1000">${esc(current.notes || "")}</textarea></label>
        </div>${manualFormActions("Cancel", !stat)}
      </form></section>`;
}
function manualTransactionForm(seasonId, transaction) {
    const current = transaction || {};
    const prefs = manualPreferences();
    const counterparty = current.direction === "incoming" ? current.from_team_name : current.to_team_name;
    const counterpartyId = current.direction === "incoming" ? current.from_team_ea_id : current.to_team_ea_id;
    const defaultType = current.transaction_type || prefs.transactionType || "transfer";
    const defaultDirection = current.direction || prefs.direction || "incoming";
    const defaultCounterparty = counterparty || prefs.counterpartyTeamName || "";
    const feeUnknown = !transaction ? Boolean(prefs.feeUnknown) : current.fee == null;
    return `<section class="card pad manual-editor-card"><h3 class="card-title">${transaction ? "Edit movement" : "Add transfer or loan"}</h3>
      <form id="manualTransactionForm" class="manual-form">
        <input type="hidden" name="id" value="${current.id || ""}"><input type="hidden" name="seasonId" value="${seasonId}">
        <div class="manual-form-grid">
          <label><span>Movement</span><select name="transactionType"><option value="transfer" ${defaultType !== "loan" ? "selected" : ""}>Transfer</option><option value="loan" ${defaultType === "loan" ? "selected" : ""}>Loan</option></select></label>
          <label><span>Direction</span><select name="direction"><option value="incoming" ${defaultDirection !== "outgoing" ? "selected" : ""}>Incoming</option><option value="outgoing" ${defaultDirection === "outgoing" ? "selected" : ""}>Outgoing</option></select></label>
          ${manualPlayerPicker(current.display_name || "", current.player_ea_id)}
          <label><span>Other club</span><input name="counterpartyTeamName" list="manualTeamNames" required value="${esc(defaultCounterparty)}" placeholder="selling / buying club"></label>
          <label><span>Other club-ID</span><input name="counterpartyTeamEaId" type="number" min="1" value="${counterpartyId ?? ""}"></label>
          <label><span>Fee</span><input name="fee" type="number" min="0" step="1" value="${current.fee ?? ""}" placeholder="in euros"></label>
          <label class="manual-check"><span>Fee known?</span><span><input name="feeUnknown" type="checkbox" ${feeUnknown ? "checked" : ""}> Unknown</span></label>
          <label><span>Date</span><input name="transactionDate" type="date" value="${esc(current.transaction_date || "")}"></label>
          <label><span>Loan end</span><input name="loanEndDate" type="date" value="${esc(current.loan_end_date || "")}"></label>
          <label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="2000">${esc(current.notes || "")}</textarea></label>
        </div>${manualFormActions("Cancel", !transaction)}
      </form></section>`;
}
function manualLeagueFinishForm(seasonId, finish) {
    const current = finish || {};
    return `<section class="card pad manual-editor-card"><h3 class="card-title">${finish ? "Edit league finish" : "Add league finish"}</h3>
      <form id="manualLeagueFinishForm" class="manual-form">
        <input type="hidden" name="id" value="${current.id || ""}"><input type="hidden" name="seasonId" value="${seasonId}">
        <div class="manual-form-grid">
          <label class="span-2"><span>Club</span><input name="teamName" list="manualTeamNames" required value="${esc(current.team_name || "")}" placeholder="Club name"></label>
          <label><span>Club EA ID</span><input name="teamEaId" type="number" min="1" value="${current.team_ea_id ?? ""}" placeholder="optional"></label>
          <label><span>League</span><input name="leagueName" list="manualLeagueNames" required value="${esc(current.league_name || "")}" placeholder="z. B. Bundesliga"></label>
          <label><span>League EA ID</span><input name="leagueEaId" type="number" min="1" value="${current.league_ea_id ?? ""}" placeholder="optional"></label>
          <label><span>Final position</span><input name="finalPosition" type="number" min="1" max="999" required value="${current.final_position ?? ""}" placeholder="1"></label>
          <label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="2000">${esc(current.notes || "")}</textarea></label>
        </div>${manualFormActions()}
      </form></section>`;
}
function manualDataLists(data) {
    return `<datalist id="manualTeamNames">${data.references.teams.map((t) => `<option value="${esc(t.team_name)}">EA-ID ${num(t.ea_team_id)}</option>`).join("")}</datalist>
      <datalist id="manualCompetitionNames">${data.references.competitions.map((c) => `<option value="${esc(c.competition_name)}">Object-ID ${num(c.competition_object_id)}</option>`).join("")}</datalist>
      <datalist id="manualLeagueNames">${data.references.leagues.map((l) => `<option value="${esc(l.league_name)}">EA-ID ${num(l.ea_league_id)}</option>`).join("")}</datalist>`;
}
function manualCompetitionSection(data, season, competitions) {
    const editing = state.manualEditKind === "competition" ? competitions.find(c => Number(c.id) === Number(state.manualEditId)) : undefined;
    return `${state.manualEditKind === "competition" ? manualCompetitionForm(season.id, editing) : `<div class="manual-section-actions"><button class="button primary" data-manual-new="competition">Add competition</button></div>`}
      <section class="card"><header class="card-header"><h2>Competitions</h2><span>${manualSourceBadge()}</span></header>${competitions.length ? table([
        { label: "Competition" }, { label: "Type" }, { label: "Position", cls: "center" }, { label: "Result" }, { label: "Actions", sortable: false }
    ], competitions.map(c => `<tr><td><strong>${esc(c.competition_name)}</strong>${manualUpdated(c.updated_at)}</td><td>${statusBadge(c.competition_type)}</td><td class="center">${c.final_position ? `#${num(c.final_position)}` : "–"}</td><td>${esc(c.result_text || "–")}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="competition" data-id="${c.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="competitions" data-id="${c.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No competitions recorded yet.</span></div>`}</section>`;
}
function manualQuickStatsForm(competitions) {
    const selected = Number(state.manualDraftCompetitionId || manualPreferences().competitionId || competitions[0]?.id);
    const rows = Array.from({ length: 6 }, (_, index) => `<fieldset class="manual-quick-stat-row" data-quick-stat-row><legend>Row ${index + 1}</legend>${manualPlayerPicker()}<div class="quick-stat-numbers"><label><span>Apps</span><input name="appearances" type="number" min="0" max="999" value="0"></label><label><span>G</span><input name="goals" type="number" min="0" max="999" value="0"></label><label><span>A</span><input name="assists" type="number" min="0" max="999" value="0"></label><label><span>CS</span><input name="cleanSheets" type="number" min="0" max="999" value="0"></label><label><span>Avg.</span><input name="averageRating" inputmode="decimal" placeholder="7,25"></label></div></fieldset>`).join("");
    return `<section class="card pad manual-editor-card quick-entry-card"><div class="card-title-row"><div><h3 class="card-title">Quick entry</h3><span>Choose a competition and save several players in one pass.</span></div><button type="button" class="button" data-manual-quick-toggle>Close</button></div><form id="manualQuickStatsForm"><label class="quick-entry-competition"><span>Competition for all rows</span><select name="competitionId">${competitions.map(c => `<option value="${c.id}" ${Number(c.id) === selected ? "selected" : ""}>${esc(c.competition_name)}</option>`).join("")}</select></label><div class="manual-quick-stat-grid">${rows}</div><div class="manual-form-actions"><small>Empty rows are skipped · Ctrl+Enter saves all completed rows</small><button type="submit" class="button primary">Save all completed rows</button></div></form></section>`;
}
function manualStatsSection(data, season, competitions, stats) {
    const editing = state.manualEditKind === "stat" ? stats.find(s => Number(s.id) === Number(state.manualEditId)) : undefined;
    const form = competitions.length ? manualStatForm(competitions, editing) : `<div class="card pad"><span class="muted">Create at least one competition first.</span></div>`;
    return `${state.manualQuickEntry && competitions.length ? manualQuickStatsForm(competitions) : state.manualEditKind === "stat" ? form : `<div class="manual-section-actions"><button class="button" data-manual-quick-toggle ${competitions.length ? "" : "disabled"}>Quick entry</button><button class="button primary" data-manual-new="stat" ${competitions.length ? "" : "disabled"}>Add individual statistics</button></div>`}
      <section class="card"><header class="card-header"><h2>Player statistics by competition</h2><span>${manualSourceBadge()}</span></header>${stats.length ? table([
        { label: "Player" }, { label: "Competition" }, { label: "Apps", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "CS", cls: "num" }, { label: "Avg. rating", cls: "num" }, { label: "Actions", sortable: false }
    ], stats.map(s => `<tr><td>${s.player_ea_id ? `<strong>${playerLink(s.player_ea_id, s.display_name)}</strong><small>EA-ID ${num(s.player_ea_id)}</small>` : `<strong>${esc(s.display_name)}</strong><small class="manual-unlinked">not linked</small>`}${manualUpdated(s.updated_at)}</td><td>${esc(s.competition_name)}</td><td class="num">${num(s.appearances)}</td><td class="num">${num(s.goals)}</td><td class="num">${num(s.assists)}</td><td class="num">${num(s.clean_sheets)}</td><td class="num">${ratingValue(s.average_rating, true)}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="stat" data-id="${s.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="stats" data-id="${s.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No player statistics recorded yet.</span></div>`}</section>`;
}
function manualTransactionsSection(season, transactions) {
    const editing = state.manualEditKind === "transaction" ? transactions.find(t => Number(t.id) === Number(state.manualEditId)) : undefined;
    return `${state.manualEditKind === "transaction" ? manualTransactionForm(season.id, editing) : `<div class="manual-section-actions"><button class="button primary" data-manual-new="transaction">Add transfer or loan</button></div>`}
      <section class="card"><header class="card-header"><h2>Transfers and loans</h2><span>${manualSourceBadge()}</span></header>${transactions.length ? table([
        { label: "Player" }, { label: "Type" }, { label: "Direction" }, { label: "From" }, { label: "To" }, { label: "Fee", cls: "num" }, { label: "Date" }, { label: "Actions", sortable: false }
    ], transactions.map(t => `<tr><td><strong>${t.player_ea_id ? playerLink(t.player_ea_id, t.display_name) : esc(t.display_name)}</strong>${t.player_ea_id ? `<small>EA-ID ${num(t.player_ea_id)}</small>` : `<small class="manual-unlinked">not linked</small>`}${manualUpdated(t.updated_at)}</td><td>${statusBadge(t.transaction_type === "loan" ? "Loan" : "Transfer")}</td><td>${statusBadge(t.direction === "incoming" ? "Incoming" : "Outgoing", t.direction === "incoming" ? "good" : "")}</td><td>${esc(t.from_team_name || "–")}</td><td>${esc(t.to_team_name || "–")}</td><td class="num">${t.fee === null || t.fee === undefined ? "–" : money(t.fee)}</td><td>${t.transaction_date ? dateText(t.transaction_date) : "–"}${t.loan_end_date ? `<small>until ${dateText(t.loan_end_date)}</small>` : ""}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="transaction" data-id="${t.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="transactions" data-id="${t.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No transfers or loans recorded yet.</span></div>`}</section>`;
}
function manualLeagueFinishesSection(season, finishes) {
    const editing = state.manualEditKind === "league-finish" ? finishes.find(f => Number(f.id) === Number(state.manualEditId)) : undefined;
    return `${state.manualEditKind === "league-finish" ? manualLeagueFinishForm(season.id, editing) : `<div class="manual-section-actions"><button class="button primary" data-manual-new="league-finish">Add league finish</button></div>`}
      <section class="card"><header class="card-header"><h2>League finishes aller clubs</h2><span>${manualSourceBadge()}</span></header>${finishes.length ? table([
        { label: "Club" }, { label: "League" }, { label: "Position", cls: "center" }, { label: "Source" }, { label: "Actions", sortable: false }
    ], finishes.map(f => `<tr><td><strong>${f.team_ea_id ? clubLink(f.team_ea_id, f.team_name) : esc(f.team_name)}</strong>${manualUpdated(f.updated_at)}</td><td>${esc(f.league_name)}</td><td class="center"><strong>#${num(f.final_position)}</strong></td><td>${statusBadge("Manual", "good")}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="league-finish" data-id="${f.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="league-finishes" data-id="${f.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No league finishes for other clubs recorded yet.</span></div>`}</section>`;
}
function manualChangesSection(data) {
    const labels = { season: "Season", competition: "Competition", player_stat: "Player statistics", transaction: "Transfer/loan", league_finish: "League finish" };
    return `<section class="card"><header class="card-header"><h2>Change log</h2><span>${num(data.changes.length)} entries</span></header>${data.changes.length ? table([
        { label: "Zeit" }, { label: "Aktion" }, { label: "Bereich" }, { label: "Datensatz" }
    ], data.changes.map((c) => `<tr><td>${esc(c.occurred_at)}</td><td>${statusBadge(c.action)}</td><td>${esc(labels[c.entity_type] || c.entity_type)}</td><td class="mono">#${num(c.entity_id)}</td></tr>`)) : `<div class="card-body"><span class="muted">No manual changes yet.</span></div>`}</section>`;
}
async function renderManualData() {
    const data = await api(`/api/careers/${state.careerId}/manual-data`);
    if (!state.manualSeasonId || !data.seasons.some(s => Number(s.id) === Number(state.manualSeasonId)))
        state.manualSeasonId = data.seasons.length ? Number(data.seasons[0].id) : null;
    const season = data.seasons.find(s => Number(s.id) === Number(state.manualSeasonId));
    const competitions = data.competitions.filter(c => Number(c.manual_season_id) === Number(state.manualSeasonId));
    const stats = data.stats.filter(s => Number(s.manual_season_id) === Number(state.manualSeasonId));
    const transactions = data.transactions.filter(t => Number(t.manual_season_id) === Number(state.manualSeasonId));
    const leagueFinishes = data.leagueFinishes.filter(f => Number(f.manual_season_id) === Number(state.manualSeasonId));
    const totals = { seasons: data.seasons.length, competitions: data.competitions.length, stats: data.stats.length, transactions: data.transactions.length, leagueFinishes: data.leagueFinishes.length };
    const seasonEditing = state.manualEditKind === "season" ? data.seasons.find(s => Number(s.id) === Number(state.manualEditId)) : undefined;
    let main = "";
    if (!season)
        main = manualSeasonForm(seasonEditing);
    else if (state.manualEditKind === "season")
        main = manualSeasonForm(state.manualEditId ? seasonEditing : undefined);
    else {
        const tabs = [["competitions", "Competitions"], ["league-finishes", "League finishes"], ["stats", "Player statistics"], ["transactions", "Transfers & loans"], ["changes", "Changes"]];
        let section = manualCompetitionSection(data, season, competitions);
        if (state.manualTab === "league-finishes")
            section = manualLeagueFinishesSection(season, leagueFinishes);
        if (state.manualTab === "stats")
            section = manualStatsSection(data, season, competitions, stats);
        if (state.manualTab === "transactions")
            section = manualTransactionsSection(season, transactions);
        if (state.manualTab === "changes")
            section = manualChangesSection(data);
        const uniquePlayers = new Set(stats.map(s => s.player_ea_id ? `ea:${s.player_ea_id}` : `name:${String(s.display_name).toLowerCase()}`)).size;
        const transfers = transactions.filter(t => t.transaction_type === "transfer").length;
        const loans = transactions.filter(t => t.transaction_type === "loan").length;
        main = `<section class="card manual-season-head"><div><p>HISTORICAL SEASON</p><h2>${esc(manualSeasonTitle(season))}</h2><span>${esc(season.managed_team_name || "Club not specified")}</span></div><div class="row-actions"><button class="button" data-manual-edit="season" data-id="${season.id}">Edit season</button><button class="button danger" data-manual-delete="seasons" data-id="${season.id}">Delete season</button></div></section>
          <div class="grid metrics manual-completeness">${metric("Competitions", num(competitions.length), "recorded")}${metric("Player", num(uniquePlayers), "with statistics", "green")}${metric("Statistic rows", num(stats.length), "player × competition", "blue")}${metric("Transfers / loans", `${transfers} / ${loans}`, "movements", "amber")}${metric("League finishes", num(leagueFinishes.length), "clubs")}</div>
          <div class="tabbar manual-tabs">${tabs.map(([key, label]) => `<button data-manual-tab="${key}" class="${state.manualTab === key ? "active" : ""}">${label}</button>`).join("")}</div>${section}`;
    }
    content.innerHTML = `<div class="content-inner wide">${pageHead("Historical data", "Add old seasons manually without changing imported snapshots", `<button class="button" data-manual-backup>Back up database</button><button class="button primary" data-manual-new="season">New season</button>`)}
      <div class="manual-safety-note card"><strong>Separate data source</strong><span>All entries on this page are marked as manual. Snapshot data remains unchanged.</span><span>${data.backups.length ? `Latest backup: ${esc(data.backups[0].name)}` : "No backup available yet"}</span></div>
      <div class="grid metrics">${metric("Seasons", num(totals.seasons), "maintained manually", "green")}${metric("Competitions", num(totals.competitions), "leagues and cups", "blue")}${metric("Statistic rows", num(totals.stats), "player × competition")}${metric("Movements", num(totals.transactions), "transfers and loans", "amber")}${metric("League finishes", num(totals.leagueFinishes), "clubs")}</div>
      <div class="manual-layout"><aside class="card manual-season-list"><header class="card-header"><h2>Seasons</h2></header><div class="manual-season-buttons">${data.seasons.map(s => `<button data-manual-season="${s.id}" class="${Number(s.id) === Number(state.manualSeasonId) ? "active" : ""}"><strong>${esc(manualSeasonTitle(s))}</strong><span>${esc(s.managed_team_name || "Club unspecified")}</span><small>${num(s.competition_count)} Competitions · ${num(s.stat_count)} statistics · ${num(s.transaction_count)} movements · ${num(s.league_finish_count)} finishes</small></button>`).join("") || `<span class="muted">No historical season yet.</span>`}</div></aside><main class="manual-main">${main}</main></div>${manualDataLists(data)}</div>`;
    bindManualData(data);
}
function formPayload(form) {
    const payload = {};
    new FormData(form).forEach((value, key) => payload[key] = typeof value === "string" ? value.trim() : value);
    return payload;
}
function resolveManualReference(data, kind, name) {
    const needle = name.trim().toLocaleLowerCase("de");
    const rows = kind === "team" ? data.references.teams : kind === "competition" ? data.references.competitions : data.references.leagues;
    const field = kind === "team" ? "team_name" : kind === "competition" ? "competition_name" : "league_name";
    return rows.find((row) => String(row[field] || "").trim().toLocaleLowerCase("de") === needle);
}
async function saveManualForm(entity, form, data, keepOpen = false) {
    const payload = formPayload(form);
    if (entity === "seasons") {
        payload.seasonIndex = Number(payload.seasonNumber) - 1;
        const team = resolveManualReference(data, "team", String(payload.managedTeamName || ""));
        if (team)
            payload.managedTeamEaId = team.ea_team_id;
    }
    if (entity === "competitions") {
        const ref = resolveManualReference(data, "competition", String(payload.competitionName || ""));
        if (ref) {
            payload.competitionObjectId = ref.competition_object_id;
            payload.staticCompetitionId = ref.static_competition_id;
        }
    }
    if (entity === "transactions") {
        const team = resolveManualReference(data, "team", String(payload.counterpartyTeamName || ""));
        if (team && !payload.counterpartyTeamEaId)
            payload.counterpartyTeamEaId = team.ea_team_id;
        saveManualPreferences({
            transactionType: payload.transactionType,
            direction: payload.direction,
            counterpartyTeamName: payload.counterpartyTeamName,
            feeUnknown: Boolean(payload.feeUnknown),
        });
    }
    if (entity === "league-finishes") {
        const team = resolveManualReference(data, "team", String(payload.teamName || ""));
        const league = resolveManualReference(data, "league", String(payload.leagueName || ""));
        if (team && !payload.teamEaId)
            payload.teamEaId = team.ea_team_id;
        if (league && !payload.leagueEaId)
            payload.leagueEaId = league.ea_league_id;
    }
    const saved = await api(`/api/careers/${state.careerId}/manual-data/${entity}/save`, { method: "POST", body: JSON.stringify(payload) });
    if (entity === "seasons")
        state.manualSeasonId = Number(saved.id);
    if (entity === "stats")
        state.manualDraftCompetitionId = Number(payload.competitionId);
    state.manualEditKind = keepOpen && entity === "stats" ? "stat" : keepOpen && entity === "transactions" ? "transaction" : null;
    state.manualEditId = null;
    clearApiCache();
    toast(saved.upsertedExisting ? "Existing record updated" : "Manual data saved");
    await renderManualData();
    applyIcons(content);
    bindContent();
    if (keepOpen)
        $(entity === "stats" ? "#manualStatForm [name='displayName']" : "#manualTransactionForm [name='displayName']", content)?.focus();
    return saved;
}
function bindMovementManualEditor() {
    const form = $("#movementManualForm", content);
    if (!form)
        return;
    bindManualPlayerPicker(form);
    bindUnknownFee(form);
    bindManualKeyboard(form);
    $("[data-movement-editor-cancel]", form)?.addEventListener("click", async () => {
        state.movementEditKind = null;
        state.movementEditId = null;
        if (state.route === "loans")
            await renderLoans();
        else
            await renderTransfers();
        applyIcons(content);
        bindContent();
    });
    form.onsubmit = async (event) => {
        event.preventDefault();
        const payload = formPayload(form);
        const data = await api(`/api/careers/${state.careerId}/manual-data`);
        const team = resolveManualReference(data, "team", String(payload.counterpartyTeamName || ""));
        if (team && !payload.counterpartyTeamEaId)
            payload.counterpartyTeamEaId = team.ea_team_id;
        saveManualPreferences({ direction: payload.direction, counterpartyTeamName: payload.counterpartyTeamName, feeUnknown: Boolean(payload.feeUnknown) });
        await api(`/api/careers/${state.careerId}/manual-data/transactions/save`, { method: "POST", body: JSON.stringify(payload) });
        state.movementEditKind = null;
        state.movementEditId = null;
        clearApiCache();
        toast(payload.transactionType === "loan" ? "Historical loan saved" : "Historical transfer saved");
        if (state.route === "loans")
            await renderLoans();
        else
            await renderTransfers();
        applyIcons(content);
        bindContent();
    };
}
function bindManualPlayerPicker(form) {
    const input = $("[data-manual-player-search]", form);
    const hidden = $("[name='playerEaId']", form);
    const results = $("[data-manual-player-results]", form);
    const selection = $("[data-manual-player-selection]", form);
    if (!input || !hidden || !results || !selection)
        return;
    let timer = 0;
    let request = 0;
    const close = () => { results.hidden = true; results.innerHTML = ""; };
    input.addEventListener("input", () => {
        hidden.value = "";
        selection.textContent = "Custom name – not linked to an EA ID yet.";
        window.clearTimeout(timer);
        const query = input.value.trim();
        if (query.length < 2) {
            close();
            return;
        }
        const currentRequest = ++request;
        timer = window.setTimeout(async () => {
            try {
                const rows = await api(`/api/careers/${state.careerId}/players/search?q=${encodeURIComponent(query)}&limit=40`);
                if (currentRequest !== request)
                    return;
                results.innerHTML = rows.length ? rows.map(row => `<button type="button" data-player-result data-id="${row.ea_player_id ?? ""}" data-name="${esc(row.display_name)}"><strong>${esc(row.display_name)}</strong><span>${row.primary_position ? positionBadge(row.primary_position) : statusBadge("manual")} ${row.overall ? overallBadge(row.overall) : ""}</span><small>${esc(row.team_name || (row.source === "manual" ? "Recorded manually" : "Unknown club"))}${row.ea_player_id ? ` · EA-ID ${num(row.ea_player_id)}` : ""}</small></button>`).join("") : `<span class="muted">No matches. The name can still be saved as entered.</span>`;
                results.hidden = false;
                $$("[data-player-result]", results).forEach(button => button.onclick = () => {
                    input.value = button.dataset.name || "";
                    hidden.value = button.dataset.id || "";
                    selection.textContent = hidden.value ? `Linked to EA ID ${hidden.value}` : "Manually entered player name";
                    close();
                });
            }
            catch (error) {
                close();
            }
        }, 180);
    });
    input.addEventListener("blur", () => window.setTimeout(close, 180));
}
function bindManualData(data) {
    $$("[data-manual-season]", content).forEach(button => button.onclick = async () => { state.manualSeasonId = Number(button.dataset.manualSeason); state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$("[data-manual-tab]", content).forEach(button => button.onclick = async () => { state.manualTab = button.dataset.manualTab || "competitions"; state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$("[data-manual-new]", content).forEach(button => button.onclick = async () => { state.manualEditKind = button.dataset.manualNew || null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$("[data-manual-quick-toggle]", content).forEach(button => button.onclick = async () => { state.manualQuickEntry = !state.manualQuickEntry; state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$("[data-manual-edit]", content).forEach(button => button.onclick = async () => { state.manualEditKind = button.dataset.manualEdit || null; state.manualEditId = Number(button.dataset.id); await renderManualData(); applyIcons(content); bindContent(); });
    $$("[data-manual-cancel]", content).forEach(button => button.onclick = async () => { state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$("[data-manual-delete]", content).forEach(button => button.onclick = async () => {
        const entity = button.dataset.manualDelete || "";
        if (!confirm("Delete this manual record? Related manual entries will also be removed."))
            return;
        try {
            await api(`/api/careers/${state.careerId}/manual-data/${entity}/delete`, { method: "POST", body: JSON.stringify({ id: Number(button.dataset.id) }) });
            if (entity === "seasons" && Number(button.dataset.id) === Number(state.manualSeasonId))
                state.manualSeasonId = null;
            state.manualEditKind = null;
            state.manualEditId = null;
            clearApiCache();
            toast("Manual record deleted");
            await renderManualData();
            applyIcons(content);
            bindContent();
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        }
    });
    $$("[data-manual-backup]", content).forEach(button => button.onclick = async () => {
        try {
            const result = await api("/api/backups/create", { method: "POST", body: JSON.stringify({ label: "manual_history" }) });
            clearApiCache();
            toast(`Backup created: ${result.name}`);
            await renderManualData();
            applyIcons(content);
            bindContent();
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        }
    });
    const seasonForm = $("#manualSeasonForm", content);
    if (seasonForm)
        seasonForm.onsubmit = async (event) => { event.preventDefault(); try {
            await saveManualForm("seasons", seasonForm, data);
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        } };
    const competitionForm = $("#manualCompetitionForm", content);
    if (competitionForm)
        competitionForm.onsubmit = async (event) => { event.preventDefault(); try {
            await saveManualForm("competitions", competitionForm, data);
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        } };
    const statForm = $("#manualStatForm", content);
    if (statForm) {
        bindManualPlayerPicker(statForm);
        $("[name='competitionId']", statForm)?.addEventListener("change", event => state.manualDraftCompetitionId = Number(event.target.value));
        statForm.onsubmit = async (event) => { event.preventDefault(); try {
            await saveManualForm("stats", statForm, data);
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        } };
        $("[data-manual-save-next]", statForm)?.addEventListener("click", async () => { try {
            await saveManualForm("stats", statForm, data, true);
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        } });
    }
    const quickStatsForm = $("#manualQuickStatsForm", content);
    if (quickStatsForm) {
        const competition = $("[name='competitionId']", quickStatsForm);
        $$("[data-quick-stat-row]", quickStatsForm).forEach(row => bindManualPlayerPicker(row));
        competition?.addEventListener("change", () => { state.manualDraftCompetitionId = Number(competition.value); saveManualPreferences({ competitionId: Number(competition.value) }); });
        quickStatsForm.onsubmit = async (event) => {
            event.preventDefault();
            const rows = $$("[data-quick-stat-row]", quickStatsForm);
            const payloads = rows.map(row => ({
                competitionId: Number(competition?.value),
                playerEaId: $("[name='playerEaId']", row)?.value || null,
                displayName: $("[name='displayName']", row)?.value.trim() || "",
                appearances: $("[name='appearances']", row)?.value || "0",
                goals: $("[name='goals']", row)?.value || "0",
                assists: $("[name='assists']", row)?.value || "0",
                cleanSheets: $("[name='cleanSheets']", row)?.value || "0",
                averageRating: $("[name='averageRating']", row)?.value || null,
            })).filter(row => row.displayName);
            if (!payloads.length) {
                toast("Complete at least one player row");
                return;
            }
            try {
                for (const payload of payloads)
                    await api(`/api/careers/${state.careerId}/manual-data/stats/save`, { method: "POST", body: JSON.stringify(payload) });
                state.manualDraftCompetitionId = Number(competition?.value);
                saveManualPreferences({ competitionId: state.manualDraftCompetitionId });
                clearApiCache();
                toast(`${payloads.length} statistics row${payloads.length === 1 ? "" : "n"} saved`);
                await renderManualData();
                applyIcons(content);
                bindContent();
            }
            catch (error) {
                toast(error instanceof Error ? error.message : String(error));
            }
        };
        bindManualKeyboard(quickStatsForm);
    }
    const transactionForm = $("#manualTransactionForm", content);
    if (transactionForm) {
        bindManualPlayerPicker(transactionForm);
        bindUnknownFee(transactionForm);
        transactionForm.onsubmit = async (event) => { event.preventDefault(); try {
            await saveManualForm("transactions", transactionForm, data);
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        } };
        const saveNext = $("[data-manual-save-next]", transactionForm);
        saveNext?.addEventListener("click", async () => { try {
            await saveManualForm("transactions", transactionForm, data, true);
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        } });
        bindManualKeyboard(transactionForm, saveNext);
    }
    const leagueFinishForm = $("#manualLeagueFinishForm", content);
    if (leagueFinishForm)
        leagueFinishForm.onsubmit = async (event) => { event.preventDefault(); try {
            await saveManualForm("league-finishes", leagueFinishForm, data);
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        } };
    [seasonForm, competitionForm, statForm, leagueFinishForm].forEach(form => { if (form)
        bindManualKeyboard(form, $("[data-manual-save-next]", form)); });
}
function playerManualEditor(data, player) {
    const editor = data.manualEditor || { seasons: [], competitions: [], stats: [] };
    if (!editor.seasons.length)
        return `<section class="card pad"><h3 class="card-title">Add historical statistics</h3><p class="muted">Create a season and its competitions under Historical data first.</p><button class="button" data-route="manual-data">Open historical data</button></section>`;
    const usableSeasons = editor.seasons.filter((season) => editor.competitions.some((competition) => Number(competition.manual_season_id) === Number(season.id)));
    if (!usableSeasons.length)
        return `<section class="card pad"><h3 class="card-title">Add historical statistics</h3><p class="muted">The available historical seasons do not have competitions yet.</p><button class="button" data-route="manual-data">Create competitions</button></section>`;
    const prefs = manualPreferences();
    const firstSeason = usableSeasons.find((season) => Number(season.id) === Number(prefs.playerStatSeasonId)) || usableSeasons[0];
    const preferredCompetition = editor.competitions.find((competition) => Number(competition.id) === Number(prefs.competitionId) && Number(competition.manual_season_id) === Number(firstSeason.id));
    return `<section class="card pad manual-editor-card player-manual-editor"><h3 class="card-title">Add statistics directly</h3><p class="muted">The player is already selected. Choose a season and competition, enter values, and save.</p>
      <form id="playerManualStatForm" class="manual-form"><input type="hidden" name="id"><input type="hidden" name="playerEaId" value="${player.ea_player_id}"><input type="hidden" name="displayName" value="${esc(player.display_name)}">
        <div class="manual-form-grid"><label><span>Season</span><select name="seasonId">${usableSeasons.map((s) => `<option value="${s.id}" ${Number(s.id) === Number(firstSeason.id) ? "selected" : ""}>${esc(manualSeasonTitle(s))}</option>`).join("")}</select></label><label><span>Competition</span><select name="competitionId" required>${editor.competitions.filter((c) => Number(c.manual_season_id) === Number(firstSeason.id)).map((c) => `<option value="${c.id}" ${Number(c.id) === Number(preferredCompetition?.id) ? "selected" : ""}>${esc(c.competition_name)}</option>`).join("")}</select></label>
          <label><span>Matches</span><input name="appearances" type="number" min="0" max="999" value="0"></label><label><span>Goals</span><input name="goals" type="number" min="0" max="999" value="0"></label><label><span>Assists</span><input name="assists" type="number" min="0" max="999" value="0"></label><label><span>Clean sheets</span><input name="cleanSheets" type="number" min="0" max="999" value="0"></label><label><span>Avg. rating</span><input name="averageRating" inputmode="decimal" placeholder="7,25"></label><label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="1000"></textarea></label></div>
        <div class="manual-form-actions"><small>The selection is remembered for the next player · Ctrl+Enter saves</small><button type="button" class="button" data-player-stat-reset>Clear</button><button type="submit" class="button primary"><span data-icon="save"></span>Save statistics</button></div></form>
      ${editor.stats.length ? `<div class="player-manual-existing"><h4>Existing manual entries</h4>${table([{ label: "Season" }, { label: "Competition" }, { label: "Apps", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "CS", cls: "num" }, { label: "Avg. rating", cls: "num" }, { label: "Actions", sortable: false }], editor.stats.map((s) => `<tr><td>${esc(s.season_label)}</td><td>${esc(s.competition_name)}</td><td class="num">${num(s.appearances)}</td><td class="num">${num(s.goals)}</td><td class="num">${num(s.assists)}</td><td class="num">${num(s.clean_sheets)}</td><td class="num">${ratingValue(s.average_rating, true)}</td><td><button class="entity-link" data-player-stat-edit="${s.id}">Edit</button> <button class="entity-link danger-link" data-player-stat-delete="${s.id}">Delete</button></td></tr>`))}</div>` : ""}
    </section>`;
}
function bindPlayerManualEditor(data, player) {
    const editor = data.manualEditor || { seasons: [], competitions: [], stats: [] };
    const form = $("#playerManualStatForm", content);
    if (!form)
        return;
    const seasonSelect = $("[name='seasonId']", form);
    const competitionSelect = $("[name='competitionId']", form);
    const fillCompetitions = (seasonId, selectedId) => {
        const rows = editor.competitions.filter((c) => Number(c.manual_season_id) === seasonId);
        competitionSelect.innerHTML = rows.map((c) => `<option value="${c.id}" ${Number(c.id) === Number(selectedId) ? "selected" : ""}>${esc(c.competition_name)}</option>`).join("");
    };
    seasonSelect.onchange = () => { fillCompetitions(Number(seasonSelect.value)); saveManualPreferences({ playerStatSeasonId: Number(seasonSelect.value) }); };
    competitionSelect.onchange = () => saveManualPreferences({ competitionId: Number(competitionSelect.value), playerStatSeasonId: Number(seasonSelect.value) });
    const reset = () => {
        ($("[name='id']", form)).value = "";
        for (const name of ["appearances", "goals", "assists", "cleanSheets"])
            ($(`[name='${name}']`, form)).value = "0";
        ($("[name='averageRating']", form)).value = "";
        ($("[name='notes']", form)).value = "";
    };
    $("[data-player-stat-reset]", form).onclick = reset;
    $$("[data-player-stat-edit]", content).forEach(button => button.onclick = () => {
        const stat = editor.stats.find((s) => Number(s.id) === Number(button.dataset.playerStatEdit));
        if (!stat)
            return;
        ($("[name='id']", form)).value = String(stat.id);
        seasonSelect.value = String(stat.manual_season_id);
        fillCompetitions(Number(stat.manual_season_id), Number(stat.manual_competition_id));
        ($("[name='appearances']", form)).value = String(stat.appearances || 0);
        ($("[name='goals']", form)).value = String(stat.goals || 0);
        ($("[name='assists']", form)).value = String(stat.assists || 0);
        ($("[name='cleanSheets']", form)).value = String(stat.clean_sheets || 0);
        ($("[name='averageRating']", form)).value = stat.average_rating ?? "";
        ($("[name='notes']", form)).value = stat.notes || "";
        form.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $$("[data-player-stat-delete]", content).forEach(button => button.onclick = async () => {
        if (!confirm("Delete this manual statistics record?"))
            return;
        try {
            await api(`/api/careers/${state.careerId}/manual-data/stats/delete`, { method: "POST", body: JSON.stringify({ id: Number(button.dataset.playerStatDelete) }) });
            clearApiCache();
            toast("Statistics deleted");
            await renderPlayer();
            applyIcons(content);
            bindContent();
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        }
    });
    form.onsubmit = async (event) => {
        event.preventDefault();
        try {
            const payload = formPayload(form);
            saveManualPreferences({ competitionId: Number(payload.competitionId), playerStatSeasonId: Number(payload.seasonId) });
            const saved = await api(`/api/careers/${state.careerId}/manual-data/stats/save`, { method: "POST", body: JSON.stringify(payload) });
            clearApiCache();
            toast(saved.upsertedExisting ? "Existing statistics updated" : "Statistics saved");
            await renderPlayer();
            applyIcons(content);
            bindContent();
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        }
    };
    bindManualKeyboard(form);
}
function developmentStageLabel(row) {
    return row.stage_label || { season_start: "Season start", season_mid: "Mid-season", season_end: "Season end", custom: "Custom point" }[row.stage] || "Custom point";
}
function playerDevelopmentEditor(data, player) {
    const editor = data.manualEditor || { seasons: [], development: [] };
    if (!editor.seasons?.length)
        return `<section class="card pad"><h3 class="card-title">Add historical development</h3><p class="muted">No imported or manual season is available for this career yet.</p></section>`;
    const prefs = manualPreferences();
    return `<section class="card pad manual-editor-card player-development-editor"><h3 class="card-title">Add OVR and POT</h3><p class="muted">Imported and manual seasons are available together. The last season and point selection is remembered.</p>
      <form id="playerDevelopmentForm" class="manual-form"><input type="hidden" name="id"><input type="hidden" name="playerEaId" value="${player.ea_player_id}"><input type="hidden" name="displayName" value="${esc(player.display_name)}">
        <div class="manual-form-grid"><label><span>Season</span><select name="seasonSelection">${editor.seasons.map((s) => { const value = s.selection_value || `manual:${s.id}`; return `<option value="${esc(value)}" ${String(value) === String(prefs.developmentSeasonSelection || "") ? "selected" : ""}>${esc(manualSeasonTitle(s))} · ${esc(s.source_label || "Season")}</option>`; }).join("")}</select></label><label><span>Point</span><select name="stage"><option value="season_start" ${prefs.developmentStage === "season_start" ? "selected" : ""}>Season start</option><option value="season_mid" ${prefs.developmentStage === "season_mid" ? "selected" : ""}>Mid-season</option><option value="season_end" ${prefs.developmentStage === "season_end" ? "selected" : ""}>Season end</option><option value="custom" ${prefs.developmentStage === "custom" ? "selected" : ""}>Custom date</option></select></label><label><span>Label</span><input name="stageLabel" maxlength="80" placeholder="e.g. before the winter break"></label><label><span>Effective date</span><input name="effectiveDate" type="date"><small>Optional for standard points.</small></label><label><span>OVR</span><input name="overall" type="number" min="1" max="99" required value="${rawNumber(player.overall)}"></label><label><span>POT</span><input name="potential" type="number" min="1" max="99" required value="${rawNumber(player.potential)}"></label><label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="1000"></textarea></label></div>
        <div class="manual-form-actions"><small>Ctrl+Enter saves</small><button type="button" class="button" data-player-development-reset>Clear</button><button type="submit" class="button primary"><span data-icon="save"></span>Save development</button></div></form>
      ${editor.development?.length ? `<div class="player-manual-existing"><h4>Manual development points</h4>${table([{ label: "Season" }, { label: "Point" }, { label: "Effective date" }, { label: "OVR", cls: "center" }, { label: "POT", cls: "center" }, { label: "Actions", sortable: false }], editor.development.map((row) => `<tr><td>${esc(row.season_label)}</td><td>${esc(developmentStageLabel(row))}</td><td>${dateText(row.effective_date)}</td><td class="center">${overallBadge(row.overall)}</td><td class="center">${overallBadge(row.potential)}</td><td><button class="entity-link" data-player-development-edit="${row.id}">Edit</button> <button class="entity-link danger-link" data-player-development-delete="${row.id}">Delete</button></td></tr>`))}</div>` : ""}
    </section>`;
}
function bindPlayerDevelopmentEditor(data, player) {
    const editor = data.manualEditor || { seasons: [], development: [] };
    const form = $("#playerDevelopmentForm", content);
    if (!form)
        return;
    const stageSelect = $("[name='stage']", form);
    const labelInput = $("[name='stageLabel']", form);
    const dateInput = $("[name='effectiveDate']", form);
    const updateStage = () => {
        const defaults = { season_start: "Season start", season_mid: "Mid-season", season_end: "Season end" };
        if (stageSelect.value !== "custom" && (!labelInput.value || Object.values(defaults).includes(labelInput.value)))
            labelInput.value = defaults[stageSelect.value] || "";
        dateInput.required = stageSelect.value === "custom";
    };
    const seasonSelection = $("[name='seasonSelection']", form);
    stageSelect.onchange = () => { updateStage(); saveManualPreferences({ developmentStage: stageSelect.value }); };
    seasonSelection.onchange = () => saveManualPreferences({ developmentSeasonSelection: seasonSelection.value });
    const reset = () => {
        ($("[name='id']", form)).value = "";
        stageSelect.value = "season_start";
        labelInput.value = "Season start";
        dateInput.value = "";
        ($("[name='overall']", form)).value = String(player.overall || "");
        ($("[name='potential']", form)).value = String(player.potential || "");
        ($("[name='notes']", form)).value = "";
        updateStage();
    };
    updateStage();
    $("[data-player-development-reset]", form).onclick = reset;
    $$("[data-player-development-edit]", content).forEach(button => button.onclick = () => {
        const row = editor.development.find((item) => Number(item.id) === Number(button.dataset.playerDevelopmentEdit));
        if (!row)
            return;
        ($("[name='id']", form)).value = String(row.id);
        ($("[name='seasonSelection']", form)).value = `manual:${row.manual_season_id}`;
        stageSelect.value = row.stage;
        labelInput.value = developmentStageLabel(row);
        dateInput.value = row.effective_date || "";
        ($("[name='overall']", form)).value = String(row.overall);
        ($("[name='potential']", form)).value = String(row.potential);
        ($("[name='notes']", form)).value = row.notes || "";
        updateStage();
        form.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $$("[data-player-development-delete]", content).forEach(button => button.onclick = async () => {
        if (!confirm("Delete this manual development point?"))
            return;
        try {
            await api(`/api/careers/${state.careerId}/manual-data/development/delete`, { method: "POST", body: JSON.stringify({ id: Number(button.dataset.playerDevelopmentDelete) }) });
            clearApiCache();
            toast("Development point deleted");
            await renderPlayer();
            applyIcons(content);
            bindContent();
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        }
    });
    form.onsubmit = async (event) => {
        event.preventDefault();
        try {
            const payload = formPayload(form);
            saveManualPreferences({ developmentStage: payload.stage, developmentSeasonSelection: payload.seasonSelection });
            const saved = await api(`/api/careers/${state.careerId}/manual-data/development/save`, { method: "POST", body: JSON.stringify(payload) });
            clearApiCache();
            toast(saved.upsertedExisting ? "Existing development point updated" : "Development point saved");
            await renderPlayer();
            applyIcons(content);
            bindContent();
        }
        catch (error) {
            toast(error instanceof Error ? error.message : String(error));
        }
    };
    bindManualKeyboard(form);
}
function mediaProgressMarkup(progress) {
    const processing = progress?.processing || {};
    const total = Number(progress?.total || 0);
    const visited = Number(progress?.visited || 0);
    const pct = total ? Math.min(100, Math.round(visited / total * 100)) : (progress?.phase === "complete" ? 100 : 0);
    const ready = Number(processing.ready || 0);
    const pending = Number(processing.pending || 0);
    const active = Number(processing.processing || 0);
    const failed = Number(processing.failed || 0);
    const phaseLabels = { idle: "Ready", indexing: "Indexing files", complete: "Index complete", cancelled: "Index cancelled", failed: "Index error" };
    const phaseLabel = phaseLabels[String(progress?.phase || "idle")] || progress?.phase || "Ready";
    return `<div class="media-progress-head"><div><strong>${esc(phaseLabel)}</strong><small>${progress?.active ? `${num(visited)} / ${num(total)} files · ${num(progress.filesPerSecond, 1)} files/s` : `${num(ready)} prepared · ${num(pending)} pending`}</small></div><div class="page-actions">${progress?.paused ? '<button class="button small" data-media-control="resume">Resume</button>' : '<button class="button small" data-media-control="pause">Pause</button>'}${progress?.active ? '<button class="button small danger" data-media-control="cancel">Cancel index</button>' : ''}</div></div><div class="progress-track"><span style="width:${pct}%"></span></div><div class="media-progress-stats"><span>Index: <b>${num(progress?.indexed || 0)}</b></span><span>Assigned: <b>${num(progress?.assigned || 0)}</b></span><span>Queue: <b>${num(progress?.queue || 0)}</b></span><span>Active: <b>${num(active)}</b></span><span>Ready: <b>${num(ready)}</b></span><span>Errors: <b>${num(failed)}</b></span></div>${progress?.currentFile ? `<small class="mono muted">${esc(progress.currentFile)}</small>` : ''}`;
}
async function refreshMediaProgress() {
    try {
        const progress = await api("/api/media/progress");
        const previousPhase = lastMediaProgressPhase;
        const previousPending = lastMediaPending;
        lastMediaProgressPhase = progress.phase;
        lastMediaPending = Number(progress.processing?.pending || 0) + Number(progress.processing?.processing || 0);
        const panel = $("#mediaProgress", content);
        if (panel) {
            panel.innerHTML = mediaProgressMarkup(progress);
            $$('[data-media-control]', panel).forEach((button) => button.onclick = () => handleAction(`media-${button.dataset.mediaControl}`));
        }
        const indexJustFinished = previousPhase === "indexing" && !progress.active;
        const queueJustFinished = Number(previousPending || 0) > 0 && lastMediaPending === 0;
        if (indexJustFinished || queueJustFinished)
            clearApiCache();
        if ((indexJustFinished || queueJustFinished) && state.route === "media" && !mediaRefreshPending) {
            mediaRefreshPending = true;
            setTimeout(async () => {
                try {
                    await renderMedia();
                    applyIcons(content);
                    bindContent();
                }
                finally {
                    mediaRefreshPending = false;
                }
            }, 80);
        }
        if (!progress.active && Number(progress.queue || 0) === 0 && Number(progress.processing?.processing || 0) === 0) {
            if (mediaProgressTimer !== null)
                clearInterval(mediaProgressTimer);
            mediaProgressTimer = null;
        }
    }
    catch { }
}
function startMediaProgressPolling() {
    if (mediaProgressTimer)
        return;
    refreshMediaProgress();
    mediaProgressTimer = setInterval(refreshMediaProgress, 900);
}
async function renderMedia() {
    const status = await api("/api/media/status");
    const params = new URLSearchParams();
    if (state.mediaStatus !== "all")
        params.set("status", state.mediaStatus);
    if (state.mediaType !== "all")
        params.set("type", state.mediaType);
    params.set("limit", "500");
    const assets = await api(`/api/media/assets?${params.toString()}`);
    const competitionMappings = state.snapshotId ? await api(`/api/media/competition-mappings?snapshotId=${state.snapshotId}`) : { items: [], choices: [] };
    const types = [["players", "Player portraits"], ["club_logos", "Club logos"], ["competition_logos", "Competition logos"], ["trophies", "Trophies"], ["stadiums", "Stadiums"], ["kits", "Kits"], ["auto", "Mixed folder"]];
    const typeOptions = [["all", "All media types"], ["player_portrait", "Player portraits"], ["club_logo", "Club logos"], ["competition_logo", "Competition logos"], ["trophy", "Trophies"], ["stadium", "Stadiums"], ["kit", "Kits"]];
    const statusOptions = [["all", "All statuses"], ["assigned", "Assigned"], ["conflict", "Conflicts"], ["unknown", "Unknown"], ["ignored", "Ignored"], ["error", "Errors"]];
    const progress = status.progress || {};
    const ready = Number(status.processing?.ready || 0), pending = Number(status.processing?.pending || 0);
    content.innerHTML = `<div class="content-inner wide">${pageHead("Media library", "Fast ID index · WebP generated only when needed and in the background", `<button class="button primary" data-action="scan-media">Quick index</button>`)}
      <div class="grid metrics">${metric("Assigned", num(status.counts?.assigned || 0), "immediately after ID scan", "green")}${metric("Prepared", num(ready), "WebP available", "blue")}${metric("Pending", num(pending), "processed in the background", "amber")}${metric("Unknown", num(status.counts?.unknown || 0), "not converted")}${metric("Sources", num(status.sources?.filter((s) => s.enabled).length || 0), `${num(progress.workers || 0)} Worker`, "blue")}</div>
      <section id="mediaProgress" class="card pad media-progress-panel">${mediaProgressMarkup(progress)}</section>
      <section class="card pad"><div class="media-source-head"><div><h3 class="card-title">Media sources</h3><p class="muted">The index scan reads only the file name, ID, size and modification time. Hashing, copying and WebP generation happen later for assigned images, either in the background or when first displayed.</p></div></div><div class="source-picker-grid">${types.map(([key, label]) => `<button class="source-picker" data-media-source="${key}"><span data-icon="folder"></span><strong>${esc(label)}</strong><small>Choose folder</small></button>`).join("")}</div>${status.sources?.length ? `<div class="source-list">${status.sources.map((source) => `<div class="source-row ${source.enabled ? "" : "disabled"}"><div><strong>${esc(source.label)}</strong><small>${esc(source.path)}</small></div><div class="source-stats"><span>${num(source.last_file_count)} files</span><span>${num(source.last_imported_count)} indexed</span><button class="entity-link" data-remove-source="${source.id}">${source.enabled ? "Disable" : "Disabled"}</button></div></div>`).join("")}</div>` : ""}</section>
      ${competitionMappings.items?.length ? `<section class="card pad competition-mapping-panel"><div class="media-source-head"><div><h3 class="card-title">Competition logo mapping</h3><p class="muted">Career object IDs and the IDs in <span class="mono">l&lt;ID&gt;.png</span> are different. Tracker maps leagues automatically from league IDs and participants. Cup mappings can be confirmed here once.</p></div><button class="button" data-action="rebuild-competition-media">Rebuild automatically</button></div><datalist id="competitionMediaIds">${(competitionMappings.choices || []).map((choice) => `<option value="${choice.mediaCompetitionId}">ID ${choice.mediaCompetitionId}</option>`).join("")}</datalist><div class="competition-mapping-list">${competitionMappings.items.map((item) => `<div class="competition-mapping-row ${item.mediaCompetitionId ? "mapped" : "unmapped"}"><div class="competition-mapping-logo">${item.logo?.url ? `<img src="${esc(item.logo.url)}" alt="">` : `<span data-icon="trophy"></span>`}</div><div class="competition-mapping-copy"><strong>${esc(item.competitionName)}</strong><small>Career ID ${num(item.competitionObjectId)}${item.mappingSource ? ` · ${esc(item.mappingSource)} · ${Math.round(Number(item.mappingConfidence || 0) * 100)} %` : " · unassigned"}</small></div><input class="filter-input mono" list="competitionMediaIds" data-competition-media-id="${item.competitionObjectId}" value="${item.mediaCompetitionId || ""}" placeholder="Logo-ID"><button class="button small" data-save-competition-media="${item.competitionObjectId}">Save</button></div>`).join("")}</div></section>` : ""}
      <div class="filter-row"><select id="mediaType" class="filter-select">${typeOptions.map(([key, label]) => `<option value="${key}" ${state.mediaType === key ? "selected" : ""}>${label}</option>`).join("")}</select><select id="mediaStatus" class="filter-select">${statusOptions.map(([key, label]) => `<option value="${key}" ${state.mediaStatus === key ? "selected" : ""}>${label}</option>`).join("")}</select><span class="chip">${num(assets.length)} media assets</span></div>
      ${assets.length ? `<div class="media-grid">${assets.map((asset) => `<article class="media-card card status-${esc(asset.status)}"><div class="media-preview">${asset.thumbUrl ? `<img src="${esc(asset.thumbUrl)}" alt="${esc(asset.original_name)}" loading="lazy">` : `<span data-icon="media"></span>`}</div><div class="media-card-copy"><div class="media-card-title"><strong>${esc(asset.original_name)}</strong>${statusBadge(asset.status, asset.status === "assigned" ? "good" : asset.status === "error" ? "bad" : asset.status === "conflict" ? "warn" : "")}</div><small>${esc(asset.media_type)} · ${asset.entity_type ? `${esc(asset.entity_type)} ${num(asset.ea_id)}` : "unassigned"}${asset.season_start ? ` · Season ${num(asset.season_start)}` : ""}${asset.variant ? ` · ${esc(asset.variant)}` : ""}</small><small>${asset.processing_state === "ready" ? `${num(asset.width)} × ${num(asset.height)} px · WebP ready` : asset.status === "assigned" ? `Processing: ${esc(asset.processing_state || "pending")}` : esc(asset.source_type || "")}</small>${asset.warning || asset.ignored_reason ? `<p>${esc(asset.warning || asset.ignored_reason)}</p>` : ""}${["conflict", "unknown"].includes(asset.status) ? `<div class="media-assign"><select data-assign-type="${asset.id}"><option value="club">Club</option><option value="competition">Competition</option><option value="player">Player</option><option value="stadium">Stadium</option></select><input data-assign-id="${asset.id}" inputmode="numeric" placeholder="EA-ID" value="${asset.ea_id || ""}"><button class="button small" data-assign-asset="${asset.id}">Assign</button></div>` : ""}</div></article>`).join("")}</div>` : emptyState("No media in this view", "Add sources, start the quick index, or adjust the filters.")}
    </div>`;
    $("#mediaType", content).onchange = (e) => { state.mediaType = e.target.value; renderMedia().then(() => { applyIcons(content); bindContent(); }); };
    $("#mediaStatus", content).onchange = (e) => { state.mediaStatus = e.target.value; renderMedia().then(() => { applyIcons(content); bindContent(); }); };
    $$('[data-media-control]', content).forEach((button) => button.onclick = () => handleAction(`media-${button.dataset.mediaControl}`));
    if (progress.active || Number(progress.queue || 0) > 0 || Number(progress.processing?.processing || 0) > 0)
        startMediaProgressPolling();
}
async function renderSetup() {
    const [reference, media, workspaces] = await Promise.all([
        api("/api/reference/status"),
        api("/api/media/status"),
        api("/api/workspaces"),
    ]);
    const latest = reference.latest || {};
    const workspaceRows = (workspaces.workspaces || []).map((workspace) => {
        const isCurrent = Boolean(workspace.isCurrent);
        const isBranch = ["branch", "sandbox"].includes(String(workspace.kind || ""));
        const archived = Boolean(workspace.archived);
        const badge = isCurrent ? statusBadge("ACTIVE", "good") : isBranch ? statusBadge("BRANCH", "warning") : statusBadge("CAREER", "neutral");
        const pending = workspace.pendingCareerBinding || null;
        const origin = pending?.origin || {};
        const binding = pending
            ? `Assignment awaiting confirmation · ${esc(String(origin.managerDisplayName || "Unknown manager"))} · ${esc(String(origin.initialTeamName || origin.initialTeamId || "Unknown starting club"))}`
            : workspace.careerFingerprint
                ? `Bound · ${esc(String(workspace.careerFingerprint))}`
                : "Not bound yet · confirm the first detected full snapshot";
        const emptyDelete = !isCurrent && !isBranch && Number(workspace.careerCount || 0) === 0
            ? `<button class="button small danger" data-workspace-delete="${esc(workspace.id)}" data-workspace-name="${esc(workspace.name || "Career")}">Delete empty profile</button>`
            : "";
        const pendingActions = isCurrent && pending
            ? `<button class="button small primary" data-workspace-bind-approve="${esc(workspace.id)}">Assign career</button><button class="button small" data-workspace-bind-cancel="${esc(workspace.id)}">Discard</button>`
            : "";
        const actions = isCurrent
            ? `${pendingActions}<span class="muted">Open</span>`
            : archived
                ? `<button class="button small" data-workspace-restore="${esc(workspace.id)}" data-workspace-name="${esc(workspace.name || "Career")}">Restore</button>`
                : `<button class="button small" data-workspace-activate="${esc(workspace.id)}">Open</button><button class="button small" data-workspace-archive="${esc(workspace.id)}" data-workspace-name="${esc(workspace.name || "Career")}">Archive</button>${isBranch ? `<button class="button small danger" data-workspace-delete="${esc(workspace.id)}" data-workspace-name="${esc(workspace.name || "Branch")}">Delete</button>` : emptyDelete}`;
        return `<div class="workspace-row ${isCurrent ? "current" : ""} ${isBranch ? "sandbox" : ""}" style="${archived ? "opacity:.58" : ""}"><div class="workspace-copy"><strong>${badge}<span>${esc(workspace.name || workspace.id)}</span></strong><small>${num(workspace.careerCount || 0)} careers · ${num(workspace.snapshotCount || 0)} snapshots</small><small>${binding}</small><small>${esc(workspace.snapshotRoot || "No dedicated export root")}</small></div><div class="workspace-actions">${actions}</div></div>`;
    }).join("");
    const workspacePanel = `<section id="workspace-section" class="card pad"><div class="card-title-row"><div><h3 class="card-title">Career saves</h3><p class="muted">Each FC26 career uses an isolated Tracker workspace. The first full snapshot must be confirmed before it is assigned.</p></div></div><div class="workspace-panel">${workspaceRows || '<div class="muted">No career saves found.</div>'}</div><form class="workspace-create" data-workspace-create-form><input class="filter-input" name="name" placeholder="New career, e.g. Valencia CF" maxlength="80" required><button class="button primary" type="submit">Create career</button></form><form class="workspace-create" data-workspace-clone-form><input class="filter-input" name="name" placeholder="Branch name" maxlength="80" required><button class="button" type="submit">Clone current state</button></form></section>`;
    content.innerHTML = `<div class="content-inner">${pageHead("Setup", "Snapshot folders, career saves, reference data and media", '<button class="button" data-route="media">Media library</button>')}${workspacePanel}<div class="grid two-col" style="margin-top:14px">
      <section class="card pad"><h3 class="card-title">Snapshot root</h3><p class="muted">The bundled community LUA exporters write to Documents\\FC26 Export\\Snapshots. Tracker watches that path automatically. Change this only to import a legacy or custom export folder; the bundled LUAs will continue writing to their fixed default path.</p><input id="rootPath" class="filter-input" style="width:100%;margin:12px 0" value="${esc(state.status?.snapshotRoot || "")}" placeholder="C:\\Users\\you\\Documents\\FC26 Export\\Snapshots"><div class="page-actions"><button class="button" data-action="pick-folder">Choose folder</button><button class="button primary" data-action="save-root">Save</button></div></section>
      <section class="card pad"><h3 class="card-title">EA FC reference data</h3><p class="muted">Club, competition, kit and stadium references. A verified baseline is included.</p><div class="list"><div class="list-row"><div class="list-main"><strong>${esc(latest.source_label || "Built-in reference")}</strong><small>${latest.is_builtin ? "included baseline" : "imported Main DB"}</small></div>${statusBadge(`${num(reference.counts?.teams)} teams`, "good")}</div><div class="list-row"><div class="list-main"><strong>Competitions / leagues / kits</strong></div><b>${num(reference.counts?.competitions)} / ${num(reference.counts?.leagues)} / ${num(reference.counts?.kits)}</b></div></div><button class="button" data-action="import-main-db">Import a newer Main DB</button></section>
      <section class="card pad"><h3 class="card-title">Media status</h3><div class="list"><div class="list-row"><div class="list-main"><strong>Sources</strong></div><b>${num(media.sources?.filter((s) => s.enabled).length)}</b></div><div class="list-row"><div class="list-main"><strong>Assigned assets</strong></div><b>${num(media.counts?.assigned || 0)}</b></div><div class="list-row"><div class="list-main"><strong>Conflicts / unknown</strong></div><b>${num((media.counts?.conflict || 0) + (media.counts?.unknown || 0))}</b></div></div><div class="page-actions"><button class="button" data-route="media">Manage sources</button><button class="button primary" data-action="scan-media">Scan media</button></div></section>
      <section class="card pad"><h3 class="card-title">${tr("setupLanguage")}</h3><p class="muted">${tr("setupLanguageHelp")}</p><label class="page-filter"><span>${tr("setupLanguage")}</span><select data-atlas-language><option value="pt-BR" ${state.status?.settings?.language === "pt-BR" ? "selected" : ""}>Português (Brasil)</option><option value="en-GB" ${state.status?.settings?.language === "en-GB" ? "selected" : ""}>English (UK)</option><option value="es-ES" ${state.status?.settings?.language === "es-ES" ? "selected" : ""}>Español</option></select></label><div class="page-actions"><button class="button primary" data-save-atlas-language>${tr("saveLanguage")}</button></div></section>
      <section class="card pad"><h3 class="card-title">Visibility</h3><p class="muted">This filter applies across search, views and world simulation. Imported snapshot data is never changed.</p><label class="setting-toggle"><input type="checkbox" data-hide-womens-football ${state.status?.settings?.hideWomensFootball ? "checked" : ""}><span><strong>Hide women’s football</strong><small>Hide women’s competitions, teams and players from Tracker views.</small></span></label></section>
      <section class="card pad"><h3 class="card-title">System status</h3><div class="list"><div class="list-row"><div class="list-main"><strong>Database</strong></div><span class="mono muted">${esc(state.status?.databasePath || "–")}</span></div><div class="list-row"><div class="list-main"><strong>App data</strong></div><span class="mono muted">${esc(state.status?.appDataPath || "–")}</span></div><div class="list-row"><div class="list-main"><strong>Ready snapshots</strong></div><b>${num(state.status?.readyCount)}</b></div><div class="list-row"><div class="list-main"><strong>Last import</strong></div><b>${esc(state.status?.lastImportAt || "–")}</b></div></div></section>
    </div></div>`;
}
function applyClubAliasLocally(teamId, displayName) {
    const patch = (item, idKey, nameKey) => { if (Number(item?.[idKey]) === teamId)
        item[nameKey] = displayName; };
    state.careers.forEach((career) => { patch(career, "initial_team_ea_id", "initial_team_name"); patch(career.latestSnapshot, "managed_team_ea_id", "managed_team_name"); });
    state.snapshots.forEach((snapshot) => patch(snapshot, "managed_team_ea_id", "managed_team_name"));
}
function commissionReportMarkup(result, params) {
    const report = result.report || {}, catalog = new Map((result.fact_catalog || []).map((item) => [item.id, item.label]));
    const refs = (ids) => esc((ids || []).map((id) => catalog.get(id) || id).join(" · "));
    const kindLabel = (kind) => kind === "fact" ? tr("claimFact") : kind === "hypothesis" ? tr("claimHypothesis") : tr("claimInference");
    const items = (values) => values?.length ? `<ul>${values.map((item) => `<li><span class="commission-claim-kind ${esc(item.kind || "inference")}">${esc(kindLabel(item.kind))}</span> ${esc(item.text)}${item.kind === "hypothesis" && item.limitations ? `<small class="commission-claim-limit">${tr("claimLimit")}: ${esc(item.limitations)}</small>` : ""}<small class="table-subline">Evidence: ${refs(item.fact_refs)}</small></li>`).join("")}</ul>` : "";
    const list = (values, label) => values?.length ? `<h4>${label}</h4>${items(values)}` : "";
    const note = report.commission_note?.text ? `<p class="commission-note"><strong>${tr("commissionNote")}:</strong> ${esc(report.commission_note.text)}<small>${refs(report.commission_note.fact_refs)}</small></p>` : "";
    const summaryKind = report.summary?.kind || "inference";
    const provenance = `<details class="report-provenance"><summary>Evidence coverage and validation</summary><small>${num(result.coverage?.previous_linked_matches)} prior linked matches · ${num(result.validation?.accepted_claims)} claims kept · ${num(result.validation?.rejected_claims)} filtered · ${esc(result.validation?.interpretation_quality || tr("interpretationNotScored"))}</small></details>`;
    const coachContext = (result.fact_catalog || []).find((item) => item.id === "coach_context")?.value || [];
    const followup = commissionFollowupForm(report.information_requests, { ...params, model: result.model, coach_context: coachContext });
    const coachNote = result.coach_context_received ? `<p class="chart-note">Coach-provided context was sent separately from imported Atlas facts.</p>` : "";
    return `<div class="commission-report-head"><strong>${esc(report.summary?.text || "Report generated.")}</strong><small><span class="commission-claim-kind ${esc(summaryKind)}">${esc(kindLabel(summaryKind))}</span> · ${esc(result.model || "Ollama")}${result.cached ? " · cached report" : " · generated now"}<br>Atlas facts: ${refs(report.summary?.fact_refs)}</small></div>${report.summary?.limitations ? `<p class="commission-claim-limit">${tr("claimLimit")}: ${esc(report.summary.limitations)}</p>` : ""}${note}${report.formation ? `<section class="commission-formation"><span>Suggested formation · based on Atlas squad data</span><strong>${esc(report.formation.shape)}</strong><p>${esc(report.formation.reason)}</p><small>Evidence: ${refs(report.formation.fact_refs)}</small></section>` : ""}${list(report.strengths, "Strengths")}${list(report.development_areas, "Development areas")}${list(report.training_suggestions, "Training suggestions")}${list(report.observations, "Observed performance")}${list(report.recommendations, "Staff recommendations")}${coachNote}${followup}${provenance}<p class="chart-note">AI interpretation is separate from imported facts. Atlas does not record injury, suspension or physical availability; this report cannot confirm them.</p>`;
}
async function submitCommissionFollowup(form) {
    const output = form.closest("[data-commission-report-output]");
    const questions = Array.from(form.querySelectorAll('input[name="question"]'));
    const answers = Array.from(form.querySelectorAll('textarea[name="answer"]'));
    const priorQuestions = Array.from(form.querySelectorAll('input[name="prior_question"]'));
    const priorAnswers = Array.from(form.querySelectorAll('input[name="prior_answer"]'));
    const prior = priorQuestions.map((question, index) => ({ question: question.value, answer: String(priorAnswers[index]?.value || "").trim() })).filter(item => item.answer);
    const clarifications = [...prior, ...questions.map((question, index) => ({ question: question.value, answer: String(answers[index]?.value || "").trim() })).filter(item => item.answer)];
    if (!clarifications.length) {
        toast("Answer at least one question.");
        return;
    }
    const button = form.querySelector('button[type="submit"]');
    if (button)
        button.disabled = true;
    if (output)
        output.innerHTML = `<p>${esc(tr("contextSent"))}</p>`;
    const payload = { snapshot_id: Number(form.dataset.snapshotId || state.snapshotId), mode: String(form.dataset.mode || "match"), force_refresh: true, model: String(form.dataset.model || "") || undefined, clarifications };
    if (Number(form.dataset.fixtureId || 0))
        payload.fixture_id = Number(form.dataset.fixtureId);
    if (Number(form.dataset.playerEaId || 0))
        payload.player_ea_id = Number(form.dataset.playerEaId);
    try {
        const started = await api(`/api/careers/${state.careerId}/commission/report-jobs`, { method: "POST", body: JSON.stringify(payload) });
        let job = { status: started.status }, attempt = 0;
        while (job.status === "queued" || job.status === "running") {
            await new Promise(resolve => setTimeout(resolve, 1500));
            job = await api(`/api/careers/${state.careerId}/commission/report-jobs/${started.job_id}`);
            if (++attempt > 240)
                throw new Error("The follow-up is taking longer than expected; refresh the saved report later.");
        }
        if (job.status === "failed")
            throw new Error(job.error || "The follow-up failed.");
        const result = job.result || {};
        if (output)
            output.innerHTML = result.available ? commissionReportMarkup(result, payload) : `<p>${esc(result.message || "Ollama report unavailable.")}</p>`;
    }
    catch (error) {
        if (output)
            output.innerHTML = `<p class="status-badge amber">${esc(String(error?.message || error))}</p>`;
    }
    finally {
        if (button)
            button.disabled = false;
    }
}
function bindContent() {
    if (!content.__commissionFollowupBound) {
        content.addEventListener("submit", (event) => {
            const form = event.target;
            if (!form.matches("[data-commission-followup]"))
                return;
            event.preventDefault();
            void submitCommissionFollowup(form);
        });
        content.__commissionFollowupBound = true;
    }
    bindSortableTables();
    $$('[data-club-tab]', content).forEach((button) => button.onclick = async (event) => { event.preventDefault(); state.clubTab = button.dataset.clubTab || "overview"; await renderClub(); applyIcons(content); bindContent(); });
    $$('[data-competition-list-tab]', content).forEach((button) => button.onclick = async (event) => { event.preventDefault(); state.competitionListTab = button.dataset.competitionListTab || "deeper"; await renderCompetitions(); applyIcons(content); bindContent(); });
    const womensToggle = $('[data-hide-womens-football]', content);
    if (womensToggle)
        womensToggle.onchange = async () => { const settings = await api('/api/settings', { method: 'POST', body: JSON.stringify({ hideWomensFootball: womensToggle.checked }) }); if (state.status)
            state.status.settings = settings; clearApiCache(); toast(womensToggle.checked ? 'Women’s football is hidden' : 'Women’s football is visible'); await render(); };
    const languageSave = $('[data-save-atlas-language]', content);
    if (languageSave)
        languageSave.onclick = async () => { const language = $('[data-atlas-language]', content)?.value || 'pt-BR'; const settings = await api('/api/settings', { method: 'POST', body: JSON.stringify({ language }) }); if (state.status)
            state.status.settings = settings; clearApiCache(); updateSystemUi(); toast(tr('languageSaved')); await render(); applyIcons(content); bindContent(); };
    const refreshSetup = async () => { await renderSetup(); applyIcons(content); bindContent(); };
    const workspaceCreateForm = $('[data-workspace-create-form]', content);
    if (workspaceCreateForm)
        workspaceCreateForm.onsubmit = async (event) => { event.preventDefault(); const name = String(new FormData(workspaceCreateForm).get('name') || '').trim(); if (!name)
            return; await api('/api/workspaces/create', { method: 'POST', body: JSON.stringify({ name }) }); toast(`Career save “${name}” created`); await refreshSetup(); };
    const workspaceCloneForm = $('[data-workspace-clone-form]', content);
    if (workspaceCloneForm)
        workspaceCloneForm.onsubmit = async (event) => { event.preventDefault(); const name = String(new FormData(workspaceCloneForm).get('name') || '').trim(); if (!name)
            return; await api('/api/workspaces/clone', { method: 'POST', body: JSON.stringify({ name }) }); toast(`Branch “${name}” created`); await refreshSetup(); };
    $$('[data-workspace-activate]', content).forEach(button => button.onclick = async () => { const workspaceId = String(button.dataset.workspaceActivate || ''); if (!workspaceId || !confirm('Switch to this career save? Project Atlas Tracker will close cleanly and use it on the next start.'))
        return; toast('Switching career save'); await api('/api/workspaces/activate', { method: 'POST', body: JSON.stringify({ workspaceId, restart: true }) }); });
    $$('[data-workspace-bind-approve]', content).forEach(button => button.onclick = async () => { const workspaceId = String(button.dataset.workspaceBindApprove || ''); if (!workspaceId || !confirm('Assign the detected FC26 career to this career save?'))
        return; const result = await api('/api/workspaces/binding/approve', { method: 'POST', body: JSON.stringify({ workspaceId }) }); clearApiCache(); await refreshCareerBootstrap(false); const imported = Array.isArray(result?.imports) && result.imports.some((item) => ['imported', 'duplicate'].includes(String(item?.status || ''))); if (state.careerId && state.snapshotId) {
        toast(imported ? 'Career assigned · snapshot imported' : 'Career assigned');
        navigate('overview');
    }
    else {
        toast('Assignment saved · import still needs attention');
        await refreshSetup();
    } });
    $$('[data-workspace-bind-cancel]', content).forEach(button => button.onclick = async () => { await api('/api/workspaces/binding/cancel', { method: 'POST', body: JSON.stringify({ workspaceId: String(button.dataset.workspaceBindCancel || '') }) }); toast('Detected assignment discarded'); await refreshSetup(); });
    $$('[data-workspace-archive]', content).forEach(button => button.onclick = async () => { const workspaceId = String(button.dataset.workspaceArchive || ''), name = String(button.dataset.workspaceName || 'Career'); if (!workspaceId || !confirm(`Archive “${name}”? Its data will be retained.`))
        return; await api('/api/workspaces/archive', { method: 'POST', body: JSON.stringify({ workspaceId, archived: true }) }); toast(`“${name}” archived`); await refreshSetup(); });
    $$('[data-workspace-restore]', content).forEach(button => button.onclick = async () => { const workspaceId = String(button.dataset.workspaceRestore || ''), name = String(button.dataset.workspaceName || 'Career'); await api('/api/workspaces/archive', { method: 'POST', body: JSON.stringify({ workspaceId, archived: false }) }); toast(`“${name}” restored`); await refreshSetup(); });
    $$('[data-workspace-delete]', content).forEach(button => button.onclick = async () => { const workspaceId = String(button.dataset.workspaceDelete || ''), name = String(button.dataset.workspaceName || 'Branch'); if (!workspaceId || !confirm(`Permanently delete branch “${name}”? The source career save is not affected.`))
        return; await api('/api/workspaces/delete', { method: 'POST', body: JSON.stringify({ workspaceId }) }); toast(`“${name}” deleted`); await refreshSetup(); });
    $$('[data-route]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate(n.dataset.route); });
    $$('[data-player]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate('player', { id: Number(n.dataset.player), tab: 'overview' }); });
    $$('[data-club]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate('club', { id: Number(n.dataset.club) }); });
    $$('[data-competition]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate('competition', { id: Number(n.dataset.competition), tab: state.competitionTab || 'results' }); });
    $$('[data-world-competition]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate('world-competition', { id: Number(n.dataset.worldCompetition) }); });
    $$('[data-match]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate('match', { id: Number(n.dataset.match) }); });
    $$('[data-player-tab]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate('player', { ...state.routeData, tab: n.dataset.playerTab }, true); });
    $$('[data-player-comparison-scope]', content).forEach((n) => n.onclick = async (e) => { e.stopPropagation(); state.playerComparisonScope = n.dataset.playerComparisonScope === 'league' ? 'league' : 'club'; await renderPlayer(); applyIcons(content); bindContent(); });
    $$('[data-player-comparison-mode]', content).forEach(select => select.onchange = async () => { state.playerComparisonMode = select.value === 'position' ? 'position' : 'group'; await renderPlayer(); applyIcons(content); bindContent(); });
    $$('[data-competition-tab]', content).forEach((n) => n.onclick = (e) => { e.stopPropagation(); navigate('competition', { ...state.routeData, tab: n.dataset.competitionTab }, true); });
    $$('[data-loan-scope]', content).forEach((n) => n.onclick = async (e) => { e.stopPropagation(); state.loanScope = n.dataset.loanScope || 'club'; await renderLoans(); applyIcons(content); bindContent(); });
    $$('[data-movement-season]', content).forEach(select => select.onchange = async () => { state.movementSeasonIndex = Number(select.value); state.movementEditId = null; clearApiCache(); if (state.route === 'loans')
        await renderLoans();
    else
        await renderTransfers(); applyIcons(content); bindContent(); });
    $$('[data-movement-editor-open]', content).forEach(button => button.onclick = async () => { state.movementEditKind = button.dataset.movementEditorOpen === 'loan' ? 'loan' : 'transfer'; state.movementEditId = null; if (state.route === 'loans')
        await renderLoans();
    else
        await renderTransfers(); applyIcons(content); bindContent(); });
    $$('[data-movement-editor-edit]', content).forEach(button => button.onclick = async () => { state.movementEditKind = button.dataset.movementEditorEdit === 'loan' ? 'loan' : 'transfer'; state.movementEditId = Number(button.dataset.id); if (state.route === 'loans')
        await renderLoans();
    else
        await renderTransfers(); applyIcons(content); bindContent(); });
    $$('[data-movement-editor-delete]', content).forEach(button => button.onclick = async () => { if (!confirm('Delete this manual history entry?'))
        return; await api(`/api/careers/${state.careerId}/manual-data/transactions/delete`, { method: 'POST', body: JSON.stringify({ id: Number(button.dataset.id) }) }); state.movementEditKind = null; state.movementEditId = null; clearApiCache(); toast('Manual history entry deleted'); if (state.route === 'loans')
        await renderLoans();
    else
        await renderTransfers(); applyIcons(content); bindContent(); });
    $$('[data-analysis-season]', content).forEach(select => select.onchange = async () => { state.analysisSeasonIndex = Number(select.value); clearApiCache(); await renderAnalysis(); applyIcons(content); bindContent(); });
    $$('[data-records-season]', content).forEach(select => select.onchange = async () => { state.recordsSeasonIndex = Number(select.value); clearApiCache(); await renderRecords(); applyIcons(content); bindContent(); });
    $$('[data-season-report-season]', content).forEach(select => select.onchange = async () => { state.seasonReportSeasonIndex = Number(select.value); clearApiCache(); await renderSeasonReport(); applyIcons(content); bindContent(); });
    $$('[data-season-report-tab]', content).forEach((n) => n.onclick = async (e) => { e.stopPropagation(); state.seasonReportTab = n.dataset.seasonReportTab || 'overview'; await renderSeasonReport(); applyIcons(content); bindContent(); });
    const awardPlayerSelect = $('[data-season-award-player]', content);
    if (awardPlayerSelect)
        awardPlayerSelect.onchange = () => { const option = awardPlayerSelect.selectedOptions[0], name = $('[data-season-award-name]', content); if (name && option?.dataset.name)
            name.value = option.dataset.name; };
    const awardForm = $('[data-season-award-form]', content);
    if (awardForm)
        awardForm.onsubmit = async (event) => { event.preventDefault(); const fd = new FormData(awardForm); await api(`/api/careers/${state.careerId}/manual-data/awards/save`, { method: 'POST', body: JSON.stringify({ id: fd.get('id') || null, seasonIndex: state.seasonReportSeasonIndex, awardKey: fd.get('awardKey'), awardLabel: fd.get('awardLabel'), playerEaId: fd.get('playerEaId') || null, displayName: fd.get('displayName'), relatedTransactionId: fd.get('relatedTransactionId') || null, reason: fd.get('reason') }) }); clearApiCache(); toast('Season award saved'); await renderSeasonReport(); applyIcons(content); bindContent(); };
    $$('[data-season-award-delete]', content).forEach(button => button.onclick = async () => { if (!confirm('Delete this manager award?'))
        return; await api(`/api/careers/${state.careerId}/manual-data/awards/delete`, { method: 'POST', body: JSON.stringify({ id: Number(button.dataset.seasonAwardDelete) }) }); clearApiCache(); toast('Season award deleted'); await renderSeasonReport(); applyIcons(content); bindContent(); });
    const reportNoteForm = $('[data-season-report-note-form]', content);
    if (reportNoteForm)
        reportNoteForm.onsubmit = async (event) => { event.preventDefault(); const fd = new FormData(reportNoteForm); await api(`/api/careers/${state.careerId}/manual-data/season-report/save`, { method: 'POST', body: JSON.stringify({ seasonIndex: state.seasonReportSeasonIndex, summaryNote: fd.get('summaryNote') }) }); clearApiCache(); toast('Season note saved'); await renderSeasonReport(); applyIcons(content); bindContent(); };
    $$('[data-season-report-print]', content).forEach(button => button.onclick = () => window.print());
    $$('[data-season-report-csv]', content).forEach(button => button.onclick = () => exportSeasonReportCsv());
    $$('[data-season-report-image]', content).forEach(button => button.onclick = () => exportSeasonInfographic(button.dataset.seasonReportImage === 'square' ? 'square' : 'portrait'));
    const clubNameForm = $('[data-club-name-form]', content);
    if (clubNameForm)
        clubNameForm.onsubmit = async (event) => { event.preventDefault(); const fd = new FormData(clubNameForm), teamId = Number(fd.get('eaTeamId')), displayName = String(fd.get('displayName') || '').trim(); await api(`/api/careers/${state.careerId}/club-names/save`, { method: 'POST', body: JSON.stringify({ eaTeamId: teamId, displayName, note: fd.get('note') }) }); clearApiCache(); applyClubAliasLocally(teamId, displayName); state.careers = await api('/api/careers'); await loadSnapshots(true); fillSelectors(); updateSystemUi(); toast(`Club name applied: ${displayName}`); await renderClub(); applyIcons(content); bindContent(); };
    $$('[data-club-name-reset]', content).forEach(button => button.onclick = async () => { if (!confirm('Remove the custom club name?'))
        return; const teamId = Number(button.dataset.clubNameReset); await api(`/api/careers/${state.careerId}/club-names/delete`, { method: 'POST', body: JSON.stringify({ eaTeamId: teamId }) }); clearApiCache(); state.careers = await api('/api/careers'); await loadSnapshots(true); fillSelectors(); updateSystemUi(); toast('Snapshot club name restored'); await renderClub(); applyIcons(content); bindContent(); });
    const resetCareerButton = $('[data-reset-career]', content);
    if (resetCareerButton)
        resetCareerButton.onclick = async () => {
            const targetSelect = $('[data-reset-target]', content);
            const deleteFiles = $('[data-reset-delete-files]', content);
            const targetId = Number(targetSelect?.value || 0);
            const target = state.snapshots.find((item) => Number(item.id) === targetId);
            if (!targetId || !target)
                return;
            const mode = deleteFiles?.checked ? 'permanently delete' : 'archive';
            const warning = `Reset this career to ${dateText(target.career_date)} (Snapshot #${num(target.import_sequence)})?\n\nAll later snapshots, MatchStats, transfer pulses and derived career state will be removed. Raw export folders will be ${mode}d. A database backup is created first.`;
            if (!confirm(warning))
                return;
            resetCareerButton.disabled = true;
            resetCareerButton.textContent = 'Resetting…';
            try {
                const result = await api(`/api/careers/${state.careerId}/reset`, { method: 'POST', body: JSON.stringify({ snapshotId: targetId, deleteRawFiles: Boolean(deleteFiles?.checked) }) });
                clearApiCache();
                state.snapshotId = targetId;
                await refreshCareerBootstrap(true);
                fillSelectors();
                updateSystemUi();
                toast(`Career reset · ${num(result.removedSnapshots)} later snapshot${Number(result.removedSnapshots) === 1 ? '' : 's'} removed`);
                await render();
            }
            catch (error) {
                const message = String(error?.message || error || 'Unknown reset error');
                toast(`Reset failed: ${message}`);
                alert(`Career reset failed.\n\n${message}\n\nThe database backup was kept and the live career was not changed.`);
            }
            finally {
                resetCareerButton.disabled = false;
                resetCareerButton.textContent = 'Reset to selected snapshot';
            }
        };
    $$('[data-analysis-tab]', content).forEach((n) => n.onclick = async (e) => { e.stopPropagation(); state.analysisTab = n.dataset.analysisTab || 'overview'; await renderAnalysis(); applyIcons(content); bindContent(); });
    $$('[data-commission-ollama]', content).forEach((n) => n.onclick = async () => { const out = $('[data-commission-ai-output]', content); n.disabled = true; n.textContent = 'Analyzing locally…'; if (out)
        out.textContent = 'Waiting for the local model. The Atlas panel remains available.'; try {
        const result = await api(`/api/careers/${state.careerId}/commission/ollama`, { method: 'POST', body: JSON.stringify({ snapshot_id: Number(n.dataset.snapshotId) }) });
        if (out) {
            const notes = result.observations || [];
            out.innerHTML = notes.length ? notes.map((item) => `<p><strong>EA ID ${esc(item.player_ea_id)}</strong> ${esc(item.text)}<small class="table-subline">Evidence: ${esc(item.evidence.join(' · '))}</small></p>`).join('') : esc(result.message || 'No additional observations returned.');
        }
        n.textContent = result.fallback ? 'Try local analysis again' : 'Refresh local analysis';
    }
    catch (error) {
        if (out)
            out.textContent = `Local analysis failed. The Atlas statistics remain available. ${String(error?.message || error)}`;
        n.textContent = 'Try local analysis again';
    }
    finally {
        n.disabled = false;
    } });
    const commissionMode = $('[data-commission-mode]', content);
    const updateCommissionReportControls = () => { const mode = commissionMode?.value || 'match'; const matchWrap = $('[data-commission-fixture-wrap]', content), nextWrap = $('[data-commission-next-wrap]', content), playerWrap = $('[data-commission-player-wrap]', content); if (matchWrap)
        matchWrap.toggleAttribute('hidden', mode !== 'match'); if (nextWrap)
        nextWrap.toggleAttribute('hidden', mode !== 'next_match'); if (playerWrap)
        playerWrap.toggleAttribute('hidden', mode !== 'player'); };
    if (commissionMode) {
        commissionMode.onchange = updateCommissionReportControls;
        updateCommissionReportControls();
    }
    $$('[data-commission-report]', content).forEach(button => button.onclick = async () => {
        const mode = String(button.dataset.mode || commissionMode?.value || 'match');
        const fixture = mode === 'next_match' ? $('[data-commission-next-fixture]', content) : $('[data-commission-fixture]', content);
        const player = $('[data-commission-player]', content);
        const target = String(button.dataset.reportTarget || button.closest('[data-report-slot]')?.getAttribute('data-report-slot') || '');
        const output = target ? $(`[data-report-slot="${target}"]`, content) : $('[data-commission-report-output]', content);
        const payload = { snapshot_id: Number(button.dataset.snapshotId || state.snapshotId), mode, force_refresh: button.dataset.forceRefresh === '1' };
        const fixtureId = Number(button.dataset.fixtureId || fixture?.value || 0), playerId = Number(button.dataset.playerEaId || player?.value || 0);
        if (mode === 'player' || mode === 'match_player')
            payload.player_ea_id = playerId;
        if (mode === 'match' || mode === 'match_player' || mode === 'next_match')
            payload.fixture_id = fixtureId;
        button.disabled = true;
        const oldLabel = button.textContent;
        button.textContent = 'Starting staff report…';
        if (output)
            output.innerHTML = '<p>The report is running in the background. You can keep using Atlas while the local model works.</p>';
        try {
            const started = await api(`/api/careers/${state.careerId}/commission/report-jobs`, { method: 'POST', body: JSON.stringify(payload) });
            let job = { status: started.status }, attempt = 0;
            while (job.status === 'queued' || job.status === 'running') {
                await new Promise(resolve => setTimeout(resolve, 1500));
                job = await api(`/api/careers/${state.careerId}/commission/report-jobs/${started.job_id}`);
                attempt++;
                if (output && attempt % 20 === 0)
                    output.innerHTML = '<p>Ollama is still working in the background. This does not block the rest of Atlas.</p>';
                if (attempt > 240)
                    throw new Error('Report is taking longer than expected; it continues in the background. Refresh the report later to use its cache.');
            }
            if (job.status === 'failed')
                throw new Error(job.error || 'The background report failed.');
            const result = job.result || {};
            if (output) {
                if (!result.available) {
                    output.innerHTML = `<p>${esc(result.message || 'Ollama report unavailable.')}</p>`;
                }
                else {
                    output.innerHTML = commissionReportMarkup(result, payload);
                    if (mode === "player" && target === "player-p1-integrated") {
                        const root = button.closest(".player-p1-ai");
                        root?.querySelector(".player-p1-warnings")?.remove();
                        const lang = atlasLanguage();
                        const messages = [result.review_required ? (lang === "pt-BR" ? "Algumas conclusões exigem revisão" : lang === "es-ES" ? "Algunas conclusiones requieren revisión" : "Some findings require review") : null, result.report?.summary?.model_generated === false ? (lang === "pt-BR" ? "Resumo de fallback determinístico" : lang === "es-ES" ? "Resumen determinístico de apoyo" : "Deterministic fallback summary") : null].filter(Boolean);
                        if (messages.length)
                            output.insertAdjacentHTML("afterbegin", `<div class="player-p1-warnings">${messages.map(msg => `<p>${esc(msg)}</p>`).join("")}</div>`);
                    }
                }
            }
        }
        catch (error) {
            if (output)
                output.textContent = `Local report failed. Atlas metrics are unchanged. ${String(error?.message || error)}`;
        }
        finally {
            button.disabled = false;
            const p1Ready = mode === "player" && target === "player-p1-integrated" && !!output?.querySelector(".commission-report-head");
            if (p1Ready) {
                const badge = button.closest(".player-p1-ai")?.querySelector(".card-header .status-badge");
                if (badge) {
                    badge.textContent = "ready";
                    badge.classList.remove("amber");
                    badge.classList.add("good");
                }
                button.textContent = atlasLanguage() === "pt-BR" ? "Atualizar análise" : atlasLanguage() === "es-ES" ? "Actualizar análisis" : "Refresh analysis";
                button.dataset.forceRefresh = "1";
            }
            else {
                button.textContent = oldLabel;
                button.dataset.forceRefresh = '0';
            }
        }
    });
    const retroButton = $('[data-retroactive-reports]', content);
    const retroOutput = $('[data-retroactive-progress]', content);
    const pollRetroactive = async (jobId) => {
        const win = window;
        if (win.__atlasRetroPollingId === jobId)
            return;
        win.__atlasRetroPollingId = jobId;
        if (retroButton)
            retroButton.disabled = true;
        try {
            let job;
            do {
                job = await api(`/api/careers/${state.careerId}/commission/retroactive-report-jobs/${jobId}`);
                if (retroOutput) {
                    const totalCount = Number(job.total_tasks ?? job.total ?? 0), completedCount = Number(job.completed_tasks ?? job.completed ?? 0), total = num(totalCount), completed = num(completedCount), pct = totalCount ? Math.round(completedCount * 100 / totalCount) : 0;
                    const heading = job.status === 'paused_offline' ? tr('retroPaused') : job.status === 'complete_with_warnings' || job.status === 'failed' ? tr('retroFailed') : job.status === 'complete' ? tr('retroDone') : tr('retroWorking');
                    retroOutput.innerHTML = `<p><strong>${heading}</strong> · ${completed}/${total} (${pct}%)</p><p>${esc(job.current_task || job.current || '')}<br>Generated: ${num(job.generated)} · reused: ${num(job.reused)} · review: ${num(job.review_required)} · failed: ${num(job.failed)} · missing: ${num(job.skipped_missing_data)} · pending: ${num(job.pending)}</p>${job.backup_path ? `<small>${tr('retroBackup')}: ${esc(job.backup_path)}</small>` : ''}${job.error ? `<p class="status-badge amber">${esc(job.error)}</p>` : ''}`;
                    if (retroButton && ['paused_offline', 'paused', 'complete_with_warnings', 'failed'].includes(job.status))
                        retroButton.textContent = tr('retroResume');
                }
                if (['queued', 'running'].includes(job.status))
                    await new Promise(resolve => setTimeout(resolve, 2000));
            } while (['queued', 'running'].includes(job.status));
            sessionStorage.removeItem(`atlas-retro-${state.careerId}`);
            if (job.status === 'complete')
                toast(tr('retroDone'));
        }
        catch (error) {
            if (retroOutput)
                retroOutput.innerHTML = `<p class="status-badge amber">${esc(String(error?.message || error))}</p>`;
            sessionStorage.removeItem(`atlas-retro-${state.careerId}`);
        }
        finally {
            win.__atlasRetroPollingId = '';
            if (retroButton)
                retroButton.disabled = false;
        }
    };
    if (retroButton)
        retroButton.onclick = async () => {
            retroButton.disabled = true;
            if (retroOutput)
                retroOutput.innerHTML = `<p>${tr('retroBackup')}…</p>`;
            try {
                const started = await api(`/api/careers/${state.careerId}/commission/retroactive-report-jobs`, { method: 'POST', body: JSON.stringify({ season_index: Number(retroButton.dataset.seasonIndex) }) });
                sessionStorage.setItem(`atlas-retro-${state.careerId}`, started.job_id);
                await pollRetroactive(started.job_id);
            }
            catch (error) {
                retroButton.disabled = false;
                if (retroOutput)
                    retroOutput.innerHTML = `<p class="status-badge amber">${esc(String(error?.message || error))}</p>`;
            }
        };
    const pendingRetro = sessionStorage.getItem(`atlas-retro-${state.careerId}`);
    if (pendingRetro && retroButton)
        void pollRetroactive(pendingRetro);
    $$('[data-snapshot]', content).forEach((n) => n.onclick = async () => { state.snapshotId = Number(n.dataset.snapshot); snapshotSelect.value = String(state.snapshotId); updateSystemUi(); await render(); });
    $$('[data-action]', content).forEach((n) => n.onclick = () => handleAction(n.dataset.action));
    $$('[data-media-source]', content).forEach((n) => n.onclick = async () => { const result = await api('/api/media/sources/pick', { method: 'POST', body: JSON.stringify({ sourceType: n.dataset.mediaSource }) }); if (result.ok) {
        toast('Media source added');
        await renderMedia();
        applyIcons(content);
        bindContent();
    } });
    $$('[data-remove-source]', content).forEach((n) => n.onclick = async () => { await api('/api/media/sources/remove', { method: 'POST', body: JSON.stringify({ sourceId: Number(n.dataset.removeSource) }) }); await renderMedia(); applyIcons(content); bindContent(); });
    $$('[data-assign-asset]', content).forEach((n) => n.onclick = async () => { const id = Number(n.dataset.assignAsset), entityType = $(`[data-assign-type="${id}"]`, content).value, eaId = Number($(`[data-assign-id="${id}"]`, content).value); await api('/api/media/assign', { method: 'POST', body: JSON.stringify({ assetId: id, entityType, eaId }) }); clearApiCache(); toast('Media asset assigned'); await renderMedia(); applyIcons(content); bindContent(); });
    $$('[data-save-competition-media]', content).forEach((n) => n.onclick = async () => { const objectId = Number(n.dataset.saveCompetitionMedia), input = $(`[data-competition-media-id="${objectId}"]`, content), raw = String(input?.value || '').trim(); await api('/api/media/competition-mappings', { method: 'POST', body: JSON.stringify({ snapshotId: state.snapshotId, competitionObjectId: objectId, mediaCompetitionId: raw ? Number(raw) : null }) }); clearApiCache(); toast(raw ? 'Competition logo assigned' : 'Assignment removed'); await renderMedia(); applyIcons(content); bindContent(); });
}
function bindShell() {
    careerSelect.onchange = async () => { clearApiCache(); state.careerId = Number(careerSelect.value); state.movementSeasonIndex = null; state.movementEditKind = null; state.movementEditId = null; state.analysisSeasonIndex = null; state.seasonReportSeasonIndex = null; state.clubTab = "overview"; state.competitionListTab = "deeper"; await loadSnapshots(); fillSelectors(); updateSystemUi(); navigate("overview"); };
    snapshotSelect.onchange = () => { clearApiCache(); state.snapshotId = Number(snapshotSelect.value); state.compareTo = state.snapshotId; updateSystemUi(); navigate(state.route, state.routeData, false); };
    $("#backButton").onclick = () => goHistory(-1);
    $("#forwardButton").onclick = () => goHistory(1);
    $("#scanButton").onclick = () => handleAction("scan");
    $("#workspaceBadge").onclick = () => navigate("setup");
    $("#globalSearch").onclick = openSearch;
    $("#windowMenu").onclick = toggleStatus;
    $$('[data-route]', $("#mainNav")).forEach((n) => n.onclick = () => navigate(n.dataset.route));
    $(".brand").onclick = () => navigate("overview");
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            openSearch();
        }
        if (e.key === "Escape") {
            closeSearch();
            statusPopover.classList.add("hidden");
        }
        if (!searchPalette.classList.contains("hidden")) {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                moveSearch(1);
            }
            if (e.key === "ArrowUp") {
                e.preventDefault();
                moveSearch(-1);
            }
            if (e.key === "Enter") {
                e.preventDefault();
                openSearchSelection();
            }
        }
    });
    document.addEventListener("mousedown", (e) => {
        if (e.button === 3) {
            e.preventDefault();
            goHistory(-1);
        }
        if (e.button === 4) {
            e.preventDefault();
            goHistory(1);
        }
    });
    searchInput.oninput = debounce(runSearch, 160);
}
async function handleAction(action) {
    if (action === "setup") {
        navigate("setup");
        return;
    }
    if (action === "scan") {
        clearApiCache();
        const r = await api("/api/import/scan", { method: "POST", body: "{}" });
        await refreshCareerBootstrap(false);
        const pending = r.some((item) => String(item?.status || "") === "pending");
        toast(pending ? "Career detected · confirm assignment" : `${r.length} export packages processed`);
        if (pending && !state.careers.length) {
            navigate("setup");
            return;
        }
        await render();
        return;
    }
    if (action === "rebuild-competition-media") {
        await api("/api/media/competition-mappings/rebuild", { method: "POST", body: JSON.stringify({ snapshotId: state.snapshotId }) });
        toast("Competition mappings rebuilt");
        if (state.route === "media") {
            await renderMedia();
            applyIcons(content);
            bindContent();
        }
        return;
    }
    if (action === "scan-media") {
        const r = await api("/api/media/scan", { method: "POST", body: "{}" });
        toast(r.alreadyRunning ? "A media index is already running" : "Quick media index started");
        startMediaProgressPolling();
        if (state.route === "media") {
            await renderMedia();
            applyIcons(content);
            bindContent();
        }
        return;
    }
    if (action === "media-pause") {
        await api("/api/media/pause", { method: "POST", body: "{}" });
        toast("WebP processing paused");
        await refreshMediaProgress();
        return;
    }
    if (action === "media-resume") {
        await api("/api/media/resume", { method: "POST", body: "{}" });
        toast("WebP processing resumed");
        startMediaProgressPolling();
        return;
    }
    if (action === "media-cancel") {
        await api("/api/media/cancel", { method: "POST", body: "{}" });
        toast("Index will stop after the current file block");
        return;
    }
    if (action === "import-main-db") {
        toast("Reading Main DB …");
        const r = await api("/api/reference/pick-main-db", { method: "POST", body: "{}" });
        if (r.ok) {
            state.status = await api("/api/status");
            updateSystemUi();
            toast("EA FC reference data updated");
            await render();
        }
        return;
    }
    if (action === "pick-folder") {
        const r = await api("/api/config/pick-folder", { method: "POST", body: "{}" });
        if (r.path) {
            $("#rootPath", content).value = r.path;
            state.status = await api("/api/status");
            updateSystemUi();
        }
        return;
    }
    if (action === "save-root") {
        const path = $("#rootPath", content).value;
        await api("/api/config/snapshot-root", { method: "POST", body: JSON.stringify({ path }) });
        state.status = await api("/api/status");
        updateSystemUi();
        toast("Snapshot folder saved");
    }
}
async function pollStatus() {
    try {
        const oldSnapshotCount = Number(state.status?.snapshotCount || 0);
        const oldCareerDate = String(state.careerClock?.careerDate || "");
        state.status = await api("/api/status");
        if (state.careerId)
            state.careerClock = await api(`/api/careers/${state.careerId}/clock`);
        const snapshotChanged = Number(state.status?.snapshotCount || 0) !== oldSnapshotCount;
        const clockChanged = String(state.careerClock?.careerDate || "") !== oldCareerDate;
        if (snapshotChanged)
            await refreshCareerBootstrap(false);
        else {
            if (clockChanged)
                fillSelectors();
            updateSystemUi();
        }
        const liveRefreshNeeded = snapshotChanged || clockChanged || state.pendingLiveRender;
        if (liveRefreshNeeded) {
            state.pendingLiveRender = false;
            await render();
            if (snapshotChanged || clockChanged)
                toast(snapshotChanged ? "New snapshot data loaded" : `Career date updated to ${dateText(state.careerClock?.careerDate)}`);
        }
    }
    catch { }
}
function toggleStatus() { statusPopover.classList.toggle("hidden"); statusPopover.innerHTML = `<div class="status-line"><span>Version</span><b>v${esc(state.status?.version || "–")}</b></div><div class="status-line"><span>Careers</span><b>${num(state.status?.careerCount)}</b></div><div class="status-line"><span>Snapshots</span><b>${num(state.status?.snapshotCount)}</b></div><div class="status-line"><span>Ready</span><b>${num(state.status?.readyCount)}</b></div><div class="status-line"><span>Watcher</span><b class="positive">Active</b></div>`; }
function openSearch() { searchPalette.classList.remove("hidden"); searchInput.value = ""; searchResults.innerHTML = '<div class="muted" style="padding:18px">Enter a name or EA ID.</div>'; state.searchResults = []; state.searchIndex = -1; setTimeout(() => searchInput.focus(), 30); }
function closeSearch() { searchPalette.classList.add("hidden"); }
async function runSearch() {
    const q = searchInput.value.trim();
    if (!q) {
        searchResults.innerHTML = '<div class="muted" style="padding:18px">Enter a name or EA ID.</div>';
        return;
    }
    state.searchResults = await api(`/api/search?snapshot_id=${state.snapshotId}&q=${encodeURIComponent(q)}`);
    state.searchIndex = state.searchResults.length ? 0 : -1;
    renderSearchResults();
}
function renderSearchResults() { searchResults.innerHTML = state.searchResults.map((r, i) => `<button class="palette-result ${i === state.searchIndex ? "active" : ""}" data-search-index="${i}"><span class="avatar ${r.type === "club" ? "club" : ""}">${esc(initials(r.label))}</span><span class="palette-result-copy"><strong>${esc(r.label)}</strong><small>${esc(r.subtitle || r.type)} · ID ${num(r.id)}</small></span><span>${r.type === "player" ? `${positionBadge(r.extra)} ${overallBadge(r.meta)}` : r.type === "club" ? overallBadge(r.meta) : statusBadge("Competition")}</span></button>`).join("") || '<div class="muted" style="padding:18px">No results.</div>'; $$('[data-search-index]', searchResults).forEach((b) => b.onclick = () => { state.searchIndex = Number(b.dataset.searchIndex); openSearchSelection(); }); }
function moveSearch(delta) {
    if (!state.searchResults.length)
        return;
    state.searchIndex = (state.searchIndex + delta + state.searchResults.length) % state.searchResults.length;
    renderSearchResults();
    $('[data-search-index].active', searchResults)?.scrollIntoView({ block: "nearest" });
}
function openSearchSelection() {
    const r = state.searchResults[state.searchIndex];
    if (!r)
        return;
    closeSearch();
    navigate(r.type === "player" ? "player" : r.type === "club" ? "club" : "competition", { id: Number(r.id) });
}
function debounce(fn, ms) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); }; }
bootstrap();
