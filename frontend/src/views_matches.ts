async function renderMatchCenter() { const d = await api(`/api/snapshots/${state.snapshotId}/matches`), recent = d.completed.slice(-5).reverse(), upcoming = d.upcoming.slice(0, 5), form = d.completed.slice(-10).map((m: any) => resultCode(m.managed_team_result)); const next = upcoming[0]; content.innerHTML = `<div class="content-inner">${pageHead("Match Center", "Schedule, results and available match data", `<button class="button" data-route="schedule">Schedule</button><button class="button" data-route="results">Results</button>`)}<div class="grid metrics">${metric("Played", num(d.completed.length), "completed matches")}${metric("Open", num(d.upcoming.length), "upcoming matches", "blue")}${metric("Last 5", form.slice(-5).map(resultPill).join(" "), "across all competitions")}${metric("Last 10", form.map((c: any) => c).join(" · "), "Form sequence")}${metric("Competitions", num(d.competitions.length), "featuring your club", "green")}</div>${next ? `<section class="card fixture-hero"><div class="fixture-meta">NEXT MATCH · ${competitionLink(next.competition_object_id, next.competition_name)} · ${dateText(next.date)} ${esc(timeText(next.time))}</div><div class="fixture-scoreboard"><div class="fixture-club">${identityLogo(next.homeIdentity, next.home_team_name, "fixture-club-logo")}<h2>${clubLink(next.home_team_ea_id, next.home_team_name)}</h2></div><div class="fixture-score">VS<small>${matchLink(next.fixture_id, "Open match")}</small></div><div class="fixture-club">${identityLogo(next.awayIdentity, next.away_team_name, "fixture-club-logo")}<h2>${clubLink(next.away_team_ea_id, next.away_team_name)}</h2></div></div></section>` : ""}<div class="grid two-col" style="margin-top:14px"><section class="card"><header class="card-header"><h2>Recent results</h2><button class="entity-link" data-route="results">All</button></header>${renderMatchRows(recent)}</section><section class="card"><header class="card-header"><h2>Upcoming matches</h2><button class="entity-link" data-route="schedule">All</button></header>${renderMatchRows(upcoming)}</section></div><section class="card" style="margin-top:14px"><header class="card-header"><h2>Competition status</h2></header><div class="card-body grid competition-grid">${d.competitions.map((c: any) => `<button class="competition-card card" data-competition="${c.competition_object_id}"><div class="competition-top">${identityLogo(c.identity, c.competition_name, "competition-logo-card")}<div><h3>${esc(c.competition_name)}</h3><p>${num(c.completed)} of ${num(c.total)} completed</p></div></div></button>`).join("")}</div></section></div>`; }
async function renderMatchList(mode: any) {
    const d = await api(`/api/snapshots/${state.snapshotId}/matches`);
    const source = mode === "results" ? d.completed.slice().reverse() : d.upcoming;
    const comps: JsonRecord[] = Array.from(new Map<number, JsonRecord>(d.competitions.map((c: JsonRecord) => [Number(c.competition_object_id), c] as [number, JsonRecord])).values());
    const rows = state.matchCompetition === "all" ? source : source.filter((m: any) => String(m.competition_object_id) === String(state.matchCompetition));
    const title = mode === "results" ? "Results" : "Schedule";
    const subtitle = mode === "results" ? "All completed matches for the managed club" : "All upcoming and open matches";
    content.innerHTML = `<div class="content-inner wide">${pageHead(title, subtitle, `<button class="button" data-route="match-center">Match Center</button>`)}
      <div class="filter-row"><select id="matchCompetition" class="filter-select"><option value="all">All competitions</option>${comps.map((c: any) => `<option value="${c.competition_object_id}" ${String(state.matchCompetition) === String(c.competition_object_id) ? "selected" : ""}>${esc(c.competition_name)}</option>`).join("")}</select><span class="chip">${num(rows.length)} matches</span></div>
      <section class="card">${table([
        { label: "Date" }, { label: "Competition" }, { label: "Home" }, { label: "Result", cls: "center" },
        { label: "Away" }, { label: "Status", cls: "center" }, { label: "" }
      ], rows.map((m: any) => `<tr>
        <td data-sort="${esc(m.date || "")}">${dateText(m.date)} <span class="muted">${esc(timeText(m.time))}</span></td>
        <td><span class="inline-identity">${identityLogo(m.competitionIdentity, m.competition_name, "inline-logo")}${competitionLink(m.competition_object_id, m.competition_name)}</span></td>
        <td><span class="inline-identity">${identityLogo(m.homeIdentity, m.home_team_name, "table-club-logo")}${clubLink(m.home_team_ea_id, m.home_team_name)}</span></td>
        <td class="center"><b>${m.is_completed ? `${num(m.home_score)} : ${num(m.away_score)}` : "–"}</b></td>
        <td><span class="inline-identity">${identityLogo(m.awayIdentity, m.away_team_name, "table-club-logo")}${clubLink(m.away_team_ea_id, m.away_team_name)}</span></td>
        <td class="center">${m.is_completed ? resultPill(m.managed_team_result) : statusBadge("Scheduled")}${m.detailedStatsAvailable ? `<small class="table-subline">${statusBadge("FC26 Detail","good")}</small>` : ""}</td>
        <td>${matchLink(m.fixture_id, "Details")}</td>
      </tr>`))}</section></div>`;
    $("#matchCompetition", content).onchange = (e: any) => { state.matchCompetition = e.target.value; renderMatchList(mode); };
}
const detailedStatLabels:Record<string,string>={
    goals_derived:"Goals",assists:"Assists",npk_expected_goals:"NPK-xG",expected_assists:"xA",shots:"Shots",shots_on_target:"Shots on target",shots_off_target_derived:"Off target",shots_blocked:"Blocked shots",key_passes:"Key passes",assists_from_shots:"Shot Assists",assists_from_dummy:"Dummy Assists",fk_goals:"Free-kick goals",pk_goals:"Penalty goals",offsides:"Offsides",offsides_caused:"Offsides caused",corners_won:"Corners won",
    passes:"Passes",passes_completed:"Completed passes",pass_accuracy_pct_derived:"Pass accuracy",passes_under_pressure:"Passes under pressure",passes_completed_under_pressure:"Completed passes under pressure",offside_passes:"Offside passes",passes_intercepted:"Passes intercepted",crosses_attempted:"Crosses",crosses_delivered:"Completed crosses",crosses_blocked:"Blocked crosses",cross_success_pct_derived:"Cross success",
    dribbles:"Dribbles",dribbles_completed:"Successful dribbles",dribbles_failed_derived:"Failed dribbles",dribble_success_pct_derived:"Dribble success",skillmove_beats:"Beaten with a skill move",nutmegs:"Nutmegs",knock_ons:"Knock-ons",beaten_by_opponent:"Beaten by opponent",beaten_in_defensive_third:"Beaten in defensive third",beaten_in_box:"Beaten in the box",tackled_by_opponent:"Tackled by opponent",beat_with_pass:"Beaten by a pass",
    tackles:"Tackles",stand_tackles:"Standing tackles",stand_tackles_won:"Standing tackles won",stand_tackle_success_pct_derived:"Standing tackle success",slide_tackles:"Sliding tackles",slide_tackles_won:"Sliding tackles won",slide_tackle_success_pct_derived:"Sliding tackle success",interceptions:"Interceptions",blocks:"Blocks",clearances:"Clearances",possession_won:"Possession won",possession_lost:"Possession lost",
    opense_duels_attempted:"Attacking duels",offense_duels_won:"Attacking duels won",offense_duel_success_pct_derived:"Attacking duel success",defense_duels_attempted:"Defensive duels",defense_duels_won:"Defensive duels won",defense_duel_success_pct_derived:"Defensive duel success",aerial_duels_attempted:"Aerial duels",aerial_duels_won:"Aerial duels won",aerial_duel_success_pct_derived:"Aerial duel success",
    fouls_committed:"Fouls",fouls_won:"Fouls won",yellow_card_events:"Yellow cards",red_dismissals:"Red cards",penalties_committed:"Penalties conceded",penalties_won:"Penalties won",
    saves:"Saves",shots_against:"Shots faced",saving_shots_on_target:"Shots on target faced",save_success_pct_derived:"Save percentage",penalty_saves:"Penalty saves",shootout_saves:"Shoot-out saves",punches:"Punches",dives_at_feet:"Dives at feet",saving_crosses:"Crosses claimed",save_punch_to_clearance:"Punch to clearance",goals_conceded:"Goals conceded",penalty_goals_conceded:"Penalty goals conceded",shootout_goals_conceded:"Shootout goals conceded"
};
const detailedStatGroups:any[]=[
    {label:"Attack & chances",keys:["goals_derived","assists","npk_expected_goals","expected_assists","shots","shots_on_target","shots_off_target_derived","shots_blocked","key_passes","fk_goals","pk_goals","offsides","corners_won"]},
    {label:"Passing & creation",keys:["passes","passes_completed","pass_accuracy_pct_derived","passes_under_pressure","passes_completed_under_pressure","crosses_attempted","crosses_delivered","cross_success_pct_derived"]},
    {label:"Dribbling & possession",keys:["dribbles","dribbles_completed","dribble_success_pct_derived","skillmove_beats","nutmegs","possession_won","possession_lost","beaten_by_opponent","beat_with_pass"]},
    {label:"Defending",keys:["tackles","stand_tackles","stand_tackles_won","stand_tackle_success_pct_derived","slide_tackles","slide_tackles_won","slide_tackle_success_pct_derived","interceptions","blocks","clearances"]},
    {label:"Duels",keys:["offense_duels_attempted","offense_duels_won","offense_duel_success_pct_derived","defense_duels_attempted","defense_duels_won","defense_duel_success_pct_derived","aerial_duels_attempted","aerial_duels_won","aerial_duel_success_pct_derived"]},
    {label:"Discipline",keys:["fouls_committed","fouls_won","yellow_card_events","red_dismissals","penalties_committed","penalties_won"]},
    {label:"Goalkeeping",keys:["saves","shots_against","saving_shots_on_target","save_success_pct_derived","penalty_saves","shootout_saves","punches","dives_at_feet","saving_crosses","goals_conceded"]}
];
function detailedStatText(key:string,value:any):string {
    if(value==null||value==="") return "–";
    if(key.includes("pct")) return `${num(value,1)} %`;
    if(key==="npk_expected_goals"||key==="expected_assists") return num(value,2);
    return num(value,Number(value)%1?2:0);
}
function detailedPlayerDrawer(p:any,analysis=""):string {
    const s=p.detailedStats||{};
    if(!Object.keys(s).length&&!analysis) return "";
    const context=[
      ["xG+xA /90",s.xg_plus_xa_per90==null?"–":num(s.xg_plus_xa_per90,2)],
      ["xG per shot",s.xg_per_shot==null?"–":num(s.xg_per_shot,3)],
      ["Passes under pressure",s.pressure_pass_accuracy_pct==null?"–":`${num(s.pressure_pass_accuracy_pct,1)} %`],
      ["Duels",s.combined_duel_success_pct==null?"–":`${num(s.combined_duel_success_pct,1)} %`],
      ["Possession balance",Number(s.possession_balance)>=0?`+${num(s.possession_balance)}`:num(s.possession_balance)]
    ];
    return `<details class="match-player-details"><summary>Match profile & all metrics</summary>${analysis}<div class="match-context-strip">${context.map((x:any)=>`<div><span>${esc(x[0])}</span><strong>${esc(x[1])}</strong></div>`).join("")}</div><div class="detailed-stat-groups">${detailedStatGroups.map((g:any)=>{const items=g.keys.filter((k:string)=>s[k]!=null);return items.length?`<div class="detailed-stat-group"><h4>${esc(g.label)}</h4>${items.map((k:string)=>`<div><span>${esc(detailedStatLabels[k]||k)}</span><strong>${detailedStatText(k,s[k])}</strong></div>`).join("")}</div>`:"";}).join("")}</div></details>`;
}
function matchComparisonRow(label:string,left:any,right:any,format:(v:any)=>string=(v:any)=>num(v)):string {
    const hasLeft=left!=null&&Number.isFinite(Number(left)),hasRight=right!=null&&Number.isFinite(Number(right));
    const lv=hasLeft?Number(left):0,rv=hasRight?Number(right):0,max=Math.max(lv,rv,0.0001);
    const bars=hasLeft&&hasRight?`<div class="match-stat-bars"><i class="home" style="width:${Math.max(2,lv/max*100)}%"></i><i class="away" style="width:${Math.max(2,rv/max*100)}%"></i></div>`:`<small class="match-stat-unavailable">Comparison unavailable for one or both teams</small>`;
    return `<div class="match-stat-row"><strong class="left">${left==null?"–":format(left)}</strong><div class="match-stat-label"><span>${esc(label)}</span>${bars}</div><strong>${right==null?"–":format(right)}</strong></div>`;
}

