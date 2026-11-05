"use strict";
let mediaProgressTimer: number | null = null;
let lastMediaProgressPhase: string | null = null;
let lastMediaPending: number | null = null;
let mediaRefreshPending = false;
const apiCache = new Map<string, { time: number; value: Promise<any> }>();
const state: AtlasState = {
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
const $ = <T extends Element = any>(selector: string, root: ParentNode = document): T => root.querySelector(selector) as T;
const $$ = <T extends Element = HTMLElement>(selector: string, root: ParentNode = document): T[] => Array.from(root.querySelectorAll<T>(selector));
const content = $<HTMLElement>("#content");
const toastEl = $<HTMLElement>("#toast");
const careerSelect = $<HTMLSelectElement>("#careerSelect");
const snapshotSelect = $<HTMLSelectElement>("#snapshotSelect");
const searchPalette = $<HTMLElement>("#searchPalette");
const searchInput = $<HTMLInputElement>("#searchInput");
const searchResults = $<HTMLElement>("#searchResults");
const statusPopover = $<HTMLElement>("#statusPopover");
const iconSvg = (path: string): string => `<svg viewBox="0 0 24 24" fill="none"><path d="${path}" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICONS: Record<string, string> = {
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
function applyIcons(root: ParentNode = document): void {
    $$('[data-icon]', root).forEach((n: any) => {
        const key = n.dataset.icon;
        if (key && ICONS[key])
            n.innerHTML = ICONS[key];
    });
}
const ATLAS_TEXT: Record<string, Record<string, string>> = {
  "pt-BR": {navOverview:"Visão geral",navChronology:"Linha do tempo",navManual:"Dados históricos",navMatches:"Central de partidas",navSchedule:"Calendário",navResults:"Resultados",navCompetitions:"Competições",navSquad:"Elenco",navContracts:"Contratos",navTransfers:"Transferências",navLoans:"Empréstimos",navYouth:"Base FC26",navCommission:"Comissão técnica",navAnalysis:"Análises",navRecords:"Recordes",navSeasonReport:"Relatório da temporada",navCompare:"Comparar snapshots",navSnapshots:"Snapshots",navImports:"Importações",navMedia:"Biblioteca de mídia",navSetup:"Configurações",crumbOverview:"Visão geral",crumbCommission:"Comissão técnica",crumbAnalysis:"Análises",crumbMatches:"Partidas",crumbMatch:"Partida",crumbSquad:"Elenco",crumbPlayer:"Perfil do jogador",crumbSetup:"Configurações",setupLanguage:"Idioma do Atlas",setupLanguageHelp:"Define o idioma da interface principal e das análises da Comissão Técnica.",saveLanguage:"Salvar idioma",languageSaved:"Idioma do Atlas atualizado.",commissionNote:"Nota da comissão",claimFact:"Fato observado",claimInference:"Inferência baseada em evidências",claimHypothesis:"Hipótese esportiva",claimLimit:"Limite da evidência",claimsFiltered:"Afirmações filtradas",interpretationNotScored:"Qualidade interpretativa não avaliada independentemente",reportOnDemand:"Análises sob demanda",generateReport:"Gerar análise",retroTitle:"Analisar histórico da carreira",retroHelp:"Gera relatórios da temporada selecionada em ordem cronológica. Atualiza partidas, jogadores e avaliações acumuladas; retoma após interrupções e sinaliza dados ausentes.",retroStart:"Gerar análises históricas",retroResume:"Retomar análises históricas",retroWorking:"Processando análises históricas",retroPaused:"Pausado: Ollama indisponível. O progresso foi salvo; clique em retomar.",retroFailed:"Concluído com falhas ou dados ausentes",retroDone:"Análises históricas concluídas",retroBackup:"Backup criado antes da geração"},
  "en-GB": {navOverview:"Overview",navChronology:"Career timeline",navManual:"Historical data",navMatches:"Match Centre",navSchedule:"Schedule",navResults:"Results",navCompetitions:"Competitions",navSquad:"Squad",navContracts:"Contracts",navTransfers:"Transfer history",navLoans:"Loans",navYouth:"FC26 youth",navCommission:"Technical commission",navAnalysis:"Analysis",navRecords:"Records",navSeasonReport:"Season report",navCompare:"Snapshot comparison",navSnapshots:"Snapshots",navImports:"Imports",navMedia:"Media library",navSetup:"Settings",crumbOverview:"Overview",crumbCommission:"Technical commission",crumbAnalysis:"Analysis",crumbMatches:"Matches",crumbMatch:"Match",crumbSquad:"Squad",crumbPlayer:"Player profile",crumbSetup:"Settings",setupLanguage:"Atlas language",setupLanguageHelp:"Sets the main interface and Technical Commission analysis language.",saveLanguage:"Save language",languageSaved:"Atlas language updated.",commissionNote:"Commission note",claimFact:"Observed fact",claimInference:"Evidence-based inference",claimHypothesis:"Sports hypothesis",claimLimit:"Evidence limitation",claimsFiltered:"Claims filtered",interpretationNotScored:"Interpretation quality not independently scored",reportOnDemand:"On-demand analysis",generateReport:"Generate analysis",retroTitle:"Analyse career history",retroHelp:"Generate reports for the selected season in chronological order. Update match, player and accumulated assessments; resume after interruptions and flag missing data.",retroStart:"Generate historical reports",retroResume:"Resume historical reports",retroWorking:"Processing historical reports",retroPaused:"Paused: Ollama is unavailable. Progress is saved; select resume to continue.",retroFailed:"Completed with failures or missing data",retroDone:"Historical reports complete",retroBackup:"Backup created before generation"},
  "es-ES": {navOverview:"Resumen",navChronology:"Cronología",navManual:"Datos históricos",navMatches:"Centro de partidos",navSchedule:"Calendario",navResults:"Resultados",navCompetitions:"Competiciones",navSquad:"Plantilla",navContracts:"Contratos",navTransfers:"Historial de traspasos",navLoans:"Cesiones",navYouth:"Cantera FC26",navCommission:"Comisión técnica",navAnalysis:"Análisis",navRecords:"Récords",navSeasonReport:"Informe de temporada",navCompare:"Comparar snapshots",navSnapshots:"Snapshots",navImports:"Importaciones",navMedia:"Biblioteca multimedia",navSetup:"Ajustes",crumbOverview:"Resumen",crumbCommission:"Comisión técnica",crumbAnalysis:"Análisis",crumbMatches:"Partidos",crumbMatch:"Partido",crumbSquad:"Plantilla",crumbPlayer:"Perfil del jugador",crumbSetup:"Ajustes",setupLanguage:"Idioma de Atlas",setupLanguageHelp:"Define el idioma de la interfaz principal y de los análisis de la Comisión Técnica.",saveLanguage:"Guardar idioma",languageSaved:"Idioma de Atlas actualizado.",commissionNote:"Nota de la comisión",claimFact:"Hecho observado",claimInference:"Inferencia basada en evidencias",claimHypothesis:"Hipótesis deportiva",claimLimit:"Límite de la evidencia",claimsFiltered:"Afirmaciones filtradas",interpretationNotScored:"Calidad interpretativa no evaluada de forma independiente",reportOnDemand:"Análisis bajo demanda",generateReport:"Generar análisis",retroTitle:"Analizar el historial de la carrera",retroHelp:"Genera informes para la temporada seleccionada en orden cronológico. Actualiza partidos, jugadores y valoraciones acumuladas; reanuda después de interrupciones y señala datos ausentes.",retroStart:"Generar informes históricos",retroResume:"Reanudar informes históricos",retroWorking:"Procesando informes históricos",retroPaused:"Pausado: Ollama no está disponible. El progreso está guardado; pulse reanudar.",retroFailed:"Terminado con fallos o datos ausentes",retroDone:"Informes históricos terminados",retroBackup:"Copia de seguridad creada antes de generar"}
};
Object.assign(ATLAS_TEXT["pt-BR"],{moreContextTitle:"A comissão pediu mais contexto",moreContextHelp:"Responda apenas o que souber. Sua resposta será enviada separada das estatísticas importadas.",yourContext:"Sua resposta",sendContext:"Enviar contexto à comissão",contextSent:"Contexto enviado ao Ollama; atualizando a análise…"});
Object.assign(ATLAS_TEXT["en-GB"],{moreContextTitle:"The commission needs more context",moreContextHelp:"Answer only what you know. Your response is sent separately from imported statistics.",yourContext:"Your answer",sendContext:"Send context to the commission",contextSent:"Context sent to Ollama; refreshing the analysis…"});
Object.assign(ATLAS_TEXT["es-ES"],{moreContextTitle:"La comisión necesita más contexto",moreContextHelp:"Responde solo lo que sepas. Tu respuesta se envía por separado de las estadísticas importadas.",yourContext:"Tu respuesta",sendContext:"Enviar contexto a la comisión",contextSent:"Contexto enviado a Ollama; actualizando el análisis…"});
function atlasLanguage(): string { const selected=String(state.status?.settings?.language||"pt-BR");return ATLAS_TEXT[selected]?selected:"pt-BR"; }
function tr(key: string): string { return ATLAS_TEXT[atlasLanguage()][key]||ATLAS_TEXT["en-GB"][key]||key; }
function applyAtlasLanguage(): void { const language=atlasLanguage();document.documentElement.lang=language;$$<HTMLElement>("[data-nav-key]").forEach(item=>{const key=String(item.dataset.navKey||"");if(key)item.textContent=tr(key);}); }
function esc(value: any) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
function num(value: any, digits: any = 0) { if(value==null||value==="")return "–";const n = Number(value); return Number.isFinite(n) ? new Intl.NumberFormat(atlasLanguage(), { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n) : "–"; }
function rawNumber(value: any): string { const n = Number(value); return Number.isFinite(n) ? String(n) : ""; }
function commissionFollowupForm(requests:any[],params:any):string {
    if(!Array.isArray(requests)||!requests.length)return "";
    const prior=Array.isArray(params.coach_context)?params.coach_context.slice(0,6).map((item:any)=>`<input type="hidden" name="prior_question" value="${esc(item.question||"")}"><input type="hidden" name="prior_answer" value="${esc(item.answer||"")}">`).join(""):"";
    const fields=requests.slice(0,2).map((request:any,index:number)=>`<div class="commission-followup-question"><label for="commission-followup-answer-${index}"><strong>${esc(request.question||"")}</strong><small>${esc(request.reason||"")}</small></label><input type="hidden" name="question" value="${esc(request.question||"")}"><textarea id="commission-followup-answer-${index}" name="answer" maxlength="1000" required placeholder="${esc(tr("yourContext"))}"></textarea></div>`).join("");
    return `<form class="commission-followup-form" data-commission-followup data-snapshot-id="${Number(params.snapshot_id||0)}" data-mode="${esc(params.mode||"")}" data-fixture-id="${Number(params.fixture_id||0)}" data-player-ea-id="${Number(params.player_ea_id||0)}" data-model="${esc(params.model||"")}">${prior}<h4>${esc(tr("moreContextTitle"))}</h4><p>${esc(tr("moreContextHelp"))}</p>${fields}<button class="button" type="submit">${esc(tr("sendContext"))}</button></form>`;
}
function rawId(value: any): string { const n = Number(value); return Number.isSafeInteger(n) && n > 0 ? String(n) : ""; }
function compact(value: any) { const n = Number(value); return Number.isFinite(n) ? new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 }).format(n) : "–"; }
function money(value: any) {
    const n = Number(value);
    if (!Number.isFinite(n))
        return "–";
    if (Math.abs(n) >= 1e6)
        return `€${num(n / 1e6, 1)}m`;
    if (Math.abs(n) >= 1e3)
        return `€${num(n / 1e3, 0)}k`;
    return `€${num(n)}`;
}
function financialHint(financial: any, kind: "market" | "wage") {
    const item = kind === "market" ? financial?.market_value : financial?.weekly_wage;
    if (!item) return "";
    const parts: string[] = [];
    if (item.label) parts.push(String(item.label));
    if (item.profitability_value_source === "observed") parts.push(`Profitability ${item.profitability_value}: observed`);
    if (item.profitability_value_source === "inferred_from_later_snapshot") parts.push(`Profitability ${item.profitability_value}: inferred from a later snapshot`);
    if (item.warning) parts.push(String(item.warning));
    if (item.profile_id) parts.push(`Profile ${item.profile_id}`);
    return esc(parts.join(" · "));
}
function dateText(value: any) {
    if (!value)
        return "–";
    const d = new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime()) ? esc(value) : new Intl.DateTimeFormat(atlasLanguage()).format(d);
}
function timeText(v: any) { return v ? String(v).slice(0, 5) : ""; }
function initials(value: any) { const p = String(value || "AT").trim().split(/\s+/).filter(Boolean); return p.length > 1 ? `${p[0]?.[0] || ""}${p.at(-1)?.[0] || ""}`.toUpperCase() : (p[0] || "AT").slice(0, 2).toUpperCase(); }
const positionAliases: Record<string, string> = {
    TW:"GK", TORWART:"GK", LIB:"SW", LIBERO:"SW", RAV:"RWB", RV:"RB", RIV:"RCB", IV:"CB", LIV:"LCB", LV:"LB", LAV:"LWB",
    ZDM:"CDM", RZM:"RCM", ZM:"CM", LZM:"LCM", ROM:"RAM", ZOM:"CAM", LOM:"LAM", HS:"CF", MS:"CF", LST:"LS", RST:"RS"
};
const positionById: Record<number, string> = {0:"GK",1:"SW",2:"RWB",3:"RB",4:"RCB",5:"CB",6:"LCB",7:"LB",8:"LWB",9:"RDM",10:"CDM",11:"LDM",12:"RM",13:"RCM",14:"CM",15:"LCM",16:"LM",17:"RAM",18:"CAM",19:"LAM",20:"RF",21:"CF",22:"LF",23:"RW",24:"RS",25:"ST",26:"LS",27:"LW"};
function canonicalPosition(value: any, explicitId: any = null) {
    const raw = String(value || "").trim().toUpperCase();
    const hasExplicitId = explicitId !== null && explicitId !== undefined && String(explicitId).trim() !== "";
    const id = hasExplicitId ? Number(explicitId) : Number.NaN;
    return positionAliases[raw] || raw || (Number.isInteger(id) ? positionById[id] : "");
}
function pos(v: any) { return canonicalPosition(v) || "–"; }
function positionClass(v: any) { const value = canonicalPosition(v); if (value === "GK") return "pos-gk"; if (["SW","RWB","RB","RCB","CB","LCB","LB","LWB"].includes(value)) return "pos-def"; if (["RDM","CDM","LDM","RM","RCM","CM","LCM","LM","RAM","CAM","LAM"].includes(value)) return "pos-mid"; return "pos-att"; }
function positionOrder(value: any, explicitId: any = null) {
    const rank: Record<string, number> = {
        GK:0, SW:5,
        RWB:10, RB:11, RCB:20, CB:21, LCB:22, LB:30, LWB:31,
        RDM:40, CDM:41, LDM:42, RCM:50, CM:51, LCM:52,
        RAM:60, CAM:61, LAM:62, RM:70, RF:71, RW:72, LM:80, LF:81, LW:82,
        CF:90, RS:100, ST:101, LS:102
    };
    const canonical = canonicalPosition(value, explicitId);
    return rank[canonical] ?? 999;
}
function overallClass(v: any) { const n = Number(v); return n >= 75 ? "overall-high" : n >= 68 ? "overall-mid" : "overall-low"; }
function resultCode(v: any) { const s = String(v || "").toUpperCase(); return s.startsWith("W") ? "W" : s.startsWith("D") ? "D" : s.startsWith("L") ? "L" : "–"; }
function resultPill(v: any) { const c = resultCode(v); return `<span class="result-pill ${c}">${c}</span>`; }
function boolText(v: any) { return Number(v) === 1 ? "Yes" : Number(v) === 0 ? "No" : "–"; }
function entityMark(name: any, kind: any = "club") { return `<span class="entity-mark ${kind}">${esc(initials(name))}</span>`; }
function mediaImg(asset: any, alt: any, cls: any = "media-image", thumb: any = true) {
    if (!asset) return "";
    const url = thumb ? (asset.thumbUrl || asset.url) : asset.url;
    return url ? `<img class="${esc(cls)}" src="${esc(url)}" alt="${esc(alt || "")}" loading="lazy">` : "";
}
function playerPortrait(media: any, name: any, cls: any = "player-portrait") {
    const portrait = media?.portrait;
    return portrait ? mediaImg(portrait, name, cls, cls !== "player-portrait-large") : `<span class="generated-avatar ${esc(cls)}" style="--seed:${Number(media?.placeholderSeed || 0) % 360}">${esc(initials(name))}</span>`;
}
function identityLogo(identity: any, name: any, cls: any = "identity-logo") {
    return identity?.logo ? mediaImg(identity.logo, name, cls) : `<span class="identity-fallback ${esc(cls)}">${esc(initials(name))}</span>`;
}
function trophyImage(identity: any, name: any, cls: any = "trophy-image") { return identity?.trophy ? mediaImg(identity.trophy, name, cls) : ""; }
function identityStyle(identity: any) { const colors = identity?.colors || []; return colors.length ? `style="--club-primary:${esc(colors[0])};--club-secondary:${esc(colors[1] || colors[0])};--club-accent:${esc(colors[2] || colors[1] || colors[0])}"` : ""; }
function kitCard(kit: any) { const image = kit.image ? mediaImg(kit.image, kit.label, "kit-image", false) : `<span class="kit-placeholder" style="--kit-1:${esc(kit.colors?.[0] || "#d7e1ec")};--kit-2:${esc(kit.colors?.[1] || "#233b57")}"></span>`; return `<div class="kit-card">${image}<strong>${esc(kit.label)}</strong><small>${kit.image?.season_start ? `Season ${kit.image.season_start}/${String(kit.image.season_start + 1).slice(-2)}` : kit.image?.usedFallback ? "Default kit" : "Reference colours"}</small></div>`; }
function playerLink(id: any, name: any) { return `<button class="entity-link" data-player="${Number(id)}">${esc(name || `Player ${id}`)}</button>`; }
function clubLink(id: any, name: any) { return `<button class="entity-link" data-club="${Number(id)}">${esc(name || `Club ${id}`)}</button>`; }
function competitionLink(id: any, name: any) { return `<button class="entity-link" data-competition="${Number(id)}">${esc(name || `Competition ${id}`)}</button>`; }
function matchLink(id: any, label: any = "Open match") { return `<button class="entity-link" data-match="${Number(id)}">${esc(label)}</button>`; }
function positionBadge(v: any) { return `<span class="position-badge ${positionClass(v)}">${esc(pos(v))}</span>`; }
function overallBadge(v: any) { return `<span class="overall-badge ${overallClass(v)}">${num(v)}</span>`; }
function potentialRangeBadge(low: any, high: any) {
    const lo = Number(low), hi = Number(high);
    if (!Number.isFinite(lo) && !Number.isFinite(hi)) return "–";
    const a = Number.isFinite(lo) ? lo : hi, b = Number.isFinite(hi) ? hi : lo;
    if (a === b) return `<span class="potential-range single">${overallBadge(a)}</span>`;
    return `<span class="potential-range">${overallBadge(a)}<span class="range-separator">–</span>${overallBadge(b)}</span>`;
}
function nationalityFlag(nationality: any, cls: any = "nationality-flag") {
    if (!nationality) return "";
    const isSmall = String(cls || "").includes("small");
    const frameClass = `nationality-flag-frame${isSmall ? " small" : ""}`;
    const visual = nationality.flagUrl
      ? `<span class="${frameClass}"><img class="${esc(cls)}" src="${esc(nationality.flagUrl)}" alt="${esc(nationality.name || "Nationality")}" loading="lazy"></span>`
      : `<span class="${frameClass}"><span class="flag-fallback ${esc(cls)}">${esc((nationality.isoCode || nationality.flagCode || "–").slice(0, 3))}</span></span>`;
    return `<span class="nationality-chip">${visual}<span>${esc(nationality.name || "Unknown")}</span></span>`;
}
function statusBadge(text: any, cls: any = "") { return `<span class="status-badge ${cls}">${esc(text)}</span>`; }
function pageHead(title: any, subtitle: any, actions: any = "") { return `<div class="page-head"><div class="page-head-copy"><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="page-actions">${actions}</div></div>`; }
function metric(label: any, value: any, note: any = "", cls: any = "") { return `<div class="card metric-card"><span class="metric-label">${esc(label)}</span><strong class="metric-value ${cls}">${value}</strong><small class="metric-note">${esc(note)}</small></div>`; }
function emptyState(title: any, text: any, action: any = "") { return `<div class="card empty"><div><div class="empty-icon" data-icon="empty"></div><h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div></div>`; }
function errorState(title: any, text: any) { return `<div class="content-inner">${pageHead(title, "Loading error")}<div class="card empty error-card"><div><h2>${esc(title)}</h2><p>${esc(text)}</p></div></div></div>`; }
function card(title: any, body: any, extra: any = "") { return `<section class="card"><header class="card-header"><div><h2>${esc(title)}</h2>${extra}</div></header><div class="card-body">${body}</div></section>`; }
let tableSequence = 0;
function table(headers: TableHeader[], rows: string[] | string | null | undefined, classes: any = "") { const tableId = `atlas-table-${++tableSequence}`; const body = Array.isArray(rows) ? rows.join("") : typeof rows === "string" ? rows : ""; return `<div class="table-wrap"><table id="${tableId}" class="data-table sortable-table ${classes}"><thead><tr>${headers.map((h: any, index: any) => `<th class="${h.cls || ""}" data-column="${index}" data-sortable="${h.sortable === false || !h.label ? "0" : "1"}">${h.sortable === false || !h.label ? esc(h.label) : `<button class="sort-button" type="button">${esc(h.label)}<span class="sort-indicator">↕</span></button>`}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`; }
function parseSortValue(cell: HTMLTableCellElement): SortValue { const explicit = cell.dataset.sort; if (explicit !== undefined) {
    const numeric = Number(explicit);
    return explicit !== "" && Number.isFinite(numeric) ? { type: "number", value: numeric } : { type: "text", value: explicit };
} const raw = (cell.textContent || "").trim(); if (!raw || raw === "–" || raw === "Not recorded")
    return { type: "empty", value: null }; const dateMatch = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/); if (dateMatch)
    return { type: "number", value: Number(`${dateMatch[3]}${dateMatch[2].padStart(2, "0")}${dateMatch[1].padStart(2, "0")}`) }; const moneyMatch = raw.replaceAll(",", "").match(/^€?([+-]?[\d.]+)\s*([mk])?$/i); if (moneyMatch) {
    let value = Number(moneyMatch[1]);
    if (/m/i.test(moneyMatch[2] || ""))
        value *= 1e6;
    if (/k/i.test(moneyMatch[2] || ""))
        value *= 1e3;
    return { type: "number", value };
} const normalized = raw.replace(/^#/, "").replace(/\s*(months|apps|matches|G|A)$/i, "").replaceAll(",", ""); if (/^[+-]?\d+(?:\.\d+)?$/.test(normalized))
    return { type: "number", value: Number(normalized) }; return { type: "text", value: raw.toLocaleLowerCase("en-GB") }; }
function bindSortableTables() { $$("table.sortable-table", content).forEach((tableEl: any) => { const tbody = $("tbody", tableEl); if (!tbody)
    return; const original = [...tbody.rows]; original.forEach((row: any, index: any) => row.dataset.originalIndex = String(index)); $$("th[data-sortable='1']", tableEl).forEach((th: any) => { th.onclick = () => { const column = Number(th.dataset.column); const previousColumn = Number(tableEl.dataset.sortColumn ?? -1); const previousDirection = tableEl.dataset.sortDirection || "none"; let direction = previousColumn !== column ? "asc" : previousDirection === "asc" ? "desc" : previousDirection === "desc" ? "none" : "asc"; tableEl.dataset.sortColumn = String(column); tableEl.dataset.sortDirection = direction; $$("th", tableEl).forEach((header: any) => { header.classList.remove("sort-asc", "sort-desc"); const indicator = $(".sort-indicator", header); if (indicator)
    indicator.textContent = "↕"; }); if (direction === "none") {
    original.sort((a: any, b: any) => Number(a.dataset.originalIndex) - Number(b.dataset.originalIndex)).forEach((row: any) => tbody.appendChild(row));
    return;
} th.classList.add(direction === "asc" ? "sort-asc" : "sort-desc"); const indicator = $(".sort-indicator", th); if (indicator)
    indicator.textContent = direction === "asc" ? "↑" : "↓"; const rows = [...tbody.rows]; rows.sort((a: any, b: any) => { const av = parseSortValue(a.cells[column]), bv = parseSortValue(b.cells[column]); if (av.type === "empty" && bv.type === "empty")
    return 0; if (av.type === "empty")
    return 1; if (bv.type === "empty")
    return -1; let result = 0; if (av.type === "number" && bv.type === "number")
    result = Number(av.value) - Number(bv.value);
else
    result = String(av.value).localeCompare(String(bv.value), "en", { numeric: true, sensitivity: "base" }); return direction === "asc" ? result : -result; }); rows.forEach((row: any) => tbody.appendChild(row)); }; }); }); }
function ratingValue(value: any, average: any = false) { const n = Number(value); if (!Number.isFinite(n) || n <= 0)
    return "–"; if (average)
    return num(n, 2); return Number.isInteger(n) ? num(n, 0) : num(n, 1); }
function delta(v: any) { const n = Number(v) || 0; return `<span class="delta ${n > 0 ? "pos positive" : n < 0 ? "negative" : "muted"}">${n > 0 ? num(n) : num(n)}</span>`; }
function clearApiCache() { apiCache.clear(); }
function cacheableApiPath(path: string, options?: RequestInit): boolean {
    const method = String(options?.method || "GET").toUpperCase();
    if (method !== "GET") return false;
    return /^\/api\/snapshots\/\d+\/(competitions\/\d+|world-leagues\/\d+|players\/\d+|clubs\/\d+|matches(?:\/\d+)?)$/.test(path);
}
async function api<T = JsonRecord>(path: string, options?: RequestInit): Promise<T> {
    const cacheable = cacheableApiPath(path, options);
    const cached = cacheable ? apiCache.get(path) : null;
    if (cached && Date.now() - cached.time < 300000) return cached.value;
    const request = (async () => {
        const r = await fetch(path, { headers: { "Content-Type": "application/json", ...(options?.headers || {}) }, ...options });
        const p = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(p.error || `HTTP ${r.status}`);
        return p;
    })();
    if (cacheable) apiCache.set(path, { time: Date.now(), value: request });
    try { return await request as T; }
    catch (error) { if (cacheable) apiCache.delete(path); throw error; }
}
function toast(message: string): void { toastEl.textContent = message; toastEl.classList.add("show"); setTimeout(() => toastEl.classList.remove("show"), 2600); }
