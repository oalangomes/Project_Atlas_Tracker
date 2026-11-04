function manualSeasonTitle(season: ManualSeason): string {
    const years = season.start_year && season.end_year ? `${season.start_year}/${String(season.end_year).slice(-2)}` : "";
    return years ? `${season.label} · ${years}` : season.label;
}

function manualSourceBadge(): string {
    return statusBadge("manual", "good");
}

function manualUpdated(value: any): string {
    return value ? `<small class="manual-updated">Updated ${dateText(String(value).slice(0, 10))}</small>` : "";
}

function manualPreferenceKey(): string { return `project-atlas-tracker-manual-${state.careerId || "none"}`; }
function manualPreferences(): JsonRecord {
    try { return JSON.parse(localStorage.getItem(manualPreferenceKey()) || "{}"); }
    catch { return {}; }
}
function saveManualPreferences(values: JsonRecord): void {
    localStorage.setItem(manualPreferenceKey(), JSON.stringify({...manualPreferences(), ...values}));
}

function bindManualKeyboard(form: HTMLFormElement, saveNext?: HTMLElement | null): void {
    form.addEventListener("keydown", event => {
        if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter") return;
        event.preventDefault();
        if (event.shiftKey && saveNext instanceof HTMLButtonElement) saveNext.click();
        else form.requestSubmit();
    });
}

function bindUnknownFee(form: ParentNode): void {
    const checkbox = $<HTMLInputElement>("[name='feeUnknown']", form);
    const input = $<HTMLInputElement>("[name='fee']", form);
    if (!checkbox || !input) return;
    const sync = () => { input.disabled = checkbox.checked; if (checkbox.checked) input.value = ""; };
    checkbox.addEventListener("change", sync); sync();
}

function manualFormActions(cancelLabel: string = "Cancel", saveNext: boolean = false): string {
    return `<div class="manual-form-actions"><small>Ctrl+Enter saves${saveNext ? " · Ctrl+Shift+Enter saves and opens the next player" : ""}</small><button type="button" class="button" data-manual-cancel>${esc(cancelLabel)}</button>${saveNext ? `<button type="button" class="button" data-manual-save-next><span data-icon="save"></span>Save & next player</button>` : ""}<button type="submit" class="button primary"><span data-icon="save"></span>Save</button></div>`;
}

function manualPlayerPicker(name: string = "", playerId: any = ""): string {
    return `<label class="span-2 manual-player-field"><span>Player</span><div class="manual-player-picker"><input name="displayName" data-manual-player-search required value="${esc(name)}" placeholder="Enter at least two characters" autocomplete="off"><input type="hidden" name="playerEaId" value="${playerId ?? ""}"><div class="manual-player-results" data-manual-player-results hidden></div></div><small data-manual-player-selection>${playerId ? `Linked to EA ID ${num(playerId)}` : "All players in the career are searched; custom names remain possible."}</small></label>`;
}

