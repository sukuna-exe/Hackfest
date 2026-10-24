"use strict";

const documentUI = {offset:0, filter:"all", selected:new Set(), editing:null};

async function compareDocuments() {
  if (state.busy) return;
  clearError();
  busy(true);
  const button = $("#compare-documents");
  button.textContent = "Comparing…";
  try {
    const result = await api("/api/documents/compare",policies());
    if (state.document) api(`/api/documents/${state.document.id}`,null,"DELETE").catch(()=>{});
    state.document = result;
    state.view = "documents";
    documentUI.offset=0; documentUI.filter="all"; documentUI.selected.clear();
    renderDocumentChanges();
    notice("");
    busy(false); stage(1);
    toast(`Text comparison ready in ${result.latency_seconds.toFixed(2)}s. No AI inference used for this comparison.`);
  } catch(error) { showError(error,compareDocuments); }
  finally { button.innerHTML='Compare documents <span aria-hidden="true">→</span>'; busy(false); }
}

function highlightedChange(before,after,side) {
  if (!before || !after) return esc(side === "before" ? before || "" : after || "");
  const a=before.split(/(\s+)/), b=after.split(/(\s+)/);
  let start=0, end=0;
  while(start<a.length && start<b.length && a[start]===b[start]) start++;
  while(end<a.length-start && end<b.length-start && a[a.length-1-end]===b[b.length-1-end]) end++;
  const tokens=side === "before" ? a:b;
  const middle=tokens.slice(start,end ? -end:undefined).join("");
  return esc(tokens.slice(0,start).join(""))+(middle ? `<mark class="${side === "before" ? "removed-text":"added-text"}">${esc(middle)}</mark>`:"")+esc(end ? tokens.slice(-end).join(""):"");
}

function changeNote(change) {
  const note=state.document.notes[change.id];
  if (!note) return '<div class="note-empty">Select this change to ask Gemma about its wording.</div>';
  return `<div class="document-note"><div class="entry-top"><span class="note-label">✧ GEMMA INTERPRETATION · SELECTED CHANGE</span><span class="badge ${esc(note.status)}">${esc(note.status === "pending" ? "Awaiting your review":note.status)}</span></div><p>${esc(note.reviewed_summary || note.original.summary)}</p>${note.reviewed_summary ? `<details><summary>Original AI proposal</summary><p>${esc(note.original.summary)}</p></details>`:""}<div class="note-meta">${esc(note.original.attention)} · ${esc(note.inference.model)} · ${note.inference.latency_seconds.toFixed(1)}s · Covers this change only</div><div class="entry-actions"><button class="button small accept" data-note-action="accept" data-change="${esc(change.id)}">✓ Approve reading</button><button class="button small" data-note-action="edit" data-change="${esc(change.id)}">Edit</button><button class="button small reject" data-note-action="reject" data-change="${esc(change.id)}">Reject reading</button></div></div>`;
}

