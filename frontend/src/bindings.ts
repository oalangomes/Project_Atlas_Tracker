function applyClubAliasLocally(teamId:number, displayName:string):void {
    const patch=(item:any,idKey:string,nameKey:string)=>{if(Number(item?.[idKey])===teamId)item[nameKey]=displayName;};
    state.careers.forEach((career:any)=>{patch(career,"initial_team_ea_id","initial_team_name");patch(career.latestSnapshot,"managed_team_ea_id","managed_team_name");});
    state.snapshots.forEach((snapshot:any)=>patch(snapshot,"managed_team_ea_id","managed_team_name"));
}

function commissionReportMarkup(result:any,params:any):string {
    const report=result.report||{},catalog=new Map((result.fact_catalog||[]).map((item:any)=>[item.id,item.label]));
    const refs=(ids:string[])=>esc((ids||[]).map((id:string)=>catalog.get(id)||id).join(" · "));
    const kindLabel=(kind:string)=>kind==="fact"?tr("claimFact"):kind==="hypothesis"?tr("claimHypothesis"):tr("claimInference");
    const items=(values:any[])=>values?.length?`<ul>${values.map((item:any)=>`<li><span class="commission-claim-kind ${esc(item.kind||"inference")}">${esc(kindLabel(item.kind))}</span> ${esc(item.text)}${item.kind==="hypothesis"&&item.limitations?`<small class="commission-claim-limit">${tr("claimLimit")}: ${esc(item.limitations)}</small>`:""}<small class="table-subline">Evidence: ${refs(item.fact_refs)}</small></li>`).join("")}</ul>`:"";
    const list=(values:any[],label:string)=>values?.length?`<h4>${label}</h4>${items(values)}`:"";
    const note=report.commission_note?.text?`<p class="commission-note"><strong>${tr("commissionNote")}:</strong> ${esc(report.commission_note.text)}<small>${refs(report.commission_note.fact_refs)}</small></p>`:"";
    const summaryKind=report.summary?.kind||"inference";
    const provenance=`<details class="report-provenance"><summary>Evidence coverage and validation</summary><small>${num(result.coverage?.previous_linked_matches)} prior linked matches · ${num(result.validation?.accepted_claims)} claims kept · ${num(result.validation?.rejected_claims)} filtered · ${esc(result.validation?.interpretation_quality||tr("interpretationNotScored"))}</small></details>`;
    const coachContext=(result.fact_catalog||[]).find((item:any)=>item.id==="coach_context")?.value||[];
    const followup=commissionFollowupForm(report.information_requests, {...params,model:result.model,coach_context:coachContext});
    const coachNote=result.coach_context_received?`<p class="chart-note">Coach-provided context was sent separately from imported Atlas facts.</p>`:"";
    const providerNote=result.provider_note?`<p class="data-note">${esc(result.provider_note)}</p>`:"";
    return `<div class="commission-report-head"><strong>${esc(report.summary?.text||"Report generated.")}</strong><small><span class="commission-claim-kind ${esc(summaryKind)}">${esc(kindLabel(summaryKind))}</span> · ${esc(result.model||"Ollama")}${result.cached?" · cached report":" · generated now"}<br>Atlas facts: ${refs(report.summary?.fact_refs)}</small></div>${providerNote}${report.summary?.limitations?`<p class="commission-claim-limit">${tr("claimLimit")}: ${esc(report.summary.limitations)}</p>`:""}${note}${report.formation?`<section class="commission-formation"><span>Suggested formation · based on Atlas squad data</span><strong>${esc(report.formation.shape)}</strong><p>${esc(report.formation.reason)}</p><small>Evidence: ${refs(report.formation.fact_refs)}</small></section>`:""}${list(report.strengths,"Strengths")}${list(report.development_areas,"Development areas")}${list(report.training_suggestions,"Training suggestions")}${list(report.observations,"Observed performance")}${list(report.recommendations,"Staff recommendations")}${coachNote}${followup}${provenance}<p class="chart-note">AI interpretation is separate from imported facts. Atlas does not record injury, suspension or physical availability; this report cannot confirm them.</p>`;
}