async function renderMatch() {
    const d = await api(`/api/snapshots/${state.snapshotId}/matches/${Number(state.routeData.id)}`), m = d.match;
    const stadium = d.stadium, detailed=d.detailedStats||{}, hasDetailed=!!detailed.available;
    const stadiumSection = stadium ? `<section class="card stadium-match-card"><header class="card-header"><div><h2>${esc(stadium.name || "Stadium")}</h2><p>${d.stadiumSource === "fixture" ? "Stadium exported for this match" : "Home stadium fallback — the actual venue may differ for neutral finals"}</p></div><div class="row-actions">${statusBadge(stadium.stadiumTypeLabel || "Unknown type", stadium.stadiumType === "authentic" ? "good" : stadium.stadiumType === "generic" ? "blue" : "")}${statusBadge(d.stadiumSource === "fixture" ? "Fixture data" : "Fallback", d.stadiumSource === "fixture" ? "good" : "")}</div></header><div class="stadium-gallery">${(stadium.variants || []).length ? (stadium.variants || []).map((variant: any, index: any) => `<figure class="stadium-variant ${index === 0 ? "primary" : ""}">${mediaImg(variant, stadium.name, "stadium-match-image", false)}<figcaption>Variant ${esc(variant.variant || index + 1)}</figcaption></figure>`).join("") : `<div class="card-body muted">A stadium is assigned, but no image has been imported yet.</div>`}</div></section>` : "";
    const teamById=new Map<number,any>((detailed.teams||[]).map((t:any)=>[Number(t.teamEaId),t] as [number,any]));
    const homeStats=(teamById.get(Number(m.home_team_ea_id))||{}).stats||{}, awayStats=(teamById.get(Number(m.away_team_ea_id))||{}).stats||{};
    const statComparisons:[string,any,any,(v:any)=>string][]=[];
    statComparisons.push(["Team-xG",homeStats.expected_goals_derived,awayStats.expected_goals_derived,(v:any)=>num(v,2)]);
    statComparisons.push(["NPK-xG",homeStats.npk_expected_goals,awayStats.npk_expected_goals,(v:any)=>num(v,2)]);
    statComparisons.push(["NPK-xG per shot",homeStats.xg_per_shot,awayStats.xg_per_shot,(v:any)=>num(v,3)]);
    statComparisons.push(["xA",homeStats.expected_assists,awayStats.expected_assists,(v:any)=>num(v,2)]);
    statComparisons.push(["Shots",homeStats.shots,awayStats.shots,(v:any)=>num(v)]);
    statComparisons.push(["On target",homeStats.shots_on_target,awayStats.shots_on_target,(v:any)=>num(v)]);
    statComparisons.push(["Passes",homeStats.passes,awayStats.passes,(v:any)=>num(v)]);
    statComparisons.push(["Pass accuracy",homeStats.pass_accuracy_pct_derived,awayStats.pass_accuracy_pct_derived,(v:any)=>`${num(v,1)} %`]);
    statComparisons.push(["Passes under pressure",homeStats.pressure_pass_accuracy_pct,awayStats.pressure_pass_accuracy_pct,(v:any)=>`${num(v,1)} %`]);
    statComparisons.push(["Key passes",homeStats.key_passes,awayStats.key_passes,(v:any)=>num(v)]);
    statComparisons.push(["Dribbles completed",homeStats.dribbles_completed,awayStats.dribbles_completed,(v:any)=>num(v)]);
    statComparisons.push(["Possession won",homeStats.possession_won,awayStats.possession_won,(v:any)=>num(v)]);
    statComparisons.push(["Possession lost",homeStats.possession_lost,awayStats.possession_lost,(v:any)=>num(v)]);
    statComparisons.push(["Interceptions",homeStats.interceptions,awayStats.interceptions,(v:any)=>num(v)]);
    statComparisons.push(["Tackles",homeStats.tackles,awayStats.tackles,(v:any)=>num(v)]);
    statComparisons.push(["Defensive duel success",homeStats.defense_duel_success_pct_derived,awayStats.defense_duel_success_pct_derived,(v:any)=>`${num(v,1)} %`]);
    statComparisons.push(["Aerial duels won",homeStats.aerial_duels_won,awayStats.aerial_duels_won,(v:any)=>num(v)]);
    statComparisons.push(["Fouls",homeStats.fouls_committed,awayStats.fouls_committed,(v:any)=>num(v)]);
    const comparisonRows=statComparisons.filter(([,left,right])=>left!=null||right!=null).map(([label,left,right,format])=>matchComparisonRow(label,left,right,format));
    const comparison=hasDetailed?`<section class="card match-comparison-card"><header class="card-header"><div><h2>Match statistics</h2><p>Direct FC26 match data · team xG augments the direct NPK-xG base only when penalty context is reliable</p></div></header><div class="match-comparison-head"><span>${esc(m.home_team_name)}</span><b>Comparison</b><span>${esc(m.away_team_name)}</span></div><div class="match-stat-comparison">${comparisonRows.join("")||'<p class="muted">No comparable team metrics were exported for this match.</p>'}</div><div class="data-note">${esc(detailed.xgNote||"")} ${esc(detailed.eventTimingNote||"")}</div></section>`:"";
    const eventNames=new Map(d.performances.map((p:any)=>[Number(p.player_ea_id),p.display_name]));
    const teamByIndex=new Map<number,any>((detailed.teams||[]).map((t:any)=>[Number(t.teamIndex),t] as [number,any]));
    const eventTeamName=(idx:any)=>{const team=teamByIndex.get(Number(idx)),id=Number(team?.teamEaId);return id===Number(m.home_team_ea_id)?m.home_team_name:id===Number(m.away_team_ea_id)?m.away_team_name:`Team ${num(Number(idx)+1)}`;};
    const events=hasDetailed?`<section class="card"><header class="card-header"><div><h2>Event overview</h2><p>Exported events — no inferred chronology or match minute</p></div></header><div class="match-event-grid">${(detailed.events||[]).length?(detailed.events||[]).map((e:any)=>`<div class="match-event ${esc(e.type)}"><span class="event-icon">${e.type==="yellow_card"?"▰":e.type==="red_card"?"■":e.type==="motm"?"★":e.type==="goal"||e.type==="penalty_goal"?"●":"•"}</span><div><strong>${esc(eventNames.get(Number(e.playerEaId))||e.displayName||`Player ${e.playerEaId}`)}</strong><small>${esc(e.label)}${Number(e.count)>1?` ×${num(e.count)}`:""}</small></div><span>${esc(eventTeamName(e.teamIndex))}</span></div>`).join(""):`<div class="card-body muted">No exported events for this match.</div>`}</div><div class="data-note">${esc(detailed.eventTimingNote||"")}</div></section>`:"";
    const matchPlayerAnalysisHtml=new Map<number,string>();
    const performanceRow=(p:any)=>{const s=p.detailedStats||p.reconstructedStats||{};const detailedRow=!!p.detailedStats;return `<tr>
        <td><div class="player-line">${playerPortrait(p.media,p.display_name,"table-portrait")}<div class="player-line-copy">${playerLink(p.player_ea_id,p.display_name)}${detailedPlayerDrawer(p,matchPlayerAnalysisHtml.get(Number(p.player_ea_id))||"")}</div></div></td>
        <td class="center" data-sort="${positionOrder(p.actual_position_source==='career_playermatchratinghistory_position'?p.actual_position:p.primary_position,p.primary_position_id)}">${p.actual_position_source==='career_playermatchratinghistory_position'?`${positionBadge(p.actual_position)}<small class="match-position-source">Observed</small>`:`${positionBadge(p.primary_position)}<small class="match-position-source">Registered · observed N/D</small>`}</td><td class="num">${num(s.minutes_played??p.minutes_played)}</td><td class="num"><b>${s.game_rating!=null?num(s.game_rating,1):p.rating?num(p.rating,1):"–"}</b></td>
        <td class="num">${detailedRow?`${num(s.goals_derived)}/${num(s.assists)}`:s.source?`${num(s.goals)}/${num(s.assists)}`:"–"}</td><td class="num">${detailedRow?num(s.npk_expected_goals,2):"–"}</td><td class="num">${detailedRow?num(s.expected_assists,2):"–"}</td><td class="num">${detailedRow?`${num(s.shots_on_target)}/${num(s.shots)}`:"–"}</td><td class="num">${detailedRow&&s.pass_accuracy_pct_derived!=null?`${num(s.pass_accuracy_pct_derived,1)} %`:"–"}</td><td class="num">${detailedRow?num(s.key_passes):"–"}</td><td class="num">${detailedRow?num(s.possession_won):"–"}</td><td class="num">${detailedRow?num(s.possession_lost):"–"}</td><td>${detailedRow?statusBadge("FC26 Detail","good"):s.source?statusBadge("Snapshot-Delta","blue"):statusBadge(p.join_status||"Direct")}</td></tr>`;};
    const performanceHeaders=[{label:"Player"},{label:"Pos.",cls:"center"},{label:"Min.",cls:"num"},{label:"Rating",cls:"num"},{label:"G/A",cls:"num"},{label:"NPK-xG",cls:"num"},{label:"xA",cls:"num"},{label:"SoT/Sh",cls:"num"},{label:"Pass %",cls:"num"},{label:"Key P.",cls:"num"},{label:"Ball +",cls:"num"},{label:"Ball -",cls:"num"},{label:"Source"}];
    const homeTeamId=Number(m.home_team_ea_id),awayTeamId=Number(m.away_team_ea_id),managedTeamId=Number(d.snapshot?.managed_team_ea_id);
    const primaryTeamId=managedTeamId===homeTeamId||managedTeamId===awayTeamId?managedTeamId:homeTeamId;
    const secondaryTeamId=primaryTeamId===homeTeamId?awayTeamId:homeTeamId;
    const teamName=(id:number)=>id===homeTeamId?m.home_team_name:id===awayTeamId?m.away_team_name:`Team ${id}`;
    const performanceTeam=(p:any)=>Number(p.match_team_ea_id??p.team_ea_id);
    const primaryPerformances=d.performances.filter((p:any)=>performanceTeam(p)===primaryTeamId);
    const secondaryPerformances=d.performances.filter((p:any)=>performanceTeam(p)===secondaryTeamId);
    const unknownPerformances=d.performances.filter((p:any)=>!Number.isFinite(performanceTeam(p))||![homeTeamId,awayTeamId].includes(performanceTeam(p)));
    if(unknownPerformances.length) primaryPerformances.push(...unknownPerformances);
    const hasTeamSplit=primaryPerformances.length>0&&secondaryPerformances.length>0;
    const detailedPlayers=new Map<number,any>((detailed.players||[]).map((p:any)=>[Number(p.playerEaId),p] as [number,any]));
    const participants=new Map<number,any>();
    for(const p of d.performances||[]){if(performanceTeam(p)===primaryTeamId&&Number(p.minutes_played||0)>0)participants.set(Number(p.player_ea_id),{...p,detailedStats:p.detailedStats||detailedPlayers.get(Number(p.player_ea_id))?.stats||null});}
    for(const p of detailed.players||[]){if(Number(p.teamEaId)===primaryTeamId&&Number(p.stats?.minutes_played||0)>0&&!participants.has(Number(p.playerEaId)))participants.set(Number(p.playerEaId),{player_ea_id:Number(p.playerEaId),display_name:p.displayName||`Player ${p.playerEaId}`,minutes_played:p.stats?.minutes_played,actual_position:"",primary_position:p.primaryPosition,detailedStats:p.stats,match_team_ea_id:primaryTeamId});}
    const ownPlayers=[...participants.values()].sort((a:any,b:any)=>Number(b.minutes_played||0)-Number(a.minutes_played||0));
    const automaticReportQueue:any=m.is_completed?await api(`/api/careers/${state.careerId}/commission/match-analysis-jobs`,{method:"POST",body:JSON.stringify({snapshot_id:Number(state.snapshotId),fixture_id:Number(m.fixture_id)})}).catch(()=>({scheduled:[]})):{scheduled:[]};
    const individualCaches=await Promise.all(ownPlayers.map((p:any)=>api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(state.snapshotId)}&mode=match_player&fixture_id=${Number(m.fixture_id)}&player_ea_id=${Number(p.player_ea_id)}`).catch(()=>({state:"missing"}))));
    const matchPlayerAnalysis=(cached:any,p:any)=>{const report=cached.result?.report||{},items=(report.observations||[]).slice(0,4),role=p?.actual_position_source==="career_playermatchratinghistory_position"?`Posição observada: ${p.actual_position}`:`Posição cadastrada: ${p?.primary_position||"N/D"} · atuação não registrada`;if(cached.state==="ready"||cached.state==="stale")return `<section class="match-player-ai-summary"><strong>Comissão · ${esc(report.summary?.text||"Análise desta atuação")}</strong>${items.length?`<ul>${items.map((item:any)=>`<li><span class="commission-claim-kind ${esc(item.kind||"fact")}">${esc(item.kind==="inference"?"Leitura técnica":"Fato")}</span> ${esc(item.text)}</li>`).join("")}</ul>`:""}<small>${esc(role)} · contexto desta partida · ${esc(cached.generated_at||"")}</small></section>`;if(cached.state==="queued"||cached.state==="running")return `<section class="match-player-ai-summary"><small>A Comissão está analisando esta atuação em segundo plano.</small></section>`;return `<section class="match-player-ai-summary"><small>A análise individual será iniciada para esta partida concluída.</small></section>`;};
    ownPlayers.forEach((p:any,index:number)=>{const queued=(automaticReportQueue.scheduled||[]).find((job:any)=>job.mode==="match_player"&&Number(job.player_ea_id)===Number(p.player_ea_id));const cached=queued&&["queued","running"].includes(queued.status)&&individualCaches[index].state==="stale"?{state:queued.status}:individualCaches[index];matchPlayerAnalysisHtml.set(Number(p.player_ea_id),`<div data-match-player-analysis="${Number(p.player_ea_id)}">${matchPlayerAnalysis(cached,p)}</div>`);});
    const performanceTable=(items:any[])=>items.length?table(performanceHeaders,items.map(performanceRow)):`<div class="card-body muted">No player performances were exported for this team.</div>`;
    const duplicateNote=Number(d.performanceDiagnostics?.suppressedSnapshotDuplicates||0)>0?`<div class="data-note">Tracker combined ${num(d.performanceDiagnostics.suppressedSnapshotDuplicates)} duplicate snapshot rating row${Number(d.performanceDiagnostics.suppressedSnapshotDuplicates)===1?"":"s"} for this match.</div>`:"";
    const performanceBody=hasTeamSplit?`<div class="card-body" style="padding-bottom:0"><div class="tabbar match-performance-tabs"><button class="active" data-match-performance-team="primary">${esc(teamName(primaryTeamId))} <b>${num(primaryPerformances.length)}</b></button><button data-match-performance-team="secondary">${esc(teamName(secondaryTeamId))} <b>${num(secondaryPerformances.length)}</b></button></div></div><div data-match-performance-panel="primary">${performanceTable(primaryPerformances)}</div><div data-match-performance-panel="secondary" hidden>${performanceTable(secondaryPerformances)}</div>${duplicateNote}`:`${performanceTable(d.performances)}${duplicateNote}`;
    const reportCache:any=m.is_completed?await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(state.snapshotId)}&mode=match&fixture_id=${Number(m.fixture_id)}`).catch(()=>({state:"missing"})):({state:"missing"});
    const savedReport=reportCache.result||{},savedBody=savedReport.report||{},savedCatalog=new Map((savedReport.fact_catalog||[]).map((f:any)=>[f.id,f.label]));
    const savedRefs=(ids:any[])=>esc((ids||[]).map((id:any)=>savedCatalog.get(id)||id).join(" · "));
    const kindLabel=(kind:string)=>kind==="fact"?tr("claimFact"):kind==="hypothesis"?tr("claimHypothesis"):tr("claimInference");
    const savedItems=(items:any[])=>items?.length?`<ul>${items.map((item:any)=>`<li><span class="commission-claim-kind ${esc(item.kind||"inference")}">${esc(kindLabel(item.kind))}</span> ${esc(item.text)}${item.kind==="hypothesis"&&item.limitations?`<small class="commission-claim-limit">${tr("claimLimit")}: ${esc(item.limitations)}</small>`:""}<small class="table-subline">Atlas sources: ${savedRefs(item.fact_refs)}</small></li>`).join("")}</ul>`:"";
    const commissionNote=savedBody.commission_note?.text?`<p class="commission-note"><strong>${tr("commissionNote")}:</strong> ${esc(savedBody.commission_note.text)}<small>${savedRefs(savedBody.commission_note.fact_refs)}</small></p>`:"";
    const reportReview=savedReport.review_required?`<p class="chart-note">Some claims were filtered by source-scope checks; the remaining analysis is still shown.</p>`:"";
    const matchReportOutput=reportCache.state==="ready"||reportCache.state==="stale"?`${reportReview}<div class="commission-report-head"><strong>${esc(savedBody.summary?.text||"Saved technical report")}</strong><small><span class="commission-claim-kind ${esc(savedBody.summary?.kind||"inference")}">${esc(kindLabel(savedBody.summary?.kind))}</span> · ${esc(savedReport.model||"AI provider")} · ${esc(reportCache.generated_at||"")}</small></div>${savedBody.summary?.limitations?`<p class="commission-claim-limit">Limit: ${esc(savedBody.summary.limitations)}</p>`:""}${commissionNote}${savedItems(savedBody.observations)}${savedItems(savedBody.recommendations)}${commissionFollowupForm(savedBody.information_requests,{snapshot_id:Number(state.snapshotId),mode:"match",fixture_id:Number(m.fixture_id),model:savedReport.model,coach_context:savedReport.fact_catalog?.find((f:any)=>f.id==="coach_context")?.value})}<details class="report-provenance"><summary>Evidence coverage and validation</summary><small>${num(savedReport.validation?.accepted_claims)} claims kept · ${num(savedReport.validation?.rejected_claims)} filtered · ${esc(savedReport.validation?.interpretation_quality||"Interpretation quality not independently scored")} · ${savedRefs(savedBody.summary?.fact_refs)}</small></details>`:reportCache.state==="queued"||reportCache.state==="running"?"The Technical Commission is analyzing this match in the background. You can keep using Atlas.":"Generate a contextual report from this match and its prior recorded performances. The analysis is saved with this career's data.";
    const automaticMatchReportQueued=(automaticReportQueue.scheduled||[]).some((job:any)=>job.mode==="match"&&["queued","running"].includes(job.status));
    const matchReportSection=`<section class="card"><header class="card-header"><div><h2>Technical Commission diagnosis</h2><p>Match indicators in context of prior recorded performances</p></div><span class="status-badge ${reportCache.state==="ready"?"good":""}">${esc(reportCache.state||"missing")}</span></header><div class="card-body"><div data-commission-report-output data-report-slot="match-overall" class="commission-report-output" aria-live="polite">${matchReportOutput}</div>${m.is_completed?(automaticMatchReportQueued||reportCache.state==="queued"||reportCache.state==="running"?'<p class="muted">The match analysis and player reports are running in the background.</p>':`<button class="button primary" data-commission-report data-mode="match" data-fixture-id="${m.fixture_id}" data-snapshot-id="${num(state.snapshotId)}" data-force-refresh="${reportCache.state==="ready"?"1":"0"}">${reportCache.state==="ready"?"Refresh match analysis":"Generate match analysis"}</button>`):'<p class="muted">Analysis becomes available when the match is complete.</p>'}</div></section>`;


    // P0: uses only canonical MatchStats and pre-match evidence already available in Atlas.
    const p0Lexicon = {
        "pt-BR":{nav:"Seções da partida",stats:"Estatísticas",commission:"Comissão técnica",players:"Jogadores",key:"Indicadores da partida",npkxg:"NPK-xG",shots:"Finalizações",target:"No alvo",passing:"Passes certos",keypasses:"Passes-chave",won:"Recuperações de posse",match:"Nesta partida",last5:"Até 5 anteriores",season:"Histórico anterior",indicator:"Indicador",context:"Partida em contexto",contextNote:"Médias por partida, calculadas apenas sobre registros anteriores vinculados.",noHistory:"O histórico comparável aparecerá após a análise contextual, quando houver dados suficientes.",noStats:"MatchStats detalhados indisponíveis; os dados existentes permanecem acessíveis.",highlights:"Destaques objetivos",highlightsNote:"Líderes estatísticos, não classificação tática.",rating:"Maior nota registrada",xg:"Maior NPK-xG individual",recovery:"Mais recuperações registradas",noPlayers:"Sem desempenho individual detalhado suficiente.",coverage:"Cobertura e proveniência"},
        "en-GB":{nav:"Match sections",stats:"Statistics",commission:"Technical commission",players:"Players",key:"Match indicators",npkxg:"NPK-xG",shots:"Shots",target:"On target",passing:"Pass accuracy",keypasses:"Key passes",won:"Possession won",match:"This match",last5:"Up to 5 earlier",season:"Prior history",indicator:"Indicator",context:"Match in context",contextNote:"Per-match averages from linked records strictly before this fixture.",noHistory:"Comparable history appears after contextual analysis, when sufficient data is available.",noStats:"Detailed MatchStats unavailable; existing records remain accessible.",highlights:"Objective highlights",highlightsNote:"Statistical leaders, not a tactical ranking.",rating:"Highest recorded rating",xg:"Highest individual NPK-xG",recovery:"Most possession won",noPlayers:"Insufficient detailed player data.",coverage:"Coverage and provenance"},
        "es-ES":{nav:"Secciones del partido",stats:"Estadísticas",commission:"Comisión técnica",players:"Jugadores",key:"Indicadores del partido",npkxg:"NPK-xG",shots:"Remates",target:"A puerta",passing:"Precisión de pase",keypasses:"Pases clave",won:"Recuperaciones",match:"Este partido",last5:"Hasta 5 anteriores",season:"Historial anterior",indicator:"Indicador",context:"Partido en contexto",contextNote:"Medias por partido de registros anteriores vinculados.",noHistory:"El historial comparable aparece tras el análisis contextual, cuando hay datos suficientes.",noStats:"MatchStats detallados no disponibles; los registros existentes siguen accesibles.",highlights:"Destacados objetivos",highlightsNote:"Líderes estadísticos, no una clasificación táctica.",rating:"Mayor nota registrada",xg:"Mayor NPK-xG individual",recovery:"Más recuperaciones",noPlayers:"Sin datos individuales detallados suficientes.",coverage:"Cobertura y procedencia"}
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
    const p0HistoryFact = p0Facts.find((item: any)=>item.id==="pre_match_team_context");
    const p0History = reportCache.state==="ready" ? (p0HistoryFact?.value||null) : null;
    const p0LastFiveAverages = p0History?.last_five_reference?.for?.metrics_per_match || {};
    const p0SeasonAverages = p0History?.season_to_date_reference?.for?.metrics_per_match || {};
    const p0ManagedHome = Number(m.home_team_ea_id)===Number(d.snapshot?.managed_team_ea_id);
    const p0ManagedStats = p0ManagedHome ? homeStats : awayStats;
    const p0HistoricalIndicators = [
        {label:p0T.npkxg,key:"npk_expected_goals",digits:2},
        {label:p0T.shots,key:"shots",digits:1},
        {label:p0T.keypasses,key:"key_passes",digits:1},
        {label:p0T.won,key:"possession_won",digits:1}
    ];
    const p0HistoricalTable = hasDetailed && p0History && Number(p0History.lookback_matches||0)>0
        ? `<div class="match-p0-table-scroll"><table class="match-p0-context-table"><thead><tr><th scope="col">${esc(p0T.indicator)}</th><th scope="col">${esc(p0T.match)}</th><th scope="col">${esc(p0T.last5)} (${num((p0History.recent_five||[]).length)})</th><th scope="col">${esc(p0T.season)} (${num(p0History.lookback_matches)})</th></tr></thead><tbody>${p0HistoricalIndicators.map(item=>`<tr><th scope="row">${esc(item.label)}</th><td>${num(p0ManagedStats[item.key],item.digits)}</td><td>${num(p0LastFiveAverages[item.key],item.digits)}</td><td>${num(p0SeasonAverages[item.key],item.digits)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="match-p0-empty muted">${esc(p0T.noHistory)}</p>`;
    const p0ContextPanel = `<section class="card match-p0-context"><header class="card-header"><div><h2>${esc(p0T.context)}</h2><p>${esc(p0T.contextNote)}</p></div></header>${p0HistoricalTable}</section>`;
    const p0HighestRating = ownPlayers.filter((p: any)=>(p.rating??p.detailedStats?.game_rating)!=null).sort((a: any,b: any)=>Number(b.rating??b.detailedStats?.game_rating)-Number(a.rating??a.detailedStats?.game_rating))[0];
    const p0HighestXg = ownPlayers.filter((p: any)=>Number(p.detailedStats?.npk_expected_goals||0)>0).sort((a: any,b: any)=>Number(b.detailedStats.npk_expected_goals)-Number(a.detailedStats.npk_expected_goals))[0];
    const p0HighestWon = ownPlayers.filter((p: any)=>p.detailedStats?.possession_won!=null).sort((a: any,b: any)=>Number(b.detailedStats.possession_won)-Number(a.detailedStats.possession_won))[0];
    const p0Leaders = [
        {label:p0T.rating,player:p0HighestRating,value:p0HighestRating==null?"":num(p0HighestRating.rating??p0HighestRating.detailedStats?.game_rating,1)},
        {label:p0T.xg,player:p0HighestXg,value:p0HighestXg==null?"":num(p0HighestXg.detailedStats?.npk_expected_goals,2)},
        {label:p0T.recovery,player:p0HighestWon,value:p0HighestWon==null?"":num(p0HighestWon.detailedStats?.possession_won)}
    ].filter(item=>item.player);
    const p0HighlightsPanel = `<section class="card match-p0-highlights"><header class="card-header"><div><h2>${esc(p0T.highlights)}</h2><p>${esc(p0T.highlightsNote)}</p></div></header><div class="match-p0-leaders">${p0Leaders.length?p0Leaders.map(item=>`<div class="match-p0-leader"><span>${esc(item.label)}</span><strong>${playerLink(item.player.player_ea_id,item.player.display_name)}</strong><b>${item.value}</b></div>`).join(""):`<p class="muted">${esc(p0T.noPlayers)}</p>`}</div></section>`;
    const p0Navigation = `<nav class="match-p0-nav" aria-label="${esc(p0T.nav)}"><a href="#p0-match-comparison">${esc(p0T.stats)}</a><a href="#p0-match-commission">${esc(p0T.commission)}</a><a href="#p0-match-players">${esc(p0T.players)}</a></nav>`;

    content.innerHTML = `<div class="content-inner wide">${pageHead("Match report", `${dateText(m.date)} · ${esc(timeText(m.time))}`, `<button class="button" data-route="match-center">Match Center</button>`)}
      <section class="card fixture-hero"><div class="fixture-meta"><span class="inline-identity">${identityLogo(d.competitionIdentity,m.competition_name,"inline-logo")}${competitionLink(m.competition_object_id,m.competition_name)}</span> · ${m.is_completed?"COMPLETED":"SCHEDULED"}</div><div class="fixture-scoreboard"><div class="fixture-club">${identityLogo(d.homeIdentity,m.home_team_name,"fixture-club-logo")}<h2>${clubLink(m.home_team_ea_id,m.home_team_name)}</h2></div><div class="fixture-score">${m.is_completed?`${num(m.home_score)} : ${num(m.away_score)}`:"VS"}<small>${m.home_penalties!=null||m.away_penalties!=null?`Penalty shoot-out ${num(m.home_penalties)}:${num(m.away_penalties)}`:esc(m.managed_team_result||"")}</small></div><div class="fixture-club">${identityLogo(d.awayIdentity,m.away_team_name,"fixture-club-logo")}<h2>${clubLink(m.away_team_ea_id,m.away_team_name)}</h2></div></div></section>
      ${p0Navigation}${p0QuickStats}<div class="match-p0-main"><div class="match-p0-primary" id="p0-match-comparison">${comparison||`<section class="card pad">${esc(p0T.noStats)}</section>`}${p0ContextPanel}</div><aside class="match-p0-secondary"><div id="p0-match-commission">${matchReportSection}</div>${p0HighlightsPanel}</aside></div>${events}
      <section id="p0-match-players" class="card match-performance-section"><header class="card-header"><div><h2>Player performances</h2><p>${hasDetailed?"Direct FC26 match data for exported participants":"Detailed MatchStats unavailable; ratings and conservative snapshot reconstruction are shown when recorded"}</p></div></header>${d.performances.length?performanceBody:`<div class="card-body muted">No player performances were exported for this match.</div>`}</section>
      ${stadiumSection}<details class="match-p0-fold match-p0-provenance"><summary>${esc(p0T.coverage)}</summary><section class="card pad match-coverage-section"><h3 class="card-title">Data coverage</h3><div class="grid metrics compact">${metric("Match ratings",d.capabilities?.matchRatings?"Available":"Partial","ratings and minutes")}${metric("Detailed FC26 data",hasDetailed?"Available":"Not available",hasDetailed?`${num(detailed.players?.length||0)} participants`:"snapshot data fallback",hasDetailed?"green":"amber")}${metric("Events",hasDetailed?num(detailed.events?.length||0):"–",hasDetailed?"not chronological · no confirmed minutes":"no detailed source")}${metric("Link confidence",hasDetailed?`${num(detailed.linkageConfidence*100,0)} %`:"–","import linkage metadata")}${metric("xG model",hasDetailed?(homeStats.expected_goals_derived!=null||awayStats.expected_goals_derived!=null?"Team-xG + NPK-xG":"NPK-xG"):"–",hasDetailed?(homeStats.expected_goals_derived!=null||awayStats.expected_goals_derived!=null?"Team-xG = NPK-xG + 0.7 × penalty attempts":"direct FC26 NPK value"):"")}</div><p class="data-note">${esc(detailed.xgNote||"")} ${esc(detailed.eventTimingNote||"")}</p></section></details>
    </div>`;
    const queuedReportJobs=(automaticReportQueue.scheduled||[]).filter((job:any)=>job?.job_id);
    if(queuedReportJobs.length){
        void (async()=>{
            for(let attempt=0;attempt<240&&content.querySelector('[data-report-slot="match-overall"]');attempt++){
                await new Promise(resolve=>setTimeout(resolve,5000));
                for(const queued of queuedReportJobs){
                    if(queued.refreshed)continue;
                    const current:any=await api(`/api/careers/${state.careerId}/commission/report-jobs/${queued.job_id}`).catch(()=>null);
                    if(!current)continue;
                    queued.status=current.status;
                    if(current.status==="complete"&&queued.mode==="match_player"){
                        const cached:any=await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(state.snapshotId)}&mode=match_player&fixture_id=${Number(m.fixture_id)}&player_ea_id=${Number(queued.player_ea_id)}`).catch(()=>null);
                        const target=Array.from(content.querySelectorAll<HTMLElement>('[data-match-player-analysis]')).find(node=>Number(node.dataset.matchPlayerAnalysis)===Number(queued.player_ea_id));
                        if(target)target.innerHTML=matchPlayerAnalysis(cached||{state:"missing"},ownPlayers.find((player:any)=>Number(player.player_ea_id)===Number(queued.player_ea_id)));
                    }else if(current.status==="complete"&&queued.mode==="match"){
                        const cached:any=await api(`/api/careers/${state.careerId}/commission/report-cache?snapshot_id=${Number(state.snapshotId)}&mode=match&fixture_id=${Number(m.fixture_id)}`).catch(()=>null);
                        const target=content.querySelector<HTMLElement>('[data-report-slot="match-overall"]'),body=cached?.result?.report||{};
                        if(target&&cached?.state==="ready")target.innerHTML=`<div class="commission-report-head"><strong>${esc(body.summary?.text||"Match report ready")}</strong><small>${esc(cached.model||"AI provider")} · ${esc(cached.generated_at||"")}</small></div>${savedItems(body.observations)}${savedItems(body.recommendations)}`;
                    }else if(current.status==="failed"&&queued.mode==="match_player"){
                        const target=Array.from(content.querySelectorAll<HTMLElement>('[data-match-player-analysis]')).find(node=>Number(node.dataset.matchPlayerAnalysis)===Number(queued.player_ea_id));
                        if(target)target.innerHTML='<section class="match-player-ai-summary"><small>A análise desta atuação falhou; os números registrados continuam disponíveis.</small></section>';
                    }
                    if(["complete","failed"].includes(current.status))queued.refreshed=true;
                }
                if(queuedReportJobs.every((job:any)=>["complete","failed"].includes(job.status)))break;
            }
        })();
    }
    $$("[data-match-performance-team]",content).forEach((button:any)=>button.onclick=()=>{
        const key=button.dataset.matchPerformanceTeam;
        $$("[data-match-performance-team]",content).forEach((item:any)=>item.classList.toggle("active",item.dataset.matchPerformanceTeam===key));
        $$("[data-match-performance-panel]",content).forEach((panel:any)=>panel.hidden=panel.dataset.matchPerformancePanel!==key);
    });
}
async function renderCompetitions() {
    const d = await api(`/api/snapshots/${state.snapshotId}/competitions`);
    const mode=state.competitionListTab||"deeper";
    const q = state.competitionQuery.toLowerCase();
    const deeper=(d.competitions||[]).filter((c:any)=>!q||String(c.competition_name||"").toLowerCase().includes(q));
    const atlas=(d.worldCompetitions||[]).filter((c:any)=>!q||String(c.leagueName||"").toLowerCase().includes(q));
    const tabs=`<div class="tabbar"><button data-competition-list-tab="deeper" class="${mode==="deeper"?"active":""}">Deeper Simulation <b>${num((d.competitions||[]).length)}</b></button><button data-competition-list-tab="atlas" class="${mode==="atlas"?"active":""}">atlas-world-simulation <b>${num((d.worldCompetitions||[]).length)}</b></button></div>`;
    const deeperCards=`<div class="grid competition-grid">${deeper.map((c:any)=>`<button class="competition-card card" data-competition="${c.competition_object_id}"><div class="competition-top">${identityLogo(c.identity,c.competition_name,"competition-logo-card")}<div><h3>${esc(c.competition_name)}</h3><p>Object ID ${num(c.competition_object_id)}${c.identity?.mediaCompetitionId?` · Media ID ${num(c.identity.mediaCompetitionId)}`:""}</p></div></div><div class="competition-format-line">${statusBadge(c.notStarted?"Not started":(c.format?.label||"Detecting format"),c.notStarted?"blue":c.format?.type==="league"?"good":c.format?.type==="hybrid"?"amber":"")}</div><div class="competition-stats"><div><strong>${num(c.fixture_count)}</strong><small>Matches</small></div><div><strong>${num(c.completed)}</strong><small>Completed</small></div><div><strong>${num(c.managed_matches)}</strong><small>Your club</small></div></div><div class="change-fields">${(c.sources||[]).map((source:any)=>`<span class="mini-tag">${esc(source)}</span>`).join("")}</div></button>`).join("")}</div>`;
    const atlasCards=`<div class="grid competition-grid">${atlas.map((league:any)=>`<button class="competition-card card atlas-world-card" data-world-competition="${rawNumber(league.leagueEaId)}"><div class="competition-top">${identityLogo(league.identity,league.leagueName,"competition-logo-card")}<div><h3>${esc(league.leagueName)}</h3><p>League ID ${num(league.leagueEaId)} · ${num(league.teamCount)} clubs</p></div></div><div class="competition-format-line">${statusBadge(league.tableSourceLabel||"Atlas World Simulation",league.tableSource==="fc_aggregate"?"good":"blue")}</div><div class="competition-stats"><div><strong>${num(league.matchesPlayed)}</strong><small>Matches per team</small></div><div><strong>${num(league.completedRounds)}</strong><small>of ${num(league.totalRounds)} rounds</small></div><div><strong>${num(Number(league.progress||0)*100)} %</strong><small>Season progress</small></div></div><div class="data-note">Season ${dateText(league.seasonStart)}–${dateText(league.seasonEnd)}${league.lastUpdateDate?` · last simulation state ${dateText(league.lastUpdateDate)}`:" · not started yet"}</div></button>`).join("")}</div>`;
    const count=mode==="deeper"?deeper.length:atlas.length;
    content.innerHTML=`<div class="content-inner">${pageHead("Competitions","Reliable EA competitions and clearly separated Atlas league models")}${tabs}<div class="filter-row"><input id="competitionQuery" class="filter-input" value="${esc(state.competitionQuery)}" placeholder="Search competitions…"><span class="chip">${num(count)} competitions</span></div>${mode==="deeper"?deeperCards:atlasCards}</div>`;
    $("#competitionQuery",content).oninput=(event:any)=>{state.competitionQuery=event.target.value;render();};
}
async function renderWorldCompetition() {
    const d=await api(`/api/snapshots/${state.snapshotId}/world-leagues/${Number(state.routeData.id)}`);
    const calendar=d.calendar||{},isFc=d.tableSource==="fc_aggregate",partial=(d.items||[]).some((item:any)=>item.aggregate_only);
    const rows=(d.items||[]).map((r:any)=>`<tr><td class="center"><b>${num(r.position)}</b></td><td><span class="inline-identity">${identityLogo(r.identity,r.team_name,"table-club-logo")}${clubLink(r.team_ea_id,r.team_name)}</span></td><td class="num">${num(r.matches_played)}</td><td class="num">${r.aggregate_only?"–":num(r.wins)}</td><td class="num">${r.aggregate_only?"–":num(r.draws)}</td><td class="num">${r.aggregate_only?"–":num(r.losses)}</td><td class="num">${r.aggregate_only?"–":`${num(r.goals_for)}:${num(r.goals_against)}`}</td><td class="num">${r.aggregate_only?"–":`${Number(r.goal_difference)>0?"+":""}${num(r.goal_difference)}`}</td><td class="num"><b>${num(r.points)}</b></td></tr>`);
    const split=(title:string,items:any[])=>items?.length?`<details class="league-split-table"><summary>${esc(title)}</summary>${table([{label:"#",cls:"center"},{label:"Club"},{label:"P",cls:"num"},{label:"W",cls:"num"},{label:"D",cls:"num"},{label:"L",cls:"num"},{label:"Goals",cls:"num"},{label:"GD",cls:"num"},{label:"Pts",cls:"num"}],items.map((r:any)=>`<tr><td class="center"><b>${num(r.position)}</b></td><td><span class="inline-identity">${identityLogo(r.identity,r.team_name,"table-club-logo")}${clubLink(r.team_ea_id,r.team_name)}</span></td><td class="num">${num(r.matches_played)}</td><td class="num">${num(r.wins)}</td><td class="num">${num(r.draws)}</td><td class="num">${num(r.losses)}</td><td class="num">${num(r.goals_for)}:${num(r.goals_against)}</td><td class="num">${Number(r.goal_difference)>0?"+":""}${num(r.goal_difference)}</td><td class="num"><b>${num(r.points)}</b></td></tr>`).join(""))}</details>`:"";
    content.innerHTML=`<div class="content-inner wide">${pageHead(d.leagueName||`League ${num(d.leagueEaId)}`,`Atlas World · League ID ${num(d.leagueEaId)}`,`<button class="button" data-route="competitions">All competitions</button>`)}
      <section class="card competition-identity-hero" ${identityStyle(d.identity)}><div>${identityLogo(d.identity,d.leagueName,"competition-hero-logo")}</div><div><p>ATLAS WORLD</p><h2>${esc(d.leagueName||`League ${d.leagueEaId}`)}</h2><div class="profile-badges"><span class="chip">League ID ${num(d.leagueEaId)}</span>${d.identity?.logo?statusBadge("Competition logo assigned","good"):statusBadge("No logo found")}${statusBadge(isFc?"FC26 table + Atlas player statistics":(d.modelId||"Atlas World Simulation"),isFc?"good":"blue")}</div></div>${trophyImage(d.identity,d.leagueName,"competition-trophy")}</section>
      <div class="grid metrics">${metric("Clubs",num((d.items||[]).length),"current league participants")}${metric("Rounds",`${num(calendar.completedRounds)} / ${num(calendar.totalRounds)}`,calendar.lastUpdateDate?`As of ${dateText(calendar.lastUpdateDate)}`:"Season not started yet","green")}${metric("Progress",`${num(Number(calendar.progress||0)*100)} %`,`${dateText(calendar.seasonStart)}–${dateText(calendar.seasonEnd)}`,"blue")}${metric("Matches per team",num(Math.max(0,...(d.items||[]).map((item:any)=>Number(item.matches_played||0)))),isFc?"FC26 table":"simulated table")}</div>
      <div class="grid split-65">
        <div><section class="card"><header class="card-header"><div><h2>League table</h2><p>${isFc?(partial?"Partial FC26 aggregate from an older snapshot":"Complete FC26 table; player statistics are linked to it"):"Consistent Tracker table advanced every Saturday"}</p></div>${statusBadge(isFc?"FC26 table":"Atlas simulation",isFc?"good":"blue")}</header>${rows.length?table([{label:"#",cls:"center"},{label:"Club"},{label:"P",cls:"num"},{label:"W",cls:"num"},{label:"D",cls:"num"},{label:"L",cls:"num"},{label:"Goals",cls:"num"},{label:"GD",cls:"num"},{label:"Pts",cls:"num"}],rows):`<div class="card-body muted">No table is available for this league on the selected date.</div>`}${split("Home table",d.homeItems||[])}${split("Away table",d.awayItems||[])}<div class="data-note">${esc(d.notice||"")}</div></section></div>
        <aside class="grid">
          <section class="card"><header class="card-header"><h2>Top scorers</h2></header><div class="card-body list">${leaderList(d.topScorers,"Goals",(p:any)=>num(p.goals))}</div></section>
          <section class="card"><header class="card-header"><h2>Top assists</h2></header><div class="card-body list">${leaderList(d.topAssists,"Assists",(p:any)=>num(p.assists))}</div></section>
          <section class="card"><header class="card-header"><div><h2>Top ratings</h2><p>At least ${num(d.ratingMinimumAppearances)} appearances</p></div></header><div class="card-body list">${leaderList(d.topRatings,"Avg rating",(p:any)=>ratingValue(p.average_rating,true))}</div></section>
        </aside>
      </div>
    </div>`;
}