function renderDocumentChanges() {
  const d=state.document;
  if(!d) return;
  const c=d.coverage;
  $("#document-review-area").innerHTML=`<div class="page-heading compact"><div><p class="eyebrow">DOCUMENT INTELLIGENCE / CHANGES</p><h1 id="document-changes-title">The difference.<br><span>With all the context.</span></h1><p class="lede">Compare source text sections. Select specific changes for a separate Gemma review.</p><p class="comparison-format-note">Blank-line formatting and spacing around sections are ignored. Both original texts are retained in your report.</p></div><span class="comparison-speed">↗ ${d.latency_seconds.toFixed(2)}s<span>Text comparison · no AI call</span></span></div>
    <div class="document-metrics">${[[d.summary.changed_sections,"Changed sections"],[d.summary.modified,"Modified"],[d.summary.added,"Added"],[d.summary.removed,"Removed"]].map(([value,label])=>`<div><strong>${value}</strong><span>${label}</span></div>`).join("")}</div>
    <div class="coverage-banner"><span>✧</span><p><strong>You choose what Gemma reviews.</strong> ${c.ai_reviewed_changes} of ${c.total_changes} changes have AI notes; ${c.human_reviewed_notes} notes have human review. Text differences alone do not establish insurance coverage or eligibility.</p></div>
    <div class="document-toolbar"><div class="filters" role="group" aria-label="Filter document changes">${["all","modified","added","removed"].map(kind=>`<button data-document-filter="${kind}" class="${documentUI.filter===kind?"selected":""}" aria-pressed="${documentUI.filter===kind}">${kind==="all"?"All changes":kind[0].toUpperCase()+kind.slice(1)}</button>`).join("")}</div><button class="button" data-document-report>View report ↗</button></div>
    <div class="selection-toolbar"><span id="selection-count">${documentUI.selected.size} selected · up to 3 changes per review</span><button class="button primary" id="interpret-changes" ${documentUI.selected.size ? "":"disabled"}>✧ Review selected with Gemma</button></div>
    <div id="document-note-progress" class="loading-panel" role="status" hidden><span class="spinner"></span><div><strong>Gemma is reviewing your selected changes</strong><p>This is real local inference. The complete text comparison stays available.</p><span id="document-note-elapsed">Elapsed: 0s</span></div></div>
    <div class="document-change-list">${d.changes.length ? d.changes.map(change=>`<article class="document-change-card"><header><label class="change-selection"><input type="checkbox" data-select-change="${esc(change.id)}" ${documentUI.selected.has(change.id)?"checked":""}><span>${esc(change.id.replace("change-","Change "))}</span></label><span class="change-kind ${esc(change.kind)}">${esc(change.kind)}</span></header><div class="text-diff-grid"><section><div class="diff-version"><span>− CURRENT</span><span>${esc(change.before?.id || "No previous text")}</span></div><p>${change.before ? highlightedChange(change.before.text,change.after?.text,"before"):'<span class="muted">This section is new.</span>'}</p></section><section><div class="diff-version"><span>+ PROPOSED</span><span>${esc(change.after?.id || "Text removed")}</span></div><p>${change.after ? highlightedChange(change.before?.text,change.after.text,"after"):'<span class="muted">This section was removed.</span>'}</p></section></div>${changeNote(change)}</article>`).join(""):'<div class="empty-state"><h2>No text changes in this view.</h2><p>Both documents may be identical, or no changes match the selected filter.</p></div>'}</div>
    <div class="document-pagination"><button class="button small" id="document-previous" ${d.offset===0?"disabled":""}>← Previous</button><span>${d.filtered_total ? d.offset+1:0}–${Math.min(d.offset+d.limit,d.filtered_total)} of ${d.filtered_total} changes</span><button class="button small" id="document-next" ${d.offset+d.limit>=d.filtered_total?"disabled":""}>Next →</button></div>`;
  $("#stage-1").setAttribute("aria-labelledby","document-changes-title");
  nav();
}

async function loadDocumentPage(offset=0,filter=documentUI.filter) {
  if(state.busy || !state.document) return;
  busy(true); clearError();
  try {
    state.document=await api(`/api/documents/${state.document.id}/changes?offset=${offset}&kind=${filter}`,null,"GET");
    documentUI.offset=offset; documentUI.filter=filter;
    renderDocumentChanges();
  }catch(error){showError(error,()=>loadDocumentPage(offset,filter));}
  finally{busy(false); documentNav();}
}

function documentNav(){
  if(!state.document || state.view!=="documents")return;
  $("#interpret-changes").disabled=state.busy || !documentUI.selected.size;
  $("#document-previous").disabled=state.busy || state.document.offset===0;
  $("#document-next").disabled=state.busy || state.document.offset+state.document.limit>=state.document.filtered_total;
}

async function interpretSelectedChanges(){
  if(state.busy || !documentUI.selected.size)return;
  busy(true);clearError();
  $("#document-note-progress").hidden=false;
  const start=performance.now();
  const timer=setInterval(()=>$("#document-note-elapsed").textContent=`Elapsed: ${Math.floor((performance.now()-start)/1000)}s`,1000);
  try{
    const result=await api(`/api/documents/${state.document.id}/notes`,{change_ids:[...documentUI.selected]});
    state.document={...state.document,notes:result.notes,coverage:result.coverage,review_revision:result.review_revision};
    documentUI.selected.clear();
    renderDocumentChanges();
    toast("Selected changes interpreted. Review each AI reading against its sources.");
  }catch(error){showError(error,interpretSelectedChanges);}
  finally{clearInterval(timer);$("#document-note-progress").hidden=true;busy(false);documentNav();}
}

async function reviewDocumentNote(changeId,action,correction=null){
  if(state.busy)return;
  busy(true);clearError();
  try{
    const result=await api(`/api/documents/${state.document.id}/notes/${changeId}/review`,{action,revision:state.document.review_revision,...(correction===null?{}:{correction})});
    state.document={...state.document,notes:result.notes,coverage:result.coverage,review_revision:result.review_revision};
    renderDocumentChanges();
    if($("#note-edit-dialog").open)$("#note-edit-dialog").close();
    toast("Human review recorded with original sources and proposal");
  }catch(error){showError(error,()=>reviewDocumentNote(changeId,action,correction));}
  finally{busy(false);documentNav();}
}