async function submitCommissionFollowup(form:HTMLFormElement):Promise<void> {
    const output=form.closest("[data-commission-report-output]") as HTMLElement|null;
    const questions=Array.from(form.querySelectorAll<HTMLInputElement>('input[name="question"]'));
    const answers=Array.from(form.querySelectorAll<HTMLTextAreaElement>('textarea[name="answer"]'));
    const priorQuestions=Array.from(form.querySelectorAll<HTMLInputElement>('input[name="prior_question"]'));
    const priorAnswers=Array.from(form.querySelectorAll<HTMLInputElement>('input[name="prior_answer"]'));
    const prior=priorQuestions.map((question,index)=>({question:question.value,answer:String(priorAnswers[index]?.value||"").trim()})).filter(item=>item.answer);
    const clarifications=[...prior,...questions.map((question,index)=>({question:question.value,answer:String(answers[index]?.value||"").trim()})).filter(item=>item.answer)];
    if(!clarifications.length){toast("Answer at least one question.");return;}
    const button=form.querySelector<HTMLButtonElement>('button[type="submit"]');
    if(button)button.disabled=true;
    if(output)output.innerHTML=`<p>${esc(tr("contextSent"))}</p>`;
    const payload:any={snapshot_id:Number(form.dataset.snapshotId||state.snapshotId),mode:String(form.dataset.mode||"match"),force_refresh:true,model:String(form.dataset.model||"")||undefined,clarifications};
    if(Number(form.dataset.fixtureId||0))payload.fixture_id=Number(form.dataset.fixtureId);
    if(Number(form.dataset.playerEaId||0))payload.player_ea_id=Number(form.dataset.playerEaId);
    try{
        const started:any=await api(`/api/careers/${state.careerId}/commission/report-jobs`,{method:"POST",body:JSON.stringify(payload)});
        let job:any={status:started.status},attempt=0;
        while(job.status==="queued"||job.status==="running"){
            await new Promise(resolve=>setTimeout(resolve,1500));
            job=await api(`/api/careers/${state.careerId}/commission/report-jobs/${started.job_id}`);
            if(++attempt>240)throw new Error("The follow-up is taking longer than expected; refresh the saved report later.");
        }
        if(job.status==="failed")throw new Error(job.error||"The follow-up failed.");
        const result=job.result||{};
        if(output)output.innerHTML=result.available?commissionReportMarkup(result,payload):`<p>${esc(result.message||"AI report unavailable.")}</p>`;
    }catch(error:any){if(output)output.innerHTML=`<p class="status-badge amber">${esc(String(error?.message||error))}</p>`;}
    finally{if(button)button.disabled=false;}
}


