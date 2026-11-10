function mediaProgressMarkup(progress: any) {
    const processing = progress?.processing || {};
    const total = Number(progress?.total || 0);
    const visited = Number(progress?.visited || 0);
    const pct = total ? Math.min(100, Math.round(visited / total * 100)) : (progress?.phase === "complete" ? 100 : 0);
    const ready = Number(processing.ready || 0);
    const pending = Number(processing.pending || 0);
    const active = Number(processing.processing || 0);
    const failed = Number(processing.failed || 0);
    const phaseLabels: Record<string, string> = { idle: "Ready", indexing: "Indexing files", complete: "Index complete", cancelled: "Index cancelled", failed: "Index error" };
    const phaseLabel = phaseLabels[String(progress?.phase || "idle")] || progress?.phase || "Ready";
    return `<div class="media-progress-head"><div><strong>${esc(phaseLabel)}</strong><small>${progress?.active ? `${num(visited)} / ${num(total)} files · ${num(progress.filesPerSecond,1)} files/s` : `${num(ready)} prepared · ${num(pending)} pending`}</small></div><div class="page-actions">${progress?.paused ? '<button class="button small" data-media-control="resume">Resume</button>' : '<button class="button small" data-media-control="pause">Pause</button>'}${progress?.active ? '<button class="button small danger" data-media-control="cancel">Cancel index</button>' : ''}</div></div><div class="progress-track"><span style="width:${pct}%"></span></div><div class="media-progress-stats"><span>Index: <b>${num(progress?.indexed || 0)}</b></span><span>Assigned: <b>${num(progress?.assigned || 0)}</b></span><span>Queue: <b>${num(progress?.queue || 0)}</b></span><span>Active: <b>${num(active)}</b></span><span>Ready: <b>${num(ready)}</b></span><span>Errors: <b>${num(failed)}</b></span></div>${progress?.currentFile ? `<small class="mono muted">${esc(progress.currentFile)}</small>` : ''}`;
}
async function refreshMediaProgress() {
    try {
        const progress = await api<MediaProgressResponse>("/api/media/progress");
        const previousPhase = lastMediaProgressPhase;
        const previousPending = lastMediaPending;
        lastMediaProgressPhase = progress.phase;
        lastMediaPending = Number(progress.processing?.pending || 0) + Number(progress.processing?.processing || 0);
        const panel = $("#mediaProgress", content);
        if (panel) {
            panel.innerHTML = mediaProgressMarkup(progress);
            $$('[data-media-control]', panel).forEach((button: any) => button.onclick = () => handleAction(`media-${button.dataset.mediaControl}`));
        }
        const indexJustFinished = previousPhase === "indexing" && !progress.active;
        const queueJustFinished = Number(previousPending || 0) > 0 && lastMediaPending === 0;
        if (indexJustFinished || queueJustFinished) clearApiCache();
        if ((indexJustFinished || queueJustFinished) && state.route === "media" && !mediaRefreshPending) {
            mediaRefreshPending = true;
            setTimeout(async () => {
                try { await renderMedia(); applyIcons(content); bindContent(); }
                finally { mediaRefreshPending = false; }
            }, 80);
        }
        if (!progress.active && Number(progress.queue || 0) === 0 && Number(progress.processing?.processing || 0) === 0) {
            if (mediaProgressTimer !== null) clearInterval(mediaProgressTimer);
            mediaProgressTimer = null;
        }
    } catch { }
}
function startMediaProgressPolling() {
    if (mediaProgressTimer) return;
    refreshMediaProgress();
    mediaProgressTimer = setInterval(refreshMediaProgress, 900);
}
function llmKeyField(configured: Record<string, boolean>, hints: Record<string, string>, name: string, label: string): string {
    const saved = Boolean(configured[name]);
    const placeholder = saved ? `Saved ${esc(hints[name] || "")} — type a new key to replace` : "Paste the API key";
    const action = saved
        ? `<div class="page-actions" style="margin:-4px 0 10px"><button class="button small danger" data-remove-llm-key="${name}">Remove saved key</button></div>`
        : `<p class="muted" style="margin:-4px 0 10px">Not configured.</p>`;
    return `<label class="page-filter"><span>${label}</span><input class="filter-input" data-llm-key="${name}" autocomplete="off" spellcheck="false" placeholder="${placeholder}"></label>${action}`;
}