function renderDocumentReport(){
  const d=state.document;if(!d)return;
  $("#document-report-area").innerHTML=`<div class="page-heading compact"><div><p class="eyebrow">DOCUMENT INTELLIGENCE / REPORT</p><h1>Every change.<br><span>Every source.</span></h1><p class="lede">Your complete text comparison, with the scope and review status of any AI notes.</p></div></div><div class="report-grid"><article class="report-card"><span class="report-symbol">↳</span><span class="overline">DOCUMENT COMPARISON</span><h2>The evidence goes with you.</h2>${[["Changed sections",d.summary.changed_sections],["AI-reviewed changes",`${d.coverage.ai_reviewed_changes} / ${d.coverage.total_changes}`],["Human-reviewed AI notes",d.coverage.human_reviewed_notes]].map(([k,v])=>`<div class="report-line"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join("")}<button class="button primary" id="download-document-report">↓ Download PDF report</button><button class="text-button audit-export" id="download-document-json">Export audit data (JSON)</button><p class="muted">Readable changes, exact source passages, and review status. Full original texts are included in the JSON audit export.</p></article><article class="audit-card"><h2>Scope of this report</h2><dl>${metadata([["Comparison method","Deterministic text difference"],["Text comparison latency",`${d.latency_seconds.toFixed(3)} seconds`],["AI scope",d.coverage.ai_reviewed_changes ? "Selected changes only":"No AI review requested"],["Coverage or eligibility decision","Not performed"],["Unchanged source sections",d.summary.unchanged_sections],["Review revision",d.review_revision]])}</dl><p class="report-disclaimer">A text replacement can change meaning, but the comparison does not decide how a real insurance or other policy applies to a person. Unreviewed changes remain unreviewed.</p></article></div>`;
}

async function downloadDocumentReport(format="pdf"){
  if(state.busy)return;busy(true);clearError();
  const button=$(format === "pdf" ? "#download-document-report":"#download-document-json"), label=button.textContent;
  button.textContent=format === "pdf" ? "Preparing PDF…":"Exporting audit data…";
  try{
    await downloadReportFile(`/api/documents/${state.document.id}/report?format=${format}`,null,`ruletrace-document-report.${format}`,format);
    toast(format === "pdf" ? "PDF comparison report downloaded":"JSON audit data downloaded");
  }catch(error){showError(error,()=>downloadDocumentReport(format));}finally{button.textContent=label;busy(false);documentNav();}
}

$("#compare-documents").addEventListener("click",compareDocuments);
document.addEventListener("change",event=>{
  const checkbox=event.target.closest("[data-select-change]");if(!checkbox)return;
  const id=checkbox.dataset.selectChange;
  if(checkbox.checked){if(documentUI.selected.size>=3){checkbox.checked=false;toast("Select up to three changes for each Gemma review");return;}documentUI.selected.add(id);}else documentUI.selected.delete(id);
  $("#selection-count").textContent=`${documentUI.selected.size} selected · up to 3 changes per review`;documentNav();
});
document.addEventListener("click",event=>{
  const filter=event.target.closest("[data-document-filter]");if(filter){loadDocumentPage(0,filter.dataset.documentFilter);return;}
  if(event.target.closest("#document-previous")){loadDocumentPage(Math.max(0,state.document.offset-20));return;}
  if(event.target.closest("#document-next")){loadDocumentPage(state.document.offset+20);return;}
  if(event.target.closest("#interpret-changes")){interpretSelectedChanges();return;}
  if(event.target.closest("[data-document-report]")){state.view="documents";stage(3);return;}
  if(event.target.closest("#download-document-report")){downloadDocumentReport("pdf");return;}
  if(event.target.closest("#download-document-json")){downloadDocumentReport("json");return;}
  const review=event.target.closest("[data-note-action]");if(!review)return;
  if(review.dataset.noteAction!=="edit"){reviewDocumentNote(review.dataset.change,review.dataset.noteAction);return;}
  documentUI.editing=review.dataset.change;
  const note=state.document.notes[documentUI.editing];
  $("#note-correction").value=note.reviewed_summary||note.original.summary;$("#note-edit-dialog").showModal();
});
$("#note-edit-form").addEventListener("submit",event=>{event.preventDefault();reviewDocumentNote(documentUI.editing,"edit",$("#note-correction").value);});