function manualSeasonForm(season?: ManualSeason): string {
    const current = season || {} as ManualSeason;
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

function manualCompetitionForm(seasonId: number, competition?: ManualCompetition): string {
    const current = competition || {} as ManualCompetition;
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

function manualStatForm(seasonCompetitions: ManualCompetition[], stat?: ManualPlayerStat): string {
    const current = stat || {} as ManualPlayerStat;
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

function manualTransactionForm(seasonId: number, transaction?: ManualTransaction): string {
    const current = transaction || {} as ManualTransaction;
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

function manualLeagueFinishForm(seasonId: number, finish?: ManualLeagueFinish): string {
    const current = finish || {} as ManualLeagueFinish;
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

function manualDataLists(data: ManualDataResponse): string {
    return `<datalist id="manualTeamNames">${data.references.teams.map((t: any) => `<option value="${esc(t.team_name)}">EA-ID ${num(t.ea_team_id)}</option>`).join("")}</datalist>
      <datalist id="manualCompetitionNames">${data.references.competitions.map((c: any) => `<option value="${esc(c.competition_name)}">Object-ID ${num(c.competition_object_id)}</option>`).join("")}</datalist>
      <datalist id="manualLeagueNames">${data.references.leagues.map((l: any) => `<option value="${esc(l.league_name)}">EA-ID ${num(l.ea_league_id)}</option>`).join("")}</datalist>`;
}

function manualCompetitionSection(data: ManualDataResponse, season: ManualSeason, competitions: ManualCompetition[]): string {
    const editing = state.manualEditKind === "competition" ? competitions.find(c => Number(c.id) === Number(state.manualEditId)) : undefined;
    return `${state.manualEditKind === "competition" ? manualCompetitionForm(season.id, editing) : `<div class="manual-section-actions"><button class="button primary" data-manual-new="competition">Add competition</button></div>`}
      <section class="card"><header class="card-header"><h2>Competitions</h2><span>${manualSourceBadge()}</span></header>${competitions.length ? table([
        { label: "Competition" }, { label: "Type" }, { label: "Position", cls: "center" }, { label: "Result" }, { label: "Actions", sortable: false }
      ], competitions.map(c => `<tr><td><strong>${esc(c.competition_name)}</strong>${manualUpdated(c.updated_at)}</td><td>${statusBadge(c.competition_type)}</td><td class="center">${c.final_position ? `#${num(c.final_position)}` : "–"}</td><td>${esc(c.result_text || "–")}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="competition" data-id="${c.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="competitions" data-id="${c.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No competitions recorded yet.</span></div>`}</section>`;
}

function manualQuickStatsForm(competitions: ManualCompetition[]): string {
    const selected = Number(state.manualDraftCompetitionId || manualPreferences().competitionId || competitions[0]?.id);
    const rows = Array.from({length: 6}, (_, index) => `<fieldset class="manual-quick-stat-row" data-quick-stat-row><legend>Row ${index + 1}</legend>${manualPlayerPicker()}<div class="quick-stat-numbers"><label><span>Apps</span><input name="appearances" type="number" min="0" max="999" value="0"></label><label><span>G</span><input name="goals" type="number" min="0" max="999" value="0"></label><label><span>A</span><input name="assists" type="number" min="0" max="999" value="0"></label><label><span>CS</span><input name="cleanSheets" type="number" min="0" max="999" value="0"></label><label><span>Avg.</span><input name="averageRating" inputmode="decimal" placeholder="7,25"></label></div></fieldset>`).join("");
    return `<section class="card pad manual-editor-card quick-entry-card"><div class="card-title-row"><div><h3 class="card-title">Quick entry</h3><span>Choose a competition and save several players in one pass.</span></div><button type="button" class="button" data-manual-quick-toggle>Close</button></div><form id="manualQuickStatsForm"><label class="quick-entry-competition"><span>Competition for all rows</span><select name="competitionId">${competitions.map(c=>`<option value="${c.id}" ${Number(c.id)===selected?"selected":""}>${esc(c.competition_name)}</option>`).join("")}</select></label><div class="manual-quick-stat-grid">${rows}</div><div class="manual-form-actions"><small>Empty rows are skipped · Ctrl+Enter saves all completed rows</small><button type="submit" class="button primary">Save all completed rows</button></div></form></section>`;
}

function manualStatsSection(data: ManualDataResponse, season: ManualSeason, competitions: ManualCompetition[], stats: ManualPlayerStat[]): string {
    const editing = state.manualEditKind === "stat" ? stats.find(s => Number(s.id) === Number(state.manualEditId)) : undefined;
    const form = competitions.length ? manualStatForm(competitions, editing) : `<div class="card pad"><span class="muted">Create at least one competition first.</span></div>`;
    return `${state.manualQuickEntry && competitions.length ? manualQuickStatsForm(competitions) : state.manualEditKind === "stat" ? form : `<div class="manual-section-actions"><button class="button" data-manual-quick-toggle ${competitions.length ? "" : "disabled"}>Quick entry</button><button class="button primary" data-manual-new="stat" ${competitions.length ? "" : "disabled"}>Add individual statistics</button></div>`}
      <section class="card"><header class="card-header"><h2>Player statistics by competition</h2><span>${manualSourceBadge()}</span></header>${stats.length ? table([
        { label: "Player" }, { label: "Competition" }, { label: "Apps", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "CS", cls: "num" }, { label: "Avg. rating", cls: "num" }, { label: "Actions", sortable: false }
      ], stats.map(s => `<tr><td>${s.player_ea_id ? `<strong>${playerLink(s.player_ea_id, s.display_name)}</strong><small>EA-ID ${num(s.player_ea_id)}</small>` : `<strong>${esc(s.display_name)}</strong><small class="manual-unlinked">not linked</small>`}${manualUpdated(s.updated_at)}</td><td>${esc(s.competition_name)}</td><td class="num">${num(s.appearances)}</td><td class="num">${num(s.goals)}</td><td class="num">${num(s.assists)}</td><td class="num">${num(s.clean_sheets)}</td><td class="num">${ratingValue(s.average_rating, true)}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="stat" data-id="${s.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="stats" data-id="${s.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No player statistics recorded yet.</span></div>`}</section>`;
}

function manualTransactionsSection(season: ManualSeason, transactions: ManualTransaction[]): string {
    const editing = state.manualEditKind === "transaction" ? transactions.find(t => Number(t.id) === Number(state.manualEditId)) : undefined;
    return `${state.manualEditKind === "transaction" ? manualTransactionForm(season.id, editing) : `<div class="manual-section-actions"><button class="button primary" data-manual-new="transaction">Add transfer or loan</button></div>`}
      <section class="card"><header class="card-header"><h2>Transfers and loans</h2><span>${manualSourceBadge()}</span></header>${transactions.length ? table([
        { label: "Player" }, { label: "Type" }, { label: "Direction" }, { label: "From" }, { label: "To" }, { label: "Fee", cls: "num" }, { label: "Date" }, { label: "Actions", sortable: false }
      ], transactions.map(t => `<tr><td><strong>${t.player_ea_id ? playerLink(t.player_ea_id, t.display_name) : esc(t.display_name)}</strong>${t.player_ea_id ? `<small>EA-ID ${num(t.player_ea_id)}</small>` : `<small class="manual-unlinked">not linked</small>`}${manualUpdated(t.updated_at)}</td><td>${statusBadge(t.transaction_type === "loan" ? "Loan" : "Transfer")}</td><td>${statusBadge(t.direction === "incoming" ? "Incoming" : "Outgoing", t.direction === "incoming" ? "good" : "")}</td><td>${esc(t.from_team_name || "–")}</td><td>${esc(t.to_team_name || "–")}</td><td class="num">${t.fee === null || t.fee === undefined ? "–" : money(t.fee)}</td><td>${t.transaction_date ? dateText(t.transaction_date) : "–"}${t.loan_end_date ? `<small>until ${dateText(t.loan_end_date)}</small>` : ""}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="transaction" data-id="${t.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="transactions" data-id="${t.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No transfers or loans recorded yet.</span></div>`}</section>`;
}

function manualLeagueFinishesSection(season: ManualSeason, finishes: ManualLeagueFinish[]): string {
    const editing = state.manualEditKind === "league-finish" ? finishes.find(f => Number(f.id) === Number(state.manualEditId)) : undefined;
    return `${state.manualEditKind === "league-finish" ? manualLeagueFinishForm(season.id, editing) : `<div class="manual-section-actions"><button class="button primary" data-manual-new="league-finish">Add league finish</button></div>`}
      <section class="card"><header class="card-header"><h2>League finishes aller clubs</h2><span>${manualSourceBadge()}</span></header>${finishes.length ? table([
        { label: "Club" }, { label: "League" }, { label: "Position", cls: "center" }, { label: "Source" }, { label: "Actions", sortable: false }
      ], finishes.map(f => `<tr><td><strong>${f.team_ea_id ? clubLink(f.team_ea_id, f.team_name) : esc(f.team_name)}</strong>${manualUpdated(f.updated_at)}</td><td>${esc(f.league_name)}</td><td class="center"><strong>#${num(f.final_position)}</strong></td><td>${statusBadge("Manual", "good")}</td><td><div class="row-actions"><button class="entity-link" data-manual-edit="league-finish" data-id="${f.id}">Edit</button><button class="entity-link danger-link" data-manual-delete="league-finishes" data-id="${f.id}">Delete</button></div></td></tr>`)) : `<div class="card-body"><span class="muted">No league finishes for other clubs recorded yet.</span></div>`}</section>`;
}

function manualChangesSection(data: ManualDataResponse): string {
    const labels: Record<string, string> = { season: "Season", competition: "Competition", player_stat: "Player statistics", transaction: "Transfer/loan", league_finish: "League finish" };
    return `<section class="card"><header class="card-header"><h2>Change log</h2><span>${num(data.changes.length)} entries</span></header>${data.changes.length ? table([
      { label: "Zeit" }, { label: "Aktion" }, { label: "Bereich" }, { label: "Datensatz" }
    ], data.changes.map((c: any) => `<tr><td>${esc(c.occurred_at)}</td><td>${statusBadge(c.action)}</td><td>${esc(labels[c.entity_type] || c.entity_type)}</td><td class="mono">#${num(c.entity_id)}</td></tr>`)) : `<div class="card-body"><span class="muted">No manual changes yet.</span></div>`}</section>`;
}

async function renderManualData(): Promise<void> {
    const data = await api<ManualDataResponse>(`/api/careers/${state.careerId}/manual-data`);
    if (!state.manualSeasonId || !data.seasons.some(s => Number(s.id) === Number(state.manualSeasonId))) state.manualSeasonId = data.seasons.length ? Number(data.seasons[0].id) : null;
    const season = data.seasons.find(s => Number(s.id) === Number(state.manualSeasonId));
    const competitions = data.competitions.filter(c => Number(c.manual_season_id) === Number(state.manualSeasonId));
    const stats = data.stats.filter(s => Number(s.manual_season_id) === Number(state.manualSeasonId));
    const transactions = data.transactions.filter(t => Number(t.manual_season_id) === Number(state.manualSeasonId));
    const leagueFinishes = data.leagueFinishes.filter(f => Number(f.manual_season_id) === Number(state.manualSeasonId));
    const totals = { seasons: data.seasons.length, competitions: data.competitions.length, stats: data.stats.length, transactions: data.transactions.length, leagueFinishes: data.leagueFinishes.length };
    const seasonEditing = state.manualEditKind === "season" ? data.seasons.find(s => Number(s.id) === Number(state.manualEditId)) : undefined;
    let main = "";
    if (!season) main = manualSeasonForm(seasonEditing);
    else if (state.manualEditKind === "season") main = manualSeasonForm(state.manualEditId ? seasonEditing : undefined);
    else {
        const tabs = [["competitions", "Competitions"], ["league-finishes", "League finishes"], ["stats", "Player statistics"], ["transactions", "Transfers & loans"], ["changes", "Changes"]];
        let section = manualCompetitionSection(data, season, competitions);
        if (state.manualTab === "league-finishes") section = manualLeagueFinishesSection(season, leagueFinishes);
        if (state.manualTab === "stats") section = manualStatsSection(data, season, competitions, stats);
        if (state.manualTab === "transactions") section = manualTransactionsSection(season, transactions);
        if (state.manualTab === "changes") section = manualChangesSection(data);
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

function formPayload(form: HTMLFormElement): JsonRecord {
    const payload: JsonRecord = {};
    new FormData(form).forEach((value, key) => payload[key] = typeof value === "string" ? value.trim() : value);
    return payload;
}

function resolveManualReference(data: ManualDataResponse, kind: "team" | "competition" | "league", name: string): JsonRecord | undefined {
    const needle = name.trim().toLocaleLowerCase("de");
    const rows = kind === "team" ? data.references.teams : kind === "competition" ? data.references.competitions : data.references.leagues;
    const field = kind === "team" ? "team_name" : kind === "competition" ? "competition_name" : "league_name";
    return rows.find((row: any) => String(row[field] || "").trim().toLocaleLowerCase("de") === needle);
}

async function saveManualForm(entity: string, form: HTMLFormElement, data: ManualDataResponse, keepOpen: boolean = false): Promise<JsonRecord> {
    const payload = formPayload(form);
    if (entity === "seasons") {
        payload.seasonIndex = Number(payload.seasonNumber) - 1;
        const team = resolveManualReference(data, "team", String(payload.managedTeamName || ""));
        if (team) payload.managedTeamEaId = team.ea_team_id;
    }
    if (entity === "competitions") {
        const ref = resolveManualReference(data, "competition", String(payload.competitionName || ""));
        if (ref) { payload.competitionObjectId = ref.competition_object_id; payload.staticCompetitionId = ref.static_competition_id; }
    }
    if (entity === "transactions") {
        const team = resolveManualReference(data, "team", String(payload.counterpartyTeamName || ""));
        if (team && !payload.counterpartyTeamEaId) payload.counterpartyTeamEaId = team.ea_team_id;
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
        if (team && !payload.teamEaId) payload.teamEaId = team.ea_team_id;
        if (league && !payload.leagueEaId) payload.leagueEaId = league.ea_league_id;
    }
    const saved = await api<JsonRecord>(`/api/careers/${state.careerId}/manual-data/${entity}/save`, { method: "POST", body: JSON.stringify(payload) });
    if (entity === "seasons") state.manualSeasonId = Number(saved.id);
    if (entity === "stats") state.manualDraftCompetitionId = Number(payload.competitionId);
    state.manualEditKind = keepOpen && entity === "stats" ? "stat" : keepOpen && entity === "transactions" ? "transaction" : null;
    state.manualEditId = null;
    clearApiCache();
    toast(saved.upsertedExisting ? "Existing record updated" : "Manual data saved");
    await renderManualData(); applyIcons(content); bindContent();
    if (keepOpen) $<HTMLInputElement>(entity === "stats" ? "#manualStatForm [name='displayName']" : "#manualTransactionForm [name='displayName']", content)?.focus();
    return saved;
}

function bindMovementManualEditor(): void {
    const form = $<HTMLFormElement>("#movementManualForm", content);
    if (!form) return;
    bindManualPlayerPicker(form); bindUnknownFee(form); bindManualKeyboard(form);
    $<HTMLButtonElement>("[data-movement-editor-cancel]", form)?.addEventListener("click", async () => {
        state.movementEditKind = null;
        state.movementEditId = null;
        if (state.route === "loans") await renderLoans(); else await renderTransfers();
        applyIcons(content); bindContent();
    });
    form.onsubmit = async event => {
        event.preventDefault();
        const payload = formPayload(form);
        const data = await api<ManualDataResponse>(`/api/careers/${state.careerId}/manual-data`);
        const team = resolveManualReference(data, "team", String(payload.counterpartyTeamName || ""));
        if (team && !payload.counterpartyTeamEaId) payload.counterpartyTeamEaId = team.ea_team_id;
        saveManualPreferences({direction:payload.direction,counterpartyTeamName:payload.counterpartyTeamName,feeUnknown:Boolean(payload.feeUnknown)});
        await api(`/api/careers/${state.careerId}/manual-data/transactions/save`, {method:"POST", body:JSON.stringify(payload)});
        state.movementEditKind = null;
        state.movementEditId = null;
        clearApiCache();
        toast(payload.transactionType === "loan" ? "Historical loan saved" : "Historical transfer saved");
        if (state.route === "loans") await renderLoans(); else await renderTransfers();
        applyIcons(content); bindContent();
    };
}

function bindManualPlayerPicker(form: HTMLFormElement): void {
    const input = $<HTMLInputElement>("[data-manual-player-search]", form);
    const hidden = $<HTMLInputElement>("[name='playerEaId']", form);
    const results = $<HTMLElement>("[data-manual-player-results]", form);
    const selection = $<HTMLElement>("[data-manual-player-selection]", form);
    if (!input || !hidden || !results || !selection) return;
    let timer = 0;
    let request = 0;
    const close = () => { results.hidden = true; results.innerHTML = ""; };
    input.addEventListener("input", () => {
        hidden.value = "";
        selection.textContent = "Custom name – not linked to an EA ID yet.";
        window.clearTimeout(timer);
        const query = input.value.trim();
        if (query.length < 2) { close(); return; }
        const currentRequest = ++request;
        timer = window.setTimeout(async () => {
            try {
                const rows = await api<JsonRecord[]>(`/api/careers/${state.careerId}/players/search?q=${encodeURIComponent(query)}&limit=40`);
                if (currentRequest !== request) return;
                results.innerHTML = rows.length ? rows.map(row => `<button type="button" data-player-result data-id="${row.ea_player_id ?? ""}" data-name="${esc(row.display_name)}"><strong>${esc(row.display_name)}</strong><span>${row.primary_position ? positionBadge(row.primary_position) : statusBadge("manual")} ${row.overall ? overallBadge(row.overall) : ""}</span><small>${esc(row.team_name || (row.source === "manual" ? "Recorded manually" : "Unknown club"))}${row.ea_player_id ? ` · EA-ID ${num(row.ea_player_id)}` : ""}</small></button>`).join("") : `<span class="muted">No matches. The name can still be saved as entered.</span>`;
                results.hidden = false;
                $$<HTMLButtonElement>("[data-player-result]", results).forEach(button => button.onclick = () => {
                    input.value = button.dataset.name || "";
                    hidden.value = button.dataset.id || "";
                    selection.textContent = hidden.value ? `Linked to EA ID ${hidden.value}` : "Manually entered player name";
                    close();
                });
            } catch (error) { close(); }
        }, 180);
    });
    input.addEventListener("blur", () => window.setTimeout(close, 180));
}

function bindManualData(data: ManualDataResponse): void {
    $$<HTMLButtonElement>("[data-manual-season]", content).forEach(button => button.onclick = async () => { state.manualSeasonId = Number(button.dataset.manualSeason); state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$<HTMLButtonElement>("[data-manual-tab]", content).forEach(button => button.onclick = async () => { state.manualTab = button.dataset.manualTab || "competitions"; state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$<HTMLButtonElement>("[data-manual-new]", content).forEach(button => button.onclick = async () => { state.manualEditKind = button.dataset.manualNew || null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$<HTMLButtonElement>("[data-manual-quick-toggle]", content).forEach(button => button.onclick = async () => { state.manualQuickEntry = !state.manualQuickEntry; state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$<HTMLButtonElement>("[data-manual-edit]", content).forEach(button => button.onclick = async () => { state.manualEditKind = button.dataset.manualEdit || null; state.manualEditId = Number(button.dataset.id); await renderManualData(); applyIcons(content); bindContent(); });
    $$<HTMLButtonElement>("[data-manual-cancel]", content).forEach(button => button.onclick = async () => { state.manualEditKind = null; state.manualEditId = null; await renderManualData(); applyIcons(content); bindContent(); });
    $$<HTMLButtonElement>("[data-manual-delete]", content).forEach(button => button.onclick = async () => {
        const entity = button.dataset.manualDelete || "";
        if (!confirm("Delete this manual record? Related manual entries will also be removed.")) return;
        try {
            await api(`/api/careers/${state.careerId}/manual-data/${entity}/delete`, { method: "POST", body: JSON.stringify({ id: Number(button.dataset.id) }) });
            if (entity === "seasons" && Number(button.dataset.id) === Number(state.manualSeasonId)) state.manualSeasonId = null;
            state.manualEditKind = null; state.manualEditId = null; clearApiCache(); toast("Manual record deleted");
            await renderManualData(); applyIcons(content); bindContent();
        } catch (error) { toast(error instanceof Error ? error.message : String(error)); }
    });
    $$<HTMLButtonElement>("[data-manual-backup]", content).forEach(button => button.onclick = async () => {
        try { const result = await api<JsonRecord>("/api/backups/create", { method: "POST", body: JSON.stringify({ label: "manual_history" }) }); clearApiCache(); toast(`Backup created: ${result.name}`); await renderManualData(); applyIcons(content); bindContent(); }
        catch (error) { toast(error instanceof Error ? error.message : String(error)); }
    });
    const seasonForm = $<HTMLFormElement>("#manualSeasonForm", content);
    if (seasonForm) seasonForm.onsubmit = async event => { event.preventDefault(); try { await saveManualForm("seasons", seasonForm, data); } catch (error) { toast(error instanceof Error ? error.message : String(error)); } };
    const competitionForm = $<HTMLFormElement>("#manualCompetitionForm", content);
    if (competitionForm) competitionForm.onsubmit = async event => { event.preventDefault(); try { await saveManualForm("competitions", competitionForm, data); } catch (error) { toast(error instanceof Error ? error.message : String(error)); } };
    const statForm = $<HTMLFormElement>("#manualStatForm", content);
    if (statForm) {
        bindManualPlayerPicker(statForm);
        $<HTMLSelectElement>("[name='competitionId']", statForm)?.addEventListener("change", event => state.manualDraftCompetitionId = Number((event.target as HTMLSelectElement).value));
        statForm.onsubmit = async event => { event.preventDefault(); try { await saveManualForm("stats", statForm, data); } catch (error) { toast(error instanceof Error ? error.message : String(error)); } };
        $<HTMLButtonElement>("[data-manual-save-next]", statForm)?.addEventListener("click", async () => { try { await saveManualForm("stats", statForm, data, true); } catch (error) { toast(error instanceof Error ? error.message : String(error)); } });
    }
    const quickStatsForm = $<HTMLFormElement>("#manualQuickStatsForm", content);
    if (quickStatsForm) {
        const competition = $<HTMLSelectElement>("[name='competitionId']", quickStatsForm);
        $$<HTMLElement>("[data-quick-stat-row]", quickStatsForm).forEach(row => bindManualPlayerPicker(row as unknown as HTMLFormElement));
        competition?.addEventListener("change", () => { state.manualDraftCompetitionId = Number(competition.value); saveManualPreferences({competitionId:Number(competition.value)}); });
        quickStatsForm.onsubmit = async event => {
            event.preventDefault();
            const rows = $$<HTMLElement>("[data-quick-stat-row]", quickStatsForm);
            const payloads = rows.map(row => ({
                competitionId: Number(competition?.value),
                playerEaId: $<HTMLInputElement>("[name='playerEaId']", row)?.value || null,
                displayName: $<HTMLInputElement>("[name='displayName']", row)?.value.trim() || "",
                appearances: $<HTMLInputElement>("[name='appearances']", row)?.value || "0",
                goals: $<HTMLInputElement>("[name='goals']", row)?.value || "0",
                assists: $<HTMLInputElement>("[name='assists']", row)?.value || "0",
                cleanSheets: $<HTMLInputElement>("[name='cleanSheets']", row)?.value || "0",
                averageRating: $<HTMLInputElement>("[name='averageRating']", row)?.value || null,
            })).filter(row => row.displayName);
            if (!payloads.length) { toast("Complete at least one player row"); return; }
            try {
                for (const payload of payloads) await api(`/api/careers/${state.careerId}/manual-data/stats/save`, {method:"POST",body:JSON.stringify(payload)});
                state.manualDraftCompetitionId = Number(competition?.value); saveManualPreferences({competitionId:state.manualDraftCompetitionId});
                clearApiCache(); toast(`${payloads.length} statistics row${payloads.length === 1 ? "" : "n"} saved`); await renderManualData(); applyIcons(content); bindContent();
            } catch (error) { toast(error instanceof Error ? error.message : String(error)); }
        };
        bindManualKeyboard(quickStatsForm);
    }
    const transactionForm = $<HTMLFormElement>("#manualTransactionForm", content);
    if (transactionForm) {
        bindManualPlayerPicker(transactionForm); bindUnknownFee(transactionForm);
        transactionForm.onsubmit = async event => { event.preventDefault(); try { await saveManualForm("transactions", transactionForm, data); } catch (error) { toast(error instanceof Error ? error.message : String(error)); } };
        const saveNext = $<HTMLButtonElement>("[data-manual-save-next]", transactionForm);
        saveNext?.addEventListener("click", async () => { try { await saveManualForm("transactions", transactionForm, data, true); } catch (error) { toast(error instanceof Error ? error.message : String(error)); } });
        bindManualKeyboard(transactionForm, saveNext);
    }
    const leagueFinishForm = $<HTMLFormElement>("#manualLeagueFinishForm", content);
    if (leagueFinishForm) leagueFinishForm.onsubmit = async event => { event.preventDefault(); try { await saveManualForm("league-finishes", leagueFinishForm, data); } catch (error) { toast(error instanceof Error ? error.message : String(error)); } };

    [seasonForm, competitionForm, statForm, leagueFinishForm].forEach(form => { if (form) bindManualKeyboard(form, $<HTMLElement>("[data-manual-save-next]", form)); });
}

function playerManualEditor(data: any, player: any): string {
    const editor = data.manualEditor || { seasons: [], competitions: [], stats: [] };
    if (!editor.seasons.length) return `<section class="card pad"><h3 class="card-title">Add historical statistics</h3><p class="muted">Create a season and its competitions under Historical data first.</p><button class="button" data-route="manual-data">Open historical data</button></section>`;
    const usableSeasons = editor.seasons.filter((season: any) => editor.competitions.some((competition: any) => Number(competition.manual_season_id) === Number(season.id)));
    if (!usableSeasons.length) return `<section class="card pad"><h3 class="card-title">Add historical statistics</h3><p class="muted">The available historical seasons do not have competitions yet.</p><button class="button" data-route="manual-data">Create competitions</button></section>`;
    const prefs = manualPreferences();
    const firstSeason = usableSeasons.find((season:any)=>Number(season.id)===Number(prefs.playerStatSeasonId)) || usableSeasons[0];
    const preferredCompetition = editor.competitions.find((competition:any)=>Number(competition.id)===Number(prefs.competitionId) && Number(competition.manual_season_id)===Number(firstSeason.id));
    return `<section class="card pad manual-editor-card player-manual-editor"><h3 class="card-title">Add statistics directly</h3><p class="muted">The player is already selected. Choose a season and competition, enter values, and save.</p>
      <form id="playerManualStatForm" class="manual-form"><input type="hidden" name="id"><input type="hidden" name="playerEaId" value="${player.ea_player_id}"><input type="hidden" name="displayName" value="${esc(player.display_name)}">
        <div class="manual-form-grid"><label><span>Season</span><select name="seasonId">${usableSeasons.map((s: any) => `<option value="${s.id}" ${Number(s.id)===Number(firstSeason.id)?"selected":""}>${esc(manualSeasonTitle(s))}</option>`).join("")}</select></label><label><span>Competition</span><select name="competitionId" required>${editor.competitions.filter((c: any) => Number(c.manual_season_id) === Number(firstSeason.id)).map((c: any) => `<option value="${c.id}" ${Number(c.id)===Number(preferredCompetition?.id)?"selected":""}>${esc(c.competition_name)}</option>`).join("")}</select></label>
          <label><span>Matches</span><input name="appearances" type="number" min="0" max="999" value="0"></label><label><span>Goals</span><input name="goals" type="number" min="0" max="999" value="0"></label><label><span>Assists</span><input name="assists" type="number" min="0" max="999" value="0"></label><label><span>Clean sheets</span><input name="cleanSheets" type="number" min="0" max="999" value="0"></label><label><span>Avg. rating</span><input name="averageRating" inputmode="decimal" placeholder="7,25"></label><label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="1000"></textarea></label></div>
        <div class="manual-form-actions"><small>The selection is remembered for the next player · Ctrl+Enter saves</small><button type="button" class="button" data-player-stat-reset>Clear</button><button type="submit" class="button primary"><span data-icon="save"></span>Save statistics</button></div></form>
      ${editor.stats.length ? `<div class="player-manual-existing"><h4>Existing manual entries</h4>${table([{ label: "Season" }, { label: "Competition" }, { label: "Apps", cls: "num" }, { label: "G", cls: "num" }, { label: "A", cls: "num" }, { label: "CS", cls: "num" }, { label: "Avg. rating", cls: "num" }, { label: "Actions", sortable: false }], editor.stats.map((s: any) => `<tr><td>${esc(s.season_label)}</td><td>${esc(s.competition_name)}</td><td class="num">${num(s.appearances)}</td><td class="num">${num(s.goals)}</td><td class="num">${num(s.assists)}</td><td class="num">${num(s.clean_sheets)}</td><td class="num">${ratingValue(s.average_rating, true)}</td><td><button class="entity-link" data-player-stat-edit="${s.id}">Edit</button> <button class="entity-link danger-link" data-player-stat-delete="${s.id}">Delete</button></td></tr>`))}</div>` : ""}
    </section>`;
}

function bindPlayerManualEditor(data: any, player: any): void {
    const editor = data.manualEditor || { seasons: [], competitions: [], stats: [] };
    const form = $<HTMLFormElement>("#playerManualStatForm", content);
    if (!form) return;
    const seasonSelect = $<HTMLSelectElement>("[name='seasonId']", form);
    const competitionSelect = $<HTMLSelectElement>("[name='competitionId']", form);
    const fillCompetitions = (seasonId: number, selectedId?: number) => {
        const rows = editor.competitions.filter((c: any) => Number(c.manual_season_id) === seasonId);
        competitionSelect.innerHTML = rows.map((c: any) => `<option value="${c.id}" ${Number(c.id) === Number(selectedId) ? "selected" : ""}>${esc(c.competition_name)}</option>`).join("");
    };
    seasonSelect.onchange = () => { fillCompetitions(Number(seasonSelect.value)); saveManualPreferences({playerStatSeasonId:Number(seasonSelect.value)}); };
    competitionSelect.onchange = () => saveManualPreferences({competitionId:Number(competitionSelect.value),playerStatSeasonId:Number(seasonSelect.value)});
    const reset = () => {
        ($<HTMLInputElement>("[name='id']", form)).value = "";
        for (const name of ["appearances", "goals", "assists", "cleanSheets"]) ($<HTMLInputElement>(`[name='${name}']`, form)).value = "0";
        ($<HTMLInputElement>("[name='averageRating']", form)).value = "";
        ($<HTMLTextAreaElement>("[name='notes']", form)).value = "";
    };
    $<HTMLButtonElement>("[data-player-stat-reset]", form).onclick = reset;
    $$<HTMLButtonElement>("[data-player-stat-edit]", content).forEach(button => button.onclick = () => {
        const stat = editor.stats.find((s: any) => Number(s.id) === Number(button.dataset.playerStatEdit));
        if (!stat) return;
        ($<HTMLInputElement>("[name='id']", form)).value = String(stat.id);
        seasonSelect.value = String(stat.manual_season_id); fillCompetitions(Number(stat.manual_season_id), Number(stat.manual_competition_id));
        ($<HTMLInputElement>("[name='appearances']", form)).value = String(stat.appearances || 0);
        ($<HTMLInputElement>("[name='goals']", form)).value = String(stat.goals || 0);
        ($<HTMLInputElement>("[name='assists']", form)).value = String(stat.assists || 0);
        ($<HTMLInputElement>("[name='cleanSheets']", form)).value = String(stat.clean_sheets || 0);
        ($<HTMLInputElement>("[name='averageRating']", form)).value = stat.average_rating ?? "";
        ($<HTMLTextAreaElement>("[name='notes']", form)).value = stat.notes || "";
        form.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $$<HTMLButtonElement>("[data-player-stat-delete]", content).forEach(button => button.onclick = async () => {
        if (!confirm("Delete this manual statistics record?")) return;
        try { await api(`/api/careers/${state.careerId}/manual-data/stats/delete`, { method: "POST", body: JSON.stringify({ id: Number(button.dataset.playerStatDelete) }) }); clearApiCache(); toast("Statistics deleted"); await renderPlayer(); applyIcons(content); bindContent(); }
        catch (error) { toast(error instanceof Error ? error.message : String(error)); }
    });
    form.onsubmit = async event => {
        event.preventDefault();
        try {
            const payload = formPayload(form);
            saveManualPreferences({competitionId:Number(payload.competitionId),playerStatSeasonId:Number(payload.seasonId)});
            const saved = await api<JsonRecord>(`/api/careers/${state.careerId}/manual-data/stats/save`, { method: "POST", body: JSON.stringify(payload) });
            clearApiCache(); toast(saved.upsertedExisting ? "Existing statistics updated" : "Statistics saved");
            await renderPlayer(); applyIcons(content); bindContent();
        } catch (error) { toast(error instanceof Error ? error.message : String(error)); }
    };
    bindManualKeyboard(form);
}

function developmentStageLabel(row: any): string {
    return row.stage_label || ({season_start:"Season start", season_mid:"Mid-season", season_end:"Season end", custom:"Custom point"} as Record<string,string>)[row.stage] || "Custom point";
}

function playerDevelopmentEditor(data: any, player: any): string {
    const editor = data.manualEditor || { seasons: [], development: [] };
    if (!editor.seasons?.length) return `<section class="card pad"><h3 class="card-title">Add historical development</h3><p class="muted">No imported or manual season is available for this career yet.</p></section>`;
    const prefs = manualPreferences();
    return `<section class="card pad manual-editor-card player-development-editor"><h3 class="card-title">Add OVR and POT</h3><p class="muted">Imported and manual seasons are available together. The last season and point selection is remembered.</p>
      <form id="playerDevelopmentForm" class="manual-form"><input type="hidden" name="id"><input type="hidden" name="playerEaId" value="${player.ea_player_id}"><input type="hidden" name="displayName" value="${esc(player.display_name)}">
        <div class="manual-form-grid"><label><span>Season</span><select name="seasonSelection">${editor.seasons.map((s:any)=>{const value=s.selection_value||`manual:${s.id}`;return `<option value="${esc(value)}" ${String(value)===String(prefs.developmentSeasonSelection||"")?"selected":""}>${esc(manualSeasonTitle(s))} · ${esc(s.source_label || "Season")}</option>`;}).join("")}</select></label><label><span>Point</span><select name="stage"><option value="season_start" ${prefs.developmentStage==="season_start"?"selected":""}>Season start</option><option value="season_mid" ${prefs.developmentStage==="season_mid"?"selected":""}>Mid-season</option><option value="season_end" ${prefs.developmentStage==="season_end"?"selected":""}>Season end</option><option value="custom" ${prefs.developmentStage==="custom"?"selected":""}>Custom date</option></select></label><label><span>Label</span><input name="stageLabel" maxlength="80" placeholder="e.g. before the winter break"></label><label><span>Effective date</span><input name="effectiveDate" type="date"><small>Optional for standard points.</small></label><label><span>OVR</span><input name="overall" type="number" min="1" max="99" required value="${rawNumber(player.overall)}"></label><label><span>POT</span><input name="potential" type="number" min="1" max="99" required value="${rawNumber(player.potential)}"></label><label class="span-2"><span>Notes</span><textarea name="notes" rows="2" maxlength="1000"></textarea></label></div>
        <div class="manual-form-actions"><small>Ctrl+Enter saves</small><button type="button" class="button" data-player-development-reset>Clear</button><button type="submit" class="button primary"><span data-icon="save"></span>Save development</button></div></form>
      ${editor.development?.length ? `<div class="player-manual-existing"><h4>Manual development points</h4>${table([{label:"Season"},{label:"Point"},{label:"Effective date"},{label:"OVR",cls:"center"},{label:"POT",cls:"center"},{label:"Actions",sortable:false}], editor.development.map((row:any)=>`<tr><td>${esc(row.season_label)}</td><td>${esc(developmentStageLabel(row))}</td><td>${dateText(row.effective_date)}</td><td class="center">${overallBadge(row.overall)}</td><td class="center">${overallBadge(row.potential)}</td><td><button class="entity-link" data-player-development-edit="${row.id}">Edit</button> <button class="entity-link danger-link" data-player-development-delete="${row.id}">Delete</button></td></tr>`))}</div>` : ""}
    </section>`;
}

function bindPlayerDevelopmentEditor(data: any, player: any): void {
    const editor = data.manualEditor || { seasons: [], development: [] };
    const form = $<HTMLFormElement>("#playerDevelopmentForm", content);
    if (!form) return;
    const stageSelect = $<HTMLSelectElement>("[name='stage']", form);
    const labelInput = $<HTMLInputElement>("[name='stageLabel']", form);
    const dateInput = $<HTMLInputElement>("[name='effectiveDate']", form);
    const updateStage = () => {
        const defaults: Record<string,string> = {season_start:"Season start",season_mid:"Mid-season",season_end:"Season end"};
        if (stageSelect.value !== "custom" && (!labelInput.value || Object.values(defaults).includes(labelInput.value))) labelInput.value = defaults[stageSelect.value] || "";
        dateInput.required = stageSelect.value === "custom";
    };
    const seasonSelection = $<HTMLSelectElement>("[name='seasonSelection']", form);
    stageSelect.onchange = () => { updateStage(); saveManualPreferences({developmentStage:stageSelect.value}); };
    seasonSelection.onchange = () => saveManualPreferences({developmentSeasonSelection:seasonSelection.value});
    const reset = () => {
        ($<HTMLInputElement>("[name='id']", form)).value = "";
        stageSelect.value = "season_start";
        labelInput.value = "Season start";
        dateInput.value = "";
        ($<HTMLInputElement>("[name='overall']", form)).value = String(player.overall || "");
        ($<HTMLInputElement>("[name='potential']", form)).value = String(player.potential || "");
        ($<HTMLTextAreaElement>("[name='notes']", form)).value = "";
        updateStage();
    };
    updateStage();
    $<HTMLButtonElement>("[data-player-development-reset]", form).onclick = reset;
    $$<HTMLButtonElement>("[data-player-development-edit]", content).forEach(button => button.onclick = () => {
        const row = editor.development.find((item:any)=>Number(item.id)===Number(button.dataset.playerDevelopmentEdit));
        if (!row) return;
        ($<HTMLInputElement>("[name='id']", form)).value = String(row.id);
        ($<HTMLSelectElement>("[name='seasonSelection']", form)).value = `manual:${row.manual_season_id}`;
        stageSelect.value = row.stage;
        labelInput.value = developmentStageLabel(row);
        dateInput.value = row.effective_date || "";
        ($<HTMLInputElement>("[name='overall']", form)).value = String(row.overall);
        ($<HTMLInputElement>("[name='potential']", form)).value = String(row.potential);
        ($<HTMLTextAreaElement>("[name='notes']", form)).value = row.notes || "";
        updateStage();
        form.scrollIntoView({behavior:"smooth",block:"start"});
    });
    $$<HTMLButtonElement>("[data-player-development-delete]", content).forEach(button => button.onclick = async () => {
        if (!confirm("Delete this manual development point?")) return;
        try { await api(`/api/careers/${state.careerId}/manual-data/development/delete`, {method:"POST",body:JSON.stringify({id:Number(button.dataset.playerDevelopmentDelete)})}); clearApiCache(); toast("Development point deleted"); await renderPlayer(); applyIcons(content); bindContent(); }
        catch (error) { toast(error instanceof Error ? error.message : String(error)); }
    });
    form.onsubmit = async event => {
        event.preventDefault();
        try { const payload=formPayload(form); saveManualPreferences({developmentStage:payload.stage,developmentSeasonSelection:payload.seasonSelection}); const saved=await api<JsonRecord>(`/api/careers/${state.careerId}/manual-data/development/save`,{method:"POST",body:JSON.stringify(payload)}); clearApiCache(); toast(saved.upsertedExisting ? "Existing development point updated" : "Development point saved"); await renderPlayer(); applyIcons(content); bindContent(); }
        catch (error) { toast(error instanceof Error ? error.message : String(error)); }
    };
    bindManualKeyboard(form);
}