async function renderMedia() {
    const status = await api("/api/media/status");
    const params = new URLSearchParams();
    if (state.mediaStatus !== "all") params.set("status", state.mediaStatus);
    if (state.mediaType !== "all") params.set("type", state.mediaType);
    params.set("limit", "500");
    const assets = await api(`/api/media/assets?${params.toString()}`);
    const competitionMappings = state.snapshotId ? await api(`/api/media/competition-mappings?snapshotId=${state.snapshotId}`) : { items: [], choices: [] };
    const types = [["players","Player portraits"],["club_logos","Club logos"],["competition_logos","Competition logos"],["trophies","Trophies"],["stadiums","Stadiums"],["kits","Kits"],["auto","Mixed folder"]];
    const typeOptions = [["all","All media types"],["player_portrait","Player portraits"],["club_logo","Club logos"],["competition_logo","Competition logos"],["trophy","Trophies"],["stadium","Stadiums"],["kit","Kits"]];
    const statusOptions = [["all","All statuses"],["assigned","Assigned"],["conflict","Conflicts"],["unknown","Unknown"],["ignored","Ignored"],["error","Errors"]];
    const progress = status.progress || {};
    const ready = Number(status.processing?.ready || 0), pending = Number(status.processing?.pending || 0);
    content.innerHTML = `<div class="content-inner wide">${pageHead("Media library", "Fast ID index · WebP generated only when needed and in the background", `<button class="button primary" data-action="scan-media">Quick index</button>`)}
      <div class="grid metrics">${metric("Assigned", num(status.counts?.assigned || 0), "immediately after ID scan", "green")}${metric("Prepared", num(ready), "WebP available", "blue")}${metric("Pending", num(pending), "processed in the background", "amber")}${metric("Unknown", num(status.counts?.unknown || 0), "not converted")}${metric("Sources", num(status.sources?.filter((s: any) => s.enabled).length || 0), `${num(progress.workers || 0)} Worker`, "blue")}</div>
      <section id="mediaProgress" class="card pad media-progress-panel">${mediaProgressMarkup(progress)}</section>
      <section class="card pad"><div class="media-source-head"><div><h3 class="card-title">Media sources</h3><p class="muted">The index scan reads only the file name, ID, size and modification time. Hashing, copying and WebP generation happen later for assigned images, either in the background or when first displayed.</p></div></div><div class="source-picker-grid">${types.map(([key,label]: any) => `<button class="source-picker" data-media-source="${key}"><span data-icon="folder"></span><strong>${esc(label)}</strong><small>Choose folder</small></button>`).join("")}</div>${status.sources?.length ? `<div class="source-list">${status.sources.map((source: any) => `<div class="source-row ${source.enabled ? "" : "disabled"}"><div><strong>${esc(source.label)}</strong><small>${esc(source.path)}</small></div><div class="source-stats"><span>${num(source.last_file_count)} files</span><span>${num(source.last_imported_count)} indexed</span><button class="entity-link" data-remove-source="${source.id}">${source.enabled ? "Disable" : "Disabled"}</button></div></div>`).join("")}</div>` : ""}</section>
      ${competitionMappings.items?.length ? `<section class="card pad competition-mapping-panel"><div class="media-source-head"><div><h3 class="card-title">Competition logo mapping</h3><p class="muted">Career object IDs and the IDs in <span class="mono">l&lt;ID&gt;.png</span> are different. Tracker maps leagues automatically from league IDs and participants. Cup mappings can be confirmed here once.</p></div><button class="button" data-action="rebuild-competition-media">Rebuild automatically</button></div><datalist id="competitionMediaIds">${(competitionMappings.choices || []).map((choice: any) => `<option value="${choice.mediaCompetitionId}">ID ${choice.mediaCompetitionId}</option>`).join("")}</datalist><div class="competition-mapping-list">${competitionMappings.items.map((item: any) => `<div class="competition-mapping-row ${item.mediaCompetitionId ? "mapped" : "unmapped"}"><div class="competition-mapping-logo">${item.logo?.url ? `<img src="${esc(item.logo.url)}" alt="">` : `<span data-icon="trophy"></span>`}</div><div class="competition-mapping-copy"><strong>${esc(item.competitionName)}</strong><small>Career ID ${num(item.competitionObjectId)}${item.mappingSource ? ` · ${esc(item.mappingSource)} · ${Math.round(Number(item.mappingConfidence || 0) * 100)} %` : " · unassigned"}</small></div><input class="filter-input mono" list="competitionMediaIds" data-competition-media-id="${item.competitionObjectId}" value="${item.mediaCompetitionId || ""}" placeholder="Logo-ID"><button class="button small" data-save-competition-media="${item.competitionObjectId}">Save</button></div>`).join("")}</div></section>` : ""}
      <div class="filter-row"><select id="mediaType" class="filter-select">${typeOptions.map(([key,label]: any) => `<option value="${key}" ${state.mediaType===key?"selected":""}>${label}</option>`).join("")}</select><select id="mediaStatus" class="filter-select">${statusOptions.map(([key,label]: any) => `<option value="${key}" ${state.mediaStatus===key?"selected":""}>${label}</option>`).join("")}</select><span class="chip">${num(assets.length)} media assets</span></div>
      ${assets.length ? `<div class="media-grid">${assets.map((asset: any) => `<article class="media-card card status-${esc(asset.status)}"><div class="media-preview">${asset.thumbUrl ? `<img src="${esc(asset.thumbUrl)}" alt="${esc(asset.original_name)}" loading="lazy">` : `<span data-icon="media"></span>`}</div><div class="media-card-copy"><div class="media-card-title"><strong>${esc(asset.original_name)}</strong>${statusBadge(asset.status, asset.status === "assigned" ? "good" : asset.status === "error" ? "bad" : asset.status === "conflict" ? "warn" : "")}</div><small>${esc(asset.media_type)} · ${asset.entity_type ? `${esc(asset.entity_type)} ${num(asset.ea_id)}` : "unassigned"}${asset.season_start ? ` · Season ${num(asset.season_start)}` : ""}${asset.variant ? ` · ${esc(asset.variant)}` : ""}</small><small>${asset.processing_state === "ready" ? `${num(asset.width)} × ${num(asset.height)} px · WebP ready` : asset.status === "assigned" ? `Processing: ${esc(asset.processing_state || "pending")}` : esc(asset.source_type || "")}</small>${asset.warning || asset.ignored_reason ? `<p>${esc(asset.warning || asset.ignored_reason)}</p>` : ""}${["conflict","unknown"].includes(asset.status) ? `<div class="media-assign"><select data-assign-type="${asset.id}"><option value="club">Club</option><option value="competition">Competition</option><option value="player">Player</option><option value="stadium">Stadium</option></select><input data-assign-id="${asset.id}" inputmode="numeric" placeholder="EA-ID" value="${asset.ea_id || ""}"><button class="button small" data-assign-asset="${asset.id}">Assign</button></div>` : ""}</div></article>`).join("")}</div>` : emptyState("No media in this view", "Add sources, start the quick index, or adjust the filters.")}
    </div>`;
    $("#mediaType", content).onchange = (e: any) => { state.mediaType = e.target.value; renderMedia().then(() => { applyIcons(content); bindContent(); }); };
    $("#mediaStatus", content).onchange = (e: any) => { state.mediaStatus = e.target.value; renderMedia().then(() => { applyIcons(content); bindContent(); }); };
    $$('[data-media-control]', content).forEach((button: any) => button.onclick = () => handleAction(`media-${button.dataset.mediaControl}`));
    if (progress.active || Number(progress.queue || 0) > 0 || Number(progress.processing?.processing || 0) > 0) startMediaProgressPolling();
}
async function renderSetup() {
    const [reference, media, workspaces, llm] = await Promise.all([
        api("/api/reference/status"),
        api("/api/media/status"),
        api("/api/workspaces"),
        api("/api/llm/config"),
    ]);
    const llmConfigured = (llm.configured || {}) as Record<string, boolean>;
    const llmHints = (llm.key_hints || {}) as Record<string, string>;
    const llmProvider = String(llm.provider || state.llmProvider || "ollama");
    const latest = reference.latest || {};
    const workspaceRows = (workspaces.workspaces || []).map((workspace: any) => {
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
      <section class="card pad"><h3 class="card-title">Media status</h3><div class="list"><div class="list-row"><div class="list-main"><strong>Sources</strong></div><b>${num(media.sources?.filter((s: any) => s.enabled).length)}</b></div><div class="list-row"><div class="list-main"><strong>Assigned assets</strong></div><b>${num(media.counts?.assigned || 0)}</b></div><div class="list-row"><div class="list-main"><strong>Conflicts / unknown</strong></div><b>${num((media.counts?.conflict || 0) + (media.counts?.unknown || 0))}</b></div></div><div class="page-actions"><button class="button" data-route="media">Manage sources</button><button class="button primary" data-action="scan-media">Scan media</button></div></section>
      <section class="card pad"><h3 class="card-title">${tr("setupLanguage")}</h3><p class="muted">${tr("setupLanguageHelp")}</p><label class="page-filter"><span>${tr("setupLanguage")}</span><select data-atlas-language><option value="pt-BR" ${state.status?.settings?.language === "pt-BR" ? "selected" : ""}>Português (Brasil)</option><option value="en-GB" ${state.status?.settings?.language === "en-GB" ? "selected" : ""}>English (UK)</option><option value="es-ES" ${state.status?.settings?.language === "es-ES" ? "selected" : ""}>Español</option></select></label><div class="page-actions"><button class="button primary" data-save-atlas-language>${tr("saveLanguage")}</button></div></section>
      <section class="card pad"><h3 class="card-title">Visibility</h3><p class="muted">This filter applies across search, views and world simulation. Imported snapshot data is never changed.</p><label class="setting-toggle"><input type="checkbox" data-hide-womens-football ${state.status?.settings?.hideWomensFootball ? "checked" : ""}><span><strong>Hide women’s football</strong><small>Hide women’s competitions, teams and players from Tracker views.</small></span></label></section>
      <section class="card pad"><h3 class="card-title">AI Analysis Engine</h3><p class="muted">Keys are stored in this career's database, so Gemini and Groq can both be saved and switched at any time. The selected provider is used for every Technical Commission report; local Ollama keeps everything on your GPU.</p><label class="page-filter"><span>Provider</span><select data-llm-provider><option value="ollama" ${llmProvider === "ollama" ? "selected" : ""}>Ollama (Local)</option><option value="gemini" ${llmProvider === "gemini" ? "selected" : ""}>Google Gemini (Cloud)${llmConfigured.gemini ? " · key saved" : " · no key"}</option><option value="groq" ${llmProvider === "groq" ? "selected" : ""}>Groq (Cloud)${llmConfigured.groq ? " · key saved" : " · no key"}</option></select></label><div class="llm-keys-panel">${llmKeyField(llmConfigured, llmHints, "gemini", "Google Gemini key")}${llmKeyField(llmConfigured, llmHints, "groq", "Groq key")}</div><p class="muted">Gemini free tier: 20 requests per day per model. Groq free tier has a much larger daily limit. Saved keys are reused automatically and never removed by saving the other provider. If the selected provider runs out of quota or stops responding, Atlas completes that report with the other saved cloud provider and labels it with the model that answered; your saved provider choice is unchanged.</p><div class="page-actions"><button class="button primary" data-save-llm-config>Save Configuration</button></div></section>
      <section class="card pad"><h3 class="card-title">System status</h3><div class="list"><div class="list-row"><div class="list-main"><strong>Database</strong></div><span class="mono muted">${esc(state.status?.databasePath || "–")}</span></div><div class="list-row"><div class="list-main"><strong>App data</strong></div><span class="mono muted">${esc(state.status?.appDataPath || "–")}</span></div><div class="list-row"><div class="list-main"><strong>Ready snapshots</strong></div><b>${num(state.status?.readyCount)}</b></div><div class="list-row"><div class="list-main"><strong>Last import</strong></div><b>${esc(state.status?.lastImportAt || "–")}</b></div></div></section>
    </div></div>`;
}