function bindContent() {
    if(!(content as any).__commissionFollowupBound){
        content.addEventListener("submit",(event:Event)=>{
            const form=event.target as HTMLFormElement;
            if(!form.matches("[data-commission-followup]"))return;
            event.preventDefault();void submitCommissionFollowup(form);
        });
        (content as any).__commissionFollowupBound=true;
    }
    bindSortableTables();
    $$('[data-club-tab]', content).forEach((button:any)=>button.onclick=async(event:Event)=>{event.preventDefault();state.clubTab=button.dataset.clubTab||"overview";await renderClub();applyIcons(content);bindContent();});
    $$('[data-competition-list-tab]', content).forEach((button:any)=>button.onclick=async(event:Event)=>{event.preventDefault();state.competitionListTab=button.dataset.competitionListTab||"deeper";await renderCompetitions();applyIcons(content);bindContent();});
    const womensToggle=$<HTMLInputElement>('[data-hide-womens-football]',content);
    if(womensToggle) womensToggle.onchange=async()=>{const settings=await api('/api/settings',{method:'POST',body:JSON.stringify({hideWomensFootball:womensToggle.checked})});if(state.status)state.status.settings=settings;clearApiCache();toast(womensToggle.checked?'Women’s football is hidden':'Women’s football is visible');await render();};
    const languageSave=$<HTMLButtonElement>('[data-save-atlas-language]',content);
    if(languageSave)languageSave.onclick=async()=>{const language=$<HTMLSelectElement>('[data-atlas-language]',content)?.value||'pt-BR';const settings=await api('/api/settings',{method:'POST',body:JSON.stringify({language})});if(state.status)state.status.settings=settings;clearApiCache();updateSystemUi();toast(tr('languageSaved'));await render();applyIcons(content);bindContent();};

    const refreshSetup=async()=>{await renderSetup();applyIcons(content);bindContent();};
    const workspaceCreateForm=$<HTMLFormElement>('[data-workspace-create-form]',content);
    if(workspaceCreateForm) workspaceCreateForm.onsubmit=async(event:SubmitEvent)=>{event.preventDefault();const name=String(new FormData(workspaceCreateForm).get('name')||'').trim();if(!name)return;await api('/api/workspaces/create',{method:'POST',body:JSON.stringify({name})});toast(`Career save “${name}” created`);await refreshSetup();};
    const workspaceCloneForm=$<HTMLFormElement>('[data-workspace-clone-form]',content);
    if(workspaceCloneForm) workspaceCloneForm.onsubmit=async(event:SubmitEvent)=>{event.preventDefault();const name=String(new FormData(workspaceCloneForm).get('name')||'').trim();if(!name)return;await api('/api/workspaces/clone',{method:'POST',body:JSON.stringify({name})});toast(`Branch “${name}” created`);await refreshSetup();};
    $$<HTMLButtonElement>('[data-workspace-activate]',content).forEach(button=>button.onclick=async()=>{const workspaceId=String(button.dataset.workspaceActivate||'');if(!workspaceId||!confirm('Switch to this career save? Project Atlas Tracker will close cleanly and use it on the next start.'))return;toast('Switching career save');await api('/api/workspaces/activate',{method:'POST',body:JSON.stringify({workspaceId,restart:true})});});
    $$<HTMLButtonElement>('[data-workspace-bind-approve]',content).forEach(button=>button.onclick=async()=>{const workspaceId=String(button.dataset.workspaceBindApprove||'');if(!workspaceId||!confirm('Assign the detected FC26 career to this career save?'))return;const result=await api('/api/workspaces/binding/approve',{method:'POST',body:JSON.stringify({workspaceId})});clearApiCache();await refreshCareerBootstrap(false);const imported=Array.isArray(result?.imports)&&result.imports.some((item:any)=>['imported','duplicate'].includes(String(item?.status||'')));if(state.careerId&&state.snapshotId){toast(imported?'Career assigned · snapshot imported':'Career assigned');navigate('overview');}else{toast('Assignment saved · import still needs attention');await refreshSetup();}});
    $$<HTMLButtonElement>('[data-workspace-bind-cancel]',content).forEach(button=>button.onclick=async()=>{await api('/api/workspaces/binding/cancel',{method:'POST',body:JSON.stringify({workspaceId:String(button.dataset.workspaceBindCancel||'')})});toast('Detected assignment discarded');await refreshSetup();});
    $$<HTMLButtonElement>('[data-workspace-archive]',content).forEach(button=>button.onclick=async()=>{const workspaceId=String(button.dataset.workspaceArchive||''),name=String(button.dataset.workspaceName||'Career');if(!workspaceId||!confirm(`Archive “${name}”? Its data will be retained.`))return;await api('/api/workspaces/archive',{method:'POST',body:JSON.stringify({workspaceId,archived:true})});toast(`“${name}” archived`);await refreshSetup();});
    $$<HTMLButtonElement>('[data-workspace-restore]',content).forEach(button=>button.onclick=async()=>{const workspaceId=String(button.dataset.workspaceRestore||''),name=String(button.dataset.workspaceName||'Career');await api('/api/workspaces/archive',{method:'POST',body:JSON.stringify({workspaceId,archived:false})});toast(`“${name}” restored`);await refreshSetup();});
    $$<HTMLButtonElement>('[data-save-llm-config]', content).forEach(button => button.onclick = async () => {
        const provider = $<HTMLSelectElement>('[data-llm-provider]', content)?.value;
        if (!provider) return;
        const keys: Record<string, string> = {};
        $$<HTMLInputElement>('[data-llm-key]', content).forEach(input => {
            const name = String(input.dataset.llmKey || '');
            const value = String(input.value || '').trim();
            if (name && value) keys[name] = value;
        });
        try {
            await api('/api/llm/config', { method: 'POST', body: JSON.stringify({ provider, keys }) });
            state.llmProvider = provider;
            state.llmKeys = { ...state.llmKeys, ...keys };
            const saved = Object.keys(keys).length;
            toast(saved ? `AI configuration saved (${saved} key${saved > 1 ? 's' : ''})` : 'AI provider saved');
        } catch (error: any) {
            toast(`Error saving configuration: ${error.message}`);
        }
        await renderSetup();
        applyIcons(content);
        bindContent();
    });

    $$<HTMLButtonElement>('[data-remove-llm-key]', content).forEach(button => button.onclick = async () => {
        const name = String(button.dataset.removeLlmKey || '');
        if (!name || !confirm(`Remove the saved ${name} key?`)) return;
        try {
            await api('/api/llm/config', { method: 'POST', body: JSON.stringify({ remove: [name] }) });
            delete state.llmKeys[name];
            toast(`${name} key removed`);
        } catch (error: any) {
            toast(`Error removing key: ${error.message}`);
        }
        await renderSetup();
        applyIcons(content);
        bindContent();
    });

    $$('[data-route]', content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate(n.dataset.route);});
    $$('[data-player]', content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate('player',{id:Number(n.dataset.player),tab:'commission'});});
    $$('[data-club]', content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate('club',{id:Number(n.dataset.club)});});
    $$('[data-competition]', content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate('competition',{id:Number(n.dataset.competition),tab:state.competitionTab||'results'});});
    $$('[data-world-competition]', content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate('world-competition',{id:Number(n.dataset.worldCompetition)});});
    $$('[data-match]', content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate('match',{id:Number(n.dataset.match)});});
    $$('[data-player-tab]', content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate('player',{...state.routeData,tab:n.dataset.playerTab},true);});
    $$('[data-player-comparison-scope]',content).forEach((n:any)=>n.onclick=async(e:any)=>{e.stopPropagation();state.playerComparisonScope=n.dataset.playerComparisonScope==='league'?'league':'club';await renderPlayer();applyIcons(content);bindContent();});
    $$<HTMLSelectElement>('[data-player-comparison-mode]',content).forEach(select=>select.onchange=async()=>{state.playerComparisonMode=select.value==='position'?'position':'group';await renderPlayer();applyIcons(content);bindContent();});
    $$('[data-competition-tab]',content).forEach((n:any)=>n.onclick=(e:any)=>{e.stopPropagation();navigate('competition',{...state.routeData,tab:n.dataset.competitionTab},true);});
    $$('[data-loan-scope]',content).forEach((n:any)=>n.onclick=async(e:any)=>{e.stopPropagation();state.loanScope=n.dataset.loanScope||'club';await renderLoans();applyIcons(content);bindContent();});
    $$<HTMLSelectElement>('[data-movement-season]',content).forEach(select=>select.onchange=async()=>{state.movementSeasonIndex=Number(select.value);state.movementEditId=null;clearApiCache();if(state.route==='loans')await renderLoans();else await renderTransfers();applyIcons(content);bindContent();});
    $$<HTMLButtonElement>('[data-movement-editor-open]',content).forEach(button=>button.onclick=async()=>{state.movementEditKind=button.dataset.movementEditorOpen==='loan'?'loan':'transfer';state.movementEditId=null;if(state.route==='loans')await renderLoans();else await renderTransfers();applyIcons(content);bindContent();});
    $$<HTMLButtonElement>('[data-movement-editor-edit]',content).forEach(button=>button.onclick=async()=>{state.movementEditKind=button.dataset.movementEditorEdit==='loan'?'loan':'transfer';state.movementEditId=Number(button.dataset.id);if(state.route==='loans')await renderLoans();else await renderTransfers();applyIcons(content);bindContent();});
    $$<HTMLButtonElement>('[data-movement-editor-delete]',content).forEach(button=>button.onclick=async()=>{if(!confirm('Delete this manual history entry?'))return;await api(`/api/careers/${state.careerId}/manual-data/transactions/delete`,{method:'POST',body:JSON.stringify({id:Number(button.dataset.id)})});state.movementEditKind=null;state.movementEditId=null;clearApiCache();toast('Manual history entry deleted');if(state.route==='loans')await renderLoans();else await renderTransfers();applyIcons(content);bindContent();});

    $$<HTMLSelectElement>('[data-analysis-season]',content).forEach(select=>select.onchange=async()=>{state.analysisSeasonIndex=Number(select.value);clearApiCache();await renderAnalysis();applyIcons(content);bindContent();});
    $$<HTMLSelectElement>('[data-records-season]',content).forEach(select=>select.onchange=async()=>{state.recordsSeasonIndex=Number(select.value);clearApiCache();await renderRecords();applyIcons(content);bindContent();});
    $$<HTMLSelectElement>('[data-season-report-season]',content).forEach(select=>select.onchange=async()=>{state.seasonReportSeasonIndex=Number(select.value);clearApiCache();await renderSeasonReport();applyIcons(content);bindContent();});
    $$('[data-season-report-tab]',content).forEach((n:any)=>n.onclick=async(e:any)=>{e.stopPropagation();state.seasonReportTab=n.dataset.seasonReportTab||'overview';await renderSeasonReport();applyIcons(content);bindContent();});
    const awardPlayerSelect=$<HTMLSelectElement>('[data-season-award-player]',content);
    if(awardPlayerSelect)awardPlayerSelect.onchange=()=>{const option=awardPlayerSelect.selectedOptions[0],name=$<HTMLInputElement>('[data-season-award-name]',content);if(name&&option?.dataset.name)name.value=option.dataset.name;};
    const awardForm=$<HTMLFormElement>('[data-season-award-form]',content);
    if(awardForm)awardForm.onsubmit=async(event:SubmitEvent)=>{event.preventDefault();const fd=new FormData(awardForm);await api(`/api/careers/${state.careerId}/manual-data/awards/save`,{method:'POST',body:JSON.stringify({id:fd.get('id')||null,seasonIndex:state.seasonReportSeasonIndex,awardKey:fd.get('awardKey'),awardLabel:fd.get('awardLabel'),playerEaId:fd.get('playerEaId')||null,displayName:fd.get('displayName'),relatedTransactionId:fd.get('relatedTransactionId')||null,reason:fd.get('reason')})});clearApiCache();toast('Season award saved');await renderSeasonReport();applyIcons(content);bindContent();};
    $$<HTMLButtonElement>('[data-season-award-delete]',content).forEach(button=>button.onclick=async()=>{if(!confirm('Delete this manager award?'))return;await api(`/api/careers/${state.careerId}/manual-data/awards/delete`,{method:'POST',body:JSON.stringify({id:Number(button.dataset.seasonAwardDelete)})});clearApiCache();toast('Season award deleted');await renderSeasonReport();applyIcons(content);bindContent();});
    const reportNoteForm=$<HTMLFormElement>('[data-season-report-note-form]',content);
    if(reportNoteForm)reportNoteForm.onsubmit=async(event:SubmitEvent)=>{event.preventDefault();const fd=new FormData(reportNoteForm);await api(`/api/careers/${state.careerId}/manual-data/season-report/save`,{method:'POST',body:JSON.stringify({seasonIndex:state.seasonReportSeasonIndex,summaryNote:fd.get('summaryNote')})});clearApiCache();toast('Season note saved');await renderSeasonReport();applyIcons(content);bindContent();};
    $$<HTMLButtonElement>('[data-season-report-print]',content).forEach(button=>button.onclick=()=>window.print());
    $$<HTMLButtonElement>('[data-season-report-csv]',content).forEach(button=>button.onclick=()=>exportSeasonReportCsv());
    $$<HTMLButtonElement>('[data-season-report-image]',content).forEach(button=>button.onclick=()=>exportSeasonInfographic(button.dataset.seasonReportImage==='square'?'square':'portrait'));

    const clubNameForm=$<HTMLFormElement>('[data-club-name-form]',content);
    if(clubNameForm)clubNameForm.onsubmit=async(event:SubmitEvent)=>{event.preventDefault();const fd=new FormData(clubNameForm),teamId=Number(fd.get('eaTeamId')),displayName=String(fd.get('displayName')||'').trim();await api(`/api/careers/${state.careerId}/club-names/save`,{method:'POST',body:JSON.stringify({eaTeamId:teamId,displayName,note:fd.get('note')})});clearApiCache();applyClubAliasLocally(teamId,displayName);state.careers=await api<CareerSummary[]>('/api/careers');await loadSnapshots(true);fillSelectors();updateSystemUi();toast(`Club name applied: ${displayName}`);await renderClub();applyIcons(content);bindContent();};
    $$<HTMLButtonElement>('[data-club-name-reset]',content).forEach(button=>button.onclick=async()=>{if(!confirm('Remove the custom club name?'))return;const teamId=Number(button.dataset.clubNameReset);await api(`/api/careers/${state.careerId}/club-names/delete`,{method:'POST',body:JSON.stringify({eaTeamId:teamId})});clearApiCache();state.careers=await api<CareerSummary[]>('/api/careers');await loadSnapshots(true);fillSelectors();updateSystemUi();toast('Snapshot club name restored');await renderClub();applyIcons(content);bindContent();});

    const resetCareerButton=$<HTMLButtonElement>('[data-reset-career]',content);
    if(resetCareerButton)resetCareerButton.onclick=async()=>{
        const targetSelect=$<HTMLSelectElement>('[data-reset-target]',content);
        const deleteFiles=$<HTMLInputElement>('[data-reset-delete-files]',content);
        const targetId=Number(targetSelect?.value||0);
        const target=state.snapshots.find((item:any)=>Number(item.id)===targetId);
        if(!targetId||!target)return;
        const mode=deleteFiles?.checked?'permanently delete':'archive';
        const warning=`Reset this career to ${dateText(target.career_date)} (Snapshot #${num(target.import_sequence)})?\n\nAll later snapshots, MatchStats, transfer pulses and derived career state will be removed. Raw export folders will be ${mode}d. A database backup is created first.`;
        if(!confirm(warning))return;
        resetCareerButton.disabled=true;
        resetCareerButton.textContent='Resetting…';
        try{
            const result=await api<JsonRecord>(`/api/careers/${state.careerId}/reset`,{method:'POST',body:JSON.stringify({snapshotId:targetId,deleteRawFiles:Boolean(deleteFiles?.checked)})});
            clearApiCache();
            state.snapshotId=targetId;
            await refreshCareerBootstrap(true);
            fillSelectors();updateSystemUi();
            toast(`Career reset · ${num(result.removedSnapshots)} later snapshot${Number(result.removedSnapshots)===1?'':'s'} removed`);
            await render();
        }catch(error:any){
            const message=String(error?.message||error||'Unknown reset error');
            toast(`Reset failed: ${message}`);
            alert(`Career reset failed.\n\n${message}\n\nThe database backup was kept and the live career was not changed.`);
        }finally{
            resetCareerButton.disabled=false;
            resetCareerButton.textContent='Reset to selected snapshot';
        }
    };

    $$('[data-analysis-tab]',content).forEach((n:any)=>n.onclick=async(e:any)=>{e.stopPropagation();state.analysisTab=n.dataset.analysisTab||'overview';await renderAnalysis();applyIcons(content);bindContent();});
    $$('[data-commission-ollama]',content).forEach((n:any)=>n.onclick=async()=>{const out=$('[data-commission-ai-output]',content);n.disabled=true;n.textContent='Analyzing locally…';if(out)out.textContent='Waiting for the local model. The Atlas panel remains available.';try{const result:any=await api(`/api/careers/${state.careerId}/commission/ollama`,{method:'POST',body:JSON.stringify({snapshot_id:Number(n.dataset.snapshotId)})});if(out){const notes=result.observations||[];out.innerHTML=notes.length?notes.map((item:any)=>`<p><strong>EA ID ${esc(item.player_ea_id)}</strong> ${esc(item.text)}<small class="table-subline">Evidence: ${esc(item.evidence.join(' · '))}</small></p>`).join(''):esc(result.message||'No additional observations returned.');}n.textContent=result.fallback?'Try local analysis again':'Refresh local analysis';}catch(error:any){if(out)out.textContent=`Local analysis failed. The Atlas statistics remain available. ${String(error?.message||error)}`;n.textContent='Try local analysis again';}finally{n.disabled=false;}});
    const commissionMode=$<HTMLSelectElement>('[data-commission-mode]',content);
    const updateCommissionReportControls=()=>{const mode=commissionMode?.value||'match';const matchWrap=$('[data-commission-fixture-wrap]',content),nextWrap=$('[data-commission-next-wrap]',content),playerWrap=$('[data-commission-player-wrap]',content);if(matchWrap)matchWrap.toggleAttribute('hidden',mode!=='match');if(nextWrap)nextWrap.toggleAttribute('hidden',mode!=='next_match');if(playerWrap)playerWrap.toggleAttribute('hidden',mode!=='player');};
    if(commissionMode){commissionMode.onchange=updateCommissionReportControls;updateCommissionReportControls();}
    $$<HTMLButtonElement>('[data-commission-report]',content).forEach(button=>button.onclick=async()=>{
      const mode=String(button.dataset.mode||commissionMode?.value||'match');
      const fixture=mode==='next_match'?$<HTMLSelectElement>('[data-commission-next-fixture]',content):$<HTMLSelectElement>('[data-commission-fixture]',content);
      const player=$<HTMLSelectElement>('[data-commission-player]',content);
      const target=String(button.dataset.reportTarget||button.closest('[data-report-slot]')?.getAttribute('data-report-slot')||'');
      const output=target?$(`[data-report-slot="${target}"]`,content):$('[data-commission-report-output]',content);
      const payload:any={snapshot_id:Number(button.dataset.snapshotId||state.snapshotId),mode,force_refresh:button.dataset.forceRefresh==='1'};
      const fixtureId=Number(button.dataset.fixtureId||fixture?.value||0),playerId=Number(button.dataset.playerEaId||player?.value||0);
      if(mode==='player'||mode==='player_form'||mode==='player_season'||mode==='match_player')payload.player_ea_id=playerId;
      if(mode==='match'||mode==='match_player'||mode==='next_match')payload.fixture_id=fixtureId;
      button.disabled=true;const oldLabel=button.textContent;button.textContent='Starting staff report…';if(output)output.innerHTML='<p>The report is running in the background. You can keep using Atlas while the AI provider works.</p>';
      try{
        const started:any=await api(`/api/careers/${state.careerId}/commission/report-jobs`,{method:'POST',body:JSON.stringify(payload)});
        let job:any={status:started.status},attempt=0;
        while(job.status==='queued'||job.status==='running'){
          await new Promise(resolve=>setTimeout(resolve,1500));
          job=await api(`/api/careers/${state.careerId}/commission/report-jobs/${started.job_id}`);
          attempt++;
          if(output&&attempt%20===0)output.innerHTML='<p>The AI provider is still working in the background. This does not block the rest of Atlas.</p>';
          if(attempt>240)throw new Error('Report is taking longer than expected; it continues in the background. Refresh the report later to use its cache.');
        }
        if(job.status==='failed')throw new Error(job.error||'The background report failed.');
        const result:any=job.result||{};
        if(output){
          if(!result.available){output.innerHTML=`<p>${esc(result.message||'AI report unavailable.')}</p>`;}
          else {
            output.innerHTML=commissionReportMarkup(result,payload);
            if(mode==="player"&&target==="player-p1-integrated"){
              const root=button.closest(".player-p1-ai");
              root?.querySelector(".player-p1-warnings")?.remove();
              const lang=atlasLanguage();
              const messages=[result.review_required?(lang==="pt-BR"?"Algumas conclusões exigem revisão":lang==="es-ES"?"Algunas conclusiones requieren revisión":"Some findings require review"):null,result.report?.summary?.model_generated===false?(lang==="pt-BR"?"Resumo de fallback determinístico":lang==="es-ES"?"Resumen determinístico de apoyo":"Deterministic fallback summary"):null].filter(Boolean);
              if(messages.length)output.insertAdjacentHTML("afterbegin",`<div class="player-p1-warnings">${messages.map(msg=>`<p>${esc(msg)}</p>`).join("")}</div>`);
            }
          }
        }
      }catch(error:any){if(output)output.textContent=`Report failed. Atlas metrics are unchanged. ${String(error?.message||error)}`;}
      finally{
        button.disabled=false;
        const p1Ready=mode==="player"&&target==="player-p1-integrated"&&!!output?.querySelector(".commission-report-head");
        if(p1Ready){
          const badge=button.closest(".player-p1-ai")?.querySelector(".card-header .status-badge");
          if(badge){badge.textContent="ready";badge.classList.remove("amber");badge.classList.add("good");}
          button.textContent=atlasLanguage()==="pt-BR"?"Atualizar análise":atlasLanguage()==="es-ES"?"Actualizar análisis":"Refresh analysis";
          button.dataset.forceRefresh="1";
        }else{button.textContent=oldLabel;button.dataset.forceRefresh='0';}
      }
    });
    const retroButton=$<HTMLButtonElement>('[data-retroactive-reports]',content);
    const retroOutput=$<HTMLElement>('[data-retroactive-progress]',content);
    const pollRetroactive=async(jobId:string)=>{
      const win=window as any;
      if(win.__atlasRetroPollingId===jobId)return;
      win.__atlasRetroPollingId=jobId;
      if(retroButton)retroButton.disabled=true;
      try{
        let job:any;
        do{
          job=await api(`/api/careers/${state.careerId}/commission/retroactive-report-jobs/${jobId}`);
          if(retroOutput){
            const totalCount=Number(job.total_tasks??job.total??0),completedCount=Number(job.completed_tasks??job.completed??0),total=num(totalCount),completed=num(completedCount),pct=totalCount?Math.round(completedCount*100/totalCount):0;
            const heading=job.status==='paused_offline'?tr('retroPaused'):job.status==='complete_with_warnings'||job.status==='failed'?tr('retroFailed'):job.status==='complete'?tr('retroDone'):tr('retroWorking');
            retroOutput.innerHTML=`<p><strong>${heading}</strong> · ${completed}/${total} (${pct}%)</p><p>${esc(job.current_task||job.current||'')}<br>Generated: ${num(job.generated)} · reused: ${num(job.reused)} · review: ${num(job.review_required)} · failed: ${num(job.failed)} · missing: ${num(job.skipped_missing_data)} · pending: ${num(job.pending)}</p>${job.backup_path?`<small>${tr('retroBackup')}: ${esc(job.backup_path)}</small>`:''}${job.error?`<p class="status-badge amber">${esc(job.error)}</p>`:''}`;
            if(retroButton&&['paused_offline','paused','complete_with_warnings','failed'].includes(job.status))retroButton.textContent=tr('retroResume');
          }
          if(['queued','running'].includes(job.status))await new Promise(resolve=>setTimeout(resolve,2000));
        }while(['queued','running'].includes(job.status));
        sessionStorage.removeItem(`atlas-retro-${state.careerId}`);
        if(job.status==='complete')toast(tr('retroDone'));
      }catch(error:any){
        if(retroOutput)retroOutput.innerHTML=`<p class="status-badge amber">${esc(String(error?.message||error))}</p>`;
        sessionStorage.removeItem(`atlas-retro-${state.careerId}`);
      }finally{
        win.__atlasRetroPollingId='';
        if(retroButton)retroButton.disabled=false;
      }
    };
    if(retroButton)retroButton.onclick=async()=>{
      retroButton.disabled=true;
      if(retroOutput)retroOutput.innerHTML=`<p>${tr('retroBackup')}…</p>`;
      try{
        const started:any=await api(`/api/careers/${state.careerId}/commission/retroactive-report-jobs`,{method:'POST',body:JSON.stringify({season_index:Number(retroButton.dataset.seasonIndex)})});
        sessionStorage.setItem(`atlas-retro-${state.careerId}`,started.job_id);
        await pollRetroactive(started.job_id);
      }catch(error:any){
        retroButton.disabled=false;
        if(retroOutput)retroOutput.innerHTML=`<p class="status-badge amber">${esc(String(error?.message||error))}</p>`;
      }
    };
    const pendingRetro=sessionStorage.getItem(`atlas-retro-${state.careerId}`);
    if(pendingRetro&&retroButton)void pollRetroactive(pendingRetro);
    $$('[data-snapshot]',content).forEach((n:any)=>n.onclick=async()=>{state.snapshotId=Number(n.dataset.snapshot);snapshotSelect.value=String(state.snapshotId);updateSystemUi();await render();});
    $$('[data-action]',content).forEach((n:any)=>n.onclick=()=>handleAction(n.dataset.action));
    $$('[data-media-source]',content).forEach((n:any)=>n.onclick=async()=>{const result=await api('/api/media/sources/pick',{method:'POST',body:JSON.stringify({sourceType:n.dataset.mediaSource})});if(result.ok){toast('Media source added');await renderMedia();applyIcons(content);bindContent();}});
    $$('[data-remove-source]',content).forEach((n:any)=>n.onclick=async()=>{await api('/api/media/sources/remove',{method:'POST',body:JSON.stringify({sourceId:Number(n.dataset.removeSource)})});await renderMedia();applyIcons(content);bindContent();});
    $$('[data-assign-asset]',content).forEach((n:any)=>n.onclick=async()=>{const id=Number(n.dataset.assignAsset),entityType=$(`[data-assign-type="${id}"]`,content).value,eaId=Number($(`[data-assign-id="${id}"]`,content).value);await api('/api/media/assign',{method:'POST',body:JSON.stringify({assetId:id,entityType,eaId})});clearApiCache();toast('Media asset assigned');await renderMedia();applyIcons(content);bindContent();});
    $$('[data-save-competition-media]',content).forEach((n:any)=>n.onclick=async()=>{const objectId=Number(n.dataset.saveCompetitionMedia),input=$(`[data-competition-media-id="${objectId}"]`,content),raw=String(input?.value||'').trim();await api('/api/media/competition-mappings',{method:'POST',body:JSON.stringify({snapshotId:state.snapshotId,competitionObjectId:objectId,mediaCompetitionId:raw?Number(raw):null})});clearApiCache();toast(raw?'Competition logo assigned':'Assignment removed');await renderMedia();applyIcons(content);bindContent();});
}