function leaderList(rows: any, metricName: any, formatter: any) { return rows?.length ? rows.map((p: any, index: any) => `<div class="list-row leader-row"><span class="leader-rank">${index + 1}</span>${playerPortrait(p.media, p.display_name, "list-portrait")}<div class="list-main">${playerLink(p.player_ea_id, p.display_name)}<small>${clubLink(p.represented_team_ea_id, p.represented_team_name)} · ${num(p.appearances)} appearances</small></div><div class="list-value"><strong>${formatter(p)}</strong><small>${esc(metricName)}</small></div></div>`).join("") : '<span class="muted">No matching season statistics.</span>'; }
function competitionFixtureTable(fixtures: any) {
    return table(
      [{ label: "Date" }, { label: "Home" }, { label: "Result", cls: "center" }, { label: "Away" }, { label: "Status" }, { label: "", sortable: false }],
      fixtures.map((m: any) => {
        const advanced = Number(m.advanced_team_id);
        const homeAdvanced = Number.isFinite(advanced) && advanced === Number(m.home_team_ea_id);
        const awayAdvanced = Number.isFinite(advanced) && advanced === Number(m.away_team_ea_id);
        const homeWon = m.is_completed && Number(m.home_score) > Number(m.away_score);
        const awayWon = m.is_completed && Number(m.away_score) > Number(m.home_score);
        const decision = m.decision_label || "Advanced";
        const scoreExtra = m.aggregate_score ? `<small class="aggregate-note">Aggregate ${esc(m.aggregate_score)}</small>` : (m.penalty_home_score != null || m.penalty_away_score != null ? `<small class="aggregate-note">${num(m.penalty_home_score)}:${num(m.penalty_away_score)} pens</small>` : "");
        const teamCell = (side: any, isAdvanced: any, isWinner: any) => {
          const identity = side === "home" ? m.homeIdentity : m.awayIdentity;
          const id = side === "home" ? m.home_team_ea_id : m.away_team_ea_id;
          const name = side === "home" ? m.home_team_name : m.away_team_name;
          return `<span class="inline-identity knockout-team ${isAdvanced ? "knockout-advanced" : isWinner ? "match-winner" : ""}">${identityLogo(identity, name, "table-club-logo")}${clubLink(id, name)}${isAdvanced ? statusBadge(decision, decision === "Cup winner" ? "winner" : "good") : ""}</span>`;
        };
        return `<tr class="${homeAdvanced || awayAdvanced ? "knockout-decided" : ""}"><td data-sort="${esc(m.date || "")}">${dateText(m.date)}</td><td>${teamCell("home", homeAdvanced, homeWon)}</td><td class="center"><b>${m.is_completed ? `${num(m.home_score)}:${num(m.away_score)}` : "–"}</b>${scoreExtra}</td><td>${teamCell("away", awayAdvanced, awayWon)}</td><td>${m.is_completed ? statusBadge("Completed", "good") : statusBadge("Scheduled")}</td><td>${matchLink(m.fixture_id, "Details")}</td></tr>`;
      })
    );
}
function competitionGroups(groups: any, mode: any, formatType: any) {
    const filtered = groups.map((group: any) => ({ ...group, fixtures: group.fixtures.filter((match: any) => mode === "results" ? match.is_completed : !match.is_completed) })).filter((group: any) => group.fixtures.length);
    if (!filtered.length) return { html: '<div class="card-body muted">No matches in this view.</div>', groups: [] };
    const defaultIndex = mode === "results" ? filtered.length - 1 : 0;
    const prefix = formatType === "league" ? "Matchday" : formatType === "hybrid" ? "Phase / matchday" : "Round";
    const html = `<div class="fixture-groups">${filtered.map((group: any, index: any) => `<details class="fixture-group" data-fixture-group="${index}" ${index === defaultIndex ? "open" : ""}><summary><div><strong>${esc(group.label.replace("Matchday / round", prefix))}</strong><small>${num(group.fixtures.length)} matches</small></div><span>${mode === "results" ? `${num(group.fixtures.filter((m: any) => m.is_completed).length)} Results` : `${num(group.fixtures.filter((m: any) => !m.is_completed).length)} open`}</span></summary><div class="fixture-group-lazy" data-loaded="${index === defaultIndex ? "1" : "0"}">${index === defaultIndex ? competitionFixtureTable(group.fixtures) : '<div class="lazy-fixture-placeholder">Load when opened</div>'}</div></details>`).join("")}</div>`;
    return { html, groups: filtered };
}
function bindCompetitionGroups(view: any) {
    $$<HTMLDetailsElement>('.fixture-group[data-fixture-group]', content).forEach((details: any) => details.addEventListener('toggle', () => {
        if (!details.open) return;
        const host = $('.fixture-group-lazy', details);
        if (!host || host.dataset.loaded === '1') return;
        const index = Number(details.dataset.fixtureGroup);
        const group = view.groups[index];
        if (!group) return;
        host.innerHTML = competitionFixtureTable(group.fixtures);
        host.dataset.loaded = '1';
        bindSortableTables();
        $$('[data-player]', host).forEach((n: any) => n.onclick = (e: any) => { e.stopPropagation(); navigate("player", { id: Number(n.dataset.player), tab: "overview" }); });
        $$('[data-club]', host).forEach((n: any) => n.onclick = (e: any) => { e.stopPropagation(); navigate("club", { id: Number(n.dataset.club) }); });
        $$('[data-match]', host).forEach((n: any) => n.onclick = (e: any) => { e.stopPropagation(); navigate("match", { id: Number(n.dataset.match) }); });
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
          ], d.standings.map((r: any) => `<tr>
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
          <section class="card"><header class="card-header"><h2>Top scorers</h2></header><div class="card-body list">${leaderList(d.topScorers, "Goals", (p: any) => num(p.goals))}</div></section>
          <section class="card"><header class="card-header"><h2>Top assists</h2></header><div class="card-body list">${leaderList(d.topAssists, "Assists", (p: any) => num(p.assists))}</div></section>
          <section class="card"><header class="card-header"><div><h2>Top ratings</h2><p>At least ${num(d.ratingMinimumAppearances)} appearances</p></div></header><div class="card-body list">${leaderList(d.topRatings, "Avg rating", (p: any) => ratingValue(p.average_rating, true))}</div></section>
          <section class="card"><header class="card-header"><h2>Participants</h2></header><div class="card-body list compact-list">${d.participants.slice(0, 30).map((t: any) => `<div class="list-row">${identityLogo(t.identity, t.team_name, "list-club-logo")}<div class="list-main">${clubLink(t.team_id, t.team_name)}<small>EA Team ID ${num(t.team_id)}</small></div></div>`).join("")}</div></section>
          ${d.progress.length ? `<section class="card pad"><h3 class="card-title">Competition progress</h3><div class="list">${d.progress.map((p: any) => `<div class="list-row"><div class="list-main">${clubLink(p.team_ea_id, p.team_name || p.raw?.team_name)}<small>Stage ${num(p.stage_id)} · Season ${num(p.season)}</small></div>${statusBadge(p.has_team_won ? "Winner" : "Active")}</div>`).join("")}</div></section>` : ""}
        </aside>
      </div>
    </div>`;
    bindCompetitionGroups(groupView);
}