function bindShell() {
    careerSelect.onchange = async () => { clearApiCache(); state.careerId = Number(careerSelect.value); state.movementSeasonIndex = null; state.movementEditKind = null; state.movementEditId = null; state.analysisSeasonIndex = null; state.seasonReportSeasonIndex = null; state.clubTab="overview"; state.competitionListTab="deeper"; await loadSnapshots(); fillSelectors(); updateSystemUi(); navigate("overview"); };
    snapshotSelect.onchange = () => { clearApiCache(); state.snapshotId = Number(snapshotSelect.value); state.compareTo = state.snapshotId; updateSystemUi(); navigate(state.route, state.routeData, false); };
    $("#backButton").onclick = () => goHistory(-1);
    $("#forwardButton").onclick = () => goHistory(1);
    $("#scanButton").onclick = () => handleAction("scan");
    $("#workspaceBadge").onclick = () => navigate("setup");
    $("#globalSearch").onclick = openSearch;
    $("#windowMenu").onclick = toggleStatus;
    $$('[data-route]', $("#mainNav")).forEach((n: any) => n.onclick = () => navigate(n.dataset.route));
    $(".brand").onclick = () => navigate("overview");
    document.addEventListener("keydown", (e: any) => {
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
    document.addEventListener("mousedown", (e: any) => {
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
async function handleAction(action: any) {
    if (action === "setup") { navigate("setup"); return; }
    if (action === "scan") {
        clearApiCache();
        const r = await api<JsonRecord[]>("/api/import/scan", { method: "POST", body: "{}" });
        await refreshCareerBootstrap(false);
        const pending = r.some((item: any) => String(item?.status || "") === "pending");
        toast(pending ? "Career detected · confirm assignment" : `${r.length} export packages processed`);
        if (pending && !state.careers.length) { navigate("setup"); return; }
        await render(); return;
    }
    if (action === "rebuild-competition-media") {
        await api("/api/media/competition-mappings/rebuild", { method: "POST", body: JSON.stringify({ snapshotId: state.snapshotId }) });
        toast("Competition mappings rebuilt");
        if (state.route === "media") { await renderMedia(); applyIcons(content); bindContent(); }
        return;
    }
    if (action === "scan-media") {
        const r = await api("/api/media/scan", { method: "POST", body: "{}" });
        toast(r.alreadyRunning ? "A media index is already running" : "Quick media index started");
        startMediaProgressPolling();
        if (state.route === "media") { await renderMedia(); applyIcons(content); bindContent(); }
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
        if (r.ok) { state.status = await api<StatusResponse>("/api/status"); updateSystemUi(); toast("EA FC reference data updated"); await render(); }
        return;
    }
    if (action === "pick-folder") {
        const r = await api("/api/config/pick-folder", { method: "POST", body: "{}" });
        if (r.path) { $("#rootPath", content).value = r.path; state.status = await api<StatusResponse>("/api/status"); updateSystemUi(); }
        return;
    }
    if (action === "save-root") {
        const path = $("#rootPath", content).value;
        await api("/api/config/snapshot-root", { method: "POST", body: JSON.stringify({ path }) });
        state.status = await api<StatusResponse>("/api/status"); updateSystemUi(); toast("Snapshot folder saved");
    }
}

async function pollStatus() {
    try {
        const oldSnapshotCount = Number(state.status?.snapshotCount || 0);
        const oldCareerDate = String(state.careerClock?.careerDate || "");
        state.status = await api<StatusResponse>("/api/status");
        if (state.careerId)
            state.careerClock = await api<CareerClock>(`/api/careers/${state.careerId}/clock`);
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
    state.searchResults = await api<SearchResult[]>(`/api/search?snapshot_id=${state.snapshotId}&q=${encodeURIComponent(q)}`);
    state.searchIndex = state.searchResults.length ? 0 : -1;
    renderSearchResults();
}
function renderSearchResults() { searchResults.innerHTML = state.searchResults.map((r: any, i: any) => `<button class="palette-result ${i === state.searchIndex ? "active" : ""}" data-search-index="${i}"><span class="avatar ${r.type === "club" ? "club" : ""}">${esc(initials(r.label))}</span><span class="palette-result-copy"><strong>${esc(r.label)}</strong><small>${esc(r.subtitle || r.type)} · ID ${num(r.id)}</small></span><span>${r.type === "player" ? `${positionBadge(r.extra)} ${overallBadge(r.meta)}` : r.type === "club" ? overallBadge(r.meta) : statusBadge("Competition")}</span></button>`).join("") || '<div class="muted" style="padding:18px">No results.</div>'; $$('[data-search-index]', searchResults).forEach((b: any) => b.onclick = () => { state.searchIndex = Number(b.dataset.searchIndex); openSearchSelection(); }); }
function moveSearch(delta: any) {
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
function debounce(fn: any, ms: any) { let timer: number | undefined; return (...args: any[]) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); }; }
