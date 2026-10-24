"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = {items_requested:"Maximum equipment items", days_requested:"Maximum borrowing duration", training_completed:"Completed training prerequisite"};
const MAX_POLICY_BYTES = 2 * 1024 * 1024;
const state = {document:null, view:"rules", stage:0, analysis:null, evaluation:null, cases:[], busy:false, filter:"all", edit:null, retry:null, timer:null};
let toastTimer;
const policies = () => ({current:$("#text-current").value, proposed:$("#text-proposed").value});
const bytes = (text) => new TextEncoder().encode(text).length;

async function api(path, data, method = "POST") {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path.startsWith("/api/analyze") || path.endsWith("/notes") ? 320000 : 30000);
  try {
    const response = await fetch(path, {method, headers:data ? {"Content-Type":"application/json"} : {}, body:data ? JSON.stringify(data) : undefined, signal:controller.signal});
    if (response.status === 204) return null;
    let result;
    try { result = await response.json(); } catch { throw new Error("The server returned an unreadable response. Check that RuleTrace is running."); }
    if (!response.ok) {
      const error = new Error(result.error?.message || "The request failed.");
      error.code = result.error?.code;
      error.issues = result.error?.issues;
      throw error;
    }
    return result;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Your inputs are preserved. Retry after checking the local server.");
    throw error;
  } finally { clearTimeout(timer); }
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => $("#toast").hidden = true, 3500);
}

function showError(error, retry = null) {
  $("#error-title").textContent = error.code ? error.code.replaceAll("_", " ").replace(/^./, c => c.toUpperCase()) : "Something needs attention";
  $("#error-message").textContent = error.message + (error.issues ? "\n" + error.issues.map(i => `${i.location}: ${i.message}`).join("\n") : "");
  $("#error").hidden = false;
  $("#retry").hidden = !retry;
  state.retry = retry;
  $("#error").scrollIntoView({block:"nearest", behavior:"smooth"});
}

function clearError() { $("#error").hidden = true; state.retry = null; }
function notice(message) { $("#notice").textContent = message; $("#notice").hidden = !message; }

function nav() {
  const complete = [!!(state.analysis || state.document), !!state.analysis?.review_complete, !!state.evaluation, false];
  const available = [true, !!(state.analysis || state.document), !!state.analysis?.review_complete, !!(state.evaluation || state.document)];
  $$(".step").forEach((button, index) => {
    button.disabled = state.busy || !available[index];
    button.classList.toggle("active", index === state.stage);
    button.classList.toggle("done", complete[index] && index !== state.stage);
    button.querySelector(".step-number").textContent = complete[index] && index !== state.stage ? "✓" : `0${index+1}`;
    if (index === state.stage) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
  $("#analyze").disabled = state.busy || !policies().current.trim() || !policies().proposed.trim();
  $("#compare-documents").disabled = $("#analyze").disabled;
  $("#to-requests").disabled = state.busy || !state.analysis?.review_complete;
  $("#evaluate").disabled = state.busy || !state.analysis?.review_complete || !state.cases.length;
}

function stage(index) {
  if (state.busy) return;
  if ((index === 1 && !state.analysis && !state.document) || (index === 2 && !state.analysis?.review_complete) || (index === 3 && !state.evaluation && !state.document)) return;
  state.stage = index;
  if (index === 2) state.view = "rules";
  $("#document-review-area").hidden = state.view !== "documents";
  $("#rule-review-area").hidden = state.view === "documents";
  $("#document-report-area").hidden = state.view !== "documents";
  $("#rule-report-area").hidden = state.view === "documents";
  $("#stage-1").setAttribute("aria-labelledby",state.view === "documents" ? "document-changes-title" : "review-title");
  if (index === 3 && state.view === "documents") renderDocumentReport();
  $$(".stage").forEach((section, i) => section.hidden = i !== index);
  nav();
  $("#workspace").focus({preventScroll:true});
  window.scrollTo({top:0, behavior:matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
}

function busy(value) {
  state.busy = value;
  $$("button,input,textarea,select").forEach(control => {
    if (!control.matches("[data-close],#help-button,#dismiss-error")) control.disabled = value;
  });
  $("#workspace").setAttribute("aria-busy", String(value));
  nav();
  if (typeof documentNav === "function") documentNav();
}

function invalidateResults(message = "Requests or rules changed. Previous results are stale; evaluate again.") {
  if (state.evaluation) notice(message);
  state.evaluation = null;
  $("#results").hidden = true;
  $("#results-empty").hidden = false;
  nav();
}

function invalidatePolicies() {
  if (state.document) {
    api(`/api/documents/${state.document.id}`, null, "DELETE").catch(() => {});
    state.document = null;
    notice("Document text changed. Compare these versions again to refresh changes and AI notes.");
  }
  if (state.analysis) {
    api(`/api/analyses/${state.analysis.id}`, null, "DELETE").catch(() => {});
    notice("Policy text changed. Previous proposals, approvals, and results are stale. Analyze these versions again.");
  }
  state.analysis = null;
  invalidateResults();
  nav();
}

function updateSize(version) {
  const size = bytes($(`#text-${version}`).value);
  $(`#size-${version}`).textContent = `${size < 1024 ? size+" B" : size < 1024*1024 ? (size/1024).toFixed(1)+" KB" : (size/(1024*1024)).toFixed(2)+" MB"} / 2 MB`;
  const error = $(`#file-error-${version}`);
  if (size > MAX_POLICY_BYTES) { error.textContent = "Policy exceeds the 2 MB limit."; error.hidden = false; }
  else error.hidden = true;
  nav();
}

async function importPdf(file) {
  const form=new FormData();form.append("file",file);
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),50000);
  try {
    const response=await fetch("/api/policies/extract",{method:"POST",body:form,signal:controller.signal});
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(result.error?.message || "The PDF could not be read. Try another PDF or paste the policy text.");
    return result;
  }catch(error){
    if(error.name === "AbortError")throw new Error("PDF reading timed out. Your previous policy is preserved; try a simpler PDF.");
    throw error;
  }finally{clearTimeout(timer);}
}

async function readFile(version, file) {
  if (!file || state.busy) return;
  let reading=false;
  const status=$(`#upload-status-${version}`);
  try {
    if (!/\.pdf$/i.test(file.name)) throw new Error("Choose a .pdf policy file, or paste text directly below.");
    if (!file.size) throw new Error("This PDF is empty. Choose a policy with selectable text.");
    if (file.size > MAX_POLICY_BYTES) throw new Error("Each PDF must be at most 2 MB.");
    reading=true;busy(true);
    $(`#file-error-${version}`).hidden=true;
    status.textContent="Reading PDF and extracting text…";status.hidden=false;
    const result=await importPdf(file);
    invalidatePolicies();
    $(`#text-${version}`).value=result.text;
    $(`#filename-${version}`).textContent=`${result.filename} · ${result.page_count} ${result.page_count === 1 ? "page":"pages"}`;
    $(`#filename-${version}`).title=`PDF size: ${result.file_bytes.toLocaleString()} bytes`;
    updateSize(version);
    status.textContent=`Text extracted from ${result.page_count} ${result.page_count === 1 ? "page":"pages"}. Check the preview against your PDF before analysis.`;
    toast(`${version === "current" ? "Current" : "Proposed"} PDF loaded`);
  } catch (error) {
    const field = $(`#file-error-${version}`);
    field.textContent=error.message || "The PDF could not be read.";field.hidden=false;
    if(reading)status.hidden=true;
  } finally {
    $(`#file-${version}`).value="";
    if(reading)busy(false);
  }
}

async function health() {
  if (state.busy) return;
  const indicator = $("#model-status");
  indicator.className = "status checking";
  try {
    const data = await api("/api/health", null, "GET");
    indicator.className = `status ${data.status}`;
    $("#model-label").textContent = `${data.model} · ${data.status === "connected" ? "Connected" : "Unavailable"}`;
    indicator.title = `${data.message} ${data.loaded ? "Model is loaded in memory." : "Model will load on the next request."}`;
  } catch {
    indicator.className = "status unavailable";
    $("#model-label").textContent = "Server unavailable";
    indicator.title = "Cannot reach the RuleTrace backend. Click to retry.";
  }
}

async function loadExample() {
  try {
    const data = await api("/api/examples", null, "GET");
    invalidatePolicies();
    for (const version of ["current", "proposed"]) {
      $(`#text-${version}`).value = data[version];
      $(`#filename-${version}`).textContent = `Fictional ${version} policy · example text`;
      updateSize(version);
    }
    state.cases = data.cases;
    renderCases();
    toast("Fictional policies and five example requests loaded");
  } catch (error) { showError(error, loadExample); }
}

async function analyze(fresh = false) {
  if (state.busy) return;
  clearError();
  const inputs = policies();
  if (Object.values(inputs).some(t => !t.trim() || bytes(t) > MAX_POLICY_BYTES)) { showError(new Error("Enter both policies, each at most 2 MB.")); return; }
  busy(true);
  $("#analysis-progress").hidden = false;
  $("#analyze-label").textContent = "Analyzing policies…";
  const start = performance.now();
  $("#elapsed").textContent = "Elapsed: 0s";
  state.timer = setInterval(() => $("#elapsed").textContent = `Elapsed: ${Math.floor((performance.now()-start)/1000)}s`, 1000);
  try {
    const data = await api(`/api/analyze${fresh ? "?fresh=true" : ""}`, inputs);
    state.view = "rules";
    if (state.analysis) api(`/api/analyses/${state.analysis.id}`, null, "DELETE").catch(() => {});
    state.analysis = data;
    invalidateResults();
    notice("");
    renderReview();
    toast(`${data.inference.mode === "cached-local-ollama" ? "Reused verified Gemma extraction" : "Live extraction complete"} in ${data.inference.latency_seconds.toFixed(1)}s. All proposals await your review.`);
    busy(false);
    stage(1);
  } catch (error) {
    $("#model-status").className = "status request_failed";
    $("#model-label").textContent = "Model request failed";
    showError(error, () => analyze(fresh));
  } finally {
    clearInterval(state.timer);
    $("#analysis-progress").hidden = true;
    $("#analyze-label").textContent = "Extract equipment rules";
    busy(false);
  }
}

function ruleValue(rule) {
  if (!rule) return "No proposal";
  if (rule.field === "training_completed") return rule.value ? "Required" : "Not required";
  return `${rule.value} ${rule.field === "days_requested" ? "days" : "items"}`;
}

function badge(entry) {
  return `<span class="badge ${esc(entry.status)}">${entry.status === "pending" ? "✧ AI proposal" : entry.status === "edited" ? "✓ Reviewer edited" : entry.status === "accepted" ? "✓ Approved" : entry.status === "acknowledged" ? "✓ Acknowledged" : "× Rejected"}</span>`;
}

function sourceLink(entry) {
  if (!entry.original) return "";
  return `<button class="source-link" data-source-version="${esc(entry.version)}" data-source-id="${esc(entry.original.paragraph_id)}">${esc(entry.version === "current" ? "Current" : "Proposed")} · ${esc(entry.original.paragraph_id)} ↗</button>`;
}

function ruleEntry(entry, version) {
  if (!entry) return `<div class="entry-box"><span class="entry-version">${esc(version)} policy</span><p class="decision-explanation">No explicit proposal. Omission is unresolved, not permission.</p></div>`;
  return `<div class="entry-box"><div class="entry-top"><span class="entry-version">${entry.version === "current" ? "Current" : "Proposed"} policy</span>${badge(entry)}</div>
    <blockquote>${esc(entry.original.excerpt)}</blockquote>${sourceLink(entry)}
    ${entry.status === "edited" || entry.correction ? `<p class="original-note">Original AI value: ${esc(ruleValue(entry.original))} · Reviewed value: ${esc(ruleValue(entry.rule))}</p>` : ""}
    <div class="entry-actions"><button class="button small accept" data-action="accept" data-entry="${esc(entry.id)}" title="Confirm that Gemma’s original reading matches this policy">${entry.status === "edited" ? "Approve original reading" : "✓ Approve reading"}</button><button class="button small" data-action="edit" data-entry="${esc(entry.id)}" title="Correct the interpreted rule value">Edit</button><button class="button small reject" data-action="reject" data-entry="${esc(entry.id)}" title="Mark the interpretation incorrect; this policy will need review">Reject reading</button></div></div>`;
}

function renderReview() {
  const analysis = state.analysis;
  if (!analysis) return;
  const reused=analysis.inference.mode === "cached-local-ollama";
  $("#rule-provenance").hidden=false;
  $("#rule-provenance").textContent=reused ? `Reused a verified Gemma extraction for identical policy text. Original inference: ${analysis.inference.original_latency_seconds.toFixed(1)}s, generated ${new Date(analysis.inference.generated_at).toLocaleString()}. No fresh inference was run; all interpretations require a new review.` : `Fresh Gemma extraction · ${analysis.inference.model} · ${analysis.inference.latency_seconds.toFixed(1)}s. Every interpretation awaits human review.`;
  const entries = analysis.policies.flatMap(p => p.entries);
  const groups = {Changed:[], Added:[], Unchanged:[], Removed:[]};
  for (const field of Object.keys(labels)) {
    const oldRules = entries.filter(e => e.kind === "rule" && e.version === "current" && e.rule.field === field);
    const newRules = entries.filter(e => e.kind === "rule" && e.version === "proposed" && e.rule.field === field);
    if (!oldRules.length && !newRules.length) continue;
    const oldRule = oldRules[0], newRule = newRules[0];
    const group = !oldRule ? "Added" : !newRule ? "Removed" : oldRule.rule.value === newRule.rule.value ? "Unchanged" : "Changed";
    groups[group].push(`<article class="rule-card"><div class="rule-card-head"><h3>${esc(labels[field])}</h3><span class="rule-type">${field === "training_completed" ? "Prerequisite" : "Maximum permitted"}</span></div><div class="value-diff"><div><strong class="old-value">${esc(ruleValue(oldRule?.rule))}</strong><small>CURRENT</small></div><span class="value-arrow" aria-label="changes to">→</span><div><strong class="new-value">${esc(ruleValue(newRule?.rule))}</strong><small>PROPOSED</small></div></div><div class="review-pair">${ruleEntry(oldRule,"Current")}${ruleEntry(newRule,"Proposed")}</div>${oldRules.slice(1).concat(newRules.slice(1)).map(e => `<div class="callout">Conflicting or repeated proposal</div>${ruleEntry(e,e.version)}`).join("")}</article>`);
  }
  let html = Object.entries(groups).filter(([, cards]) => cards.length).map(([name,cards]) => `<div class="rule-group"><h2 class="group-heading">${esc(name)} rules <span class="count-badge">${cards.length}</span></h2>${cards.join("")}</div>`).join("");
  const unresolved = entries.filter(e => e.kind === "unresolved");
  if (unresolved.length) html += `<div class="rule-group"><h2 class="group-heading">Unresolved clauses <span class="badge warning">${unresolved.length} · Needs review</span></h2>${unresolved.map(e => `<article class="rule-card unresolved-card"><div class="rule-card-head"><h3>${esc(e.reason)}</h3></div><div class="entry-box"><div class="entry-top"><span class="entry-version">${esc(e.version)} policy</span>${badge(e)}</div>${e.original ? `<blockquote>${esc(e.original.excerpt)}</blockquote>${sourceLink(e)}` : ""}<p class="decision-explanation">Acknowledging this clause does not resolve its interpretation. This policy will produce Needs review for all requests.</p><div class="entry-actions"><button class="button small" data-action="acknowledge" data-entry="${esc(e.id)}">Acknowledge unresolved clause</button><button class="button small reject" data-action="reject" data-entry="${esc(e.id)}">Reject interpretation</button></div></div></article>`).join("")}</div>`;
  const context = entries.filter(e => e.kind === "context");
  if (context.length) html += `<details class="context-list" open><summary>Document headings · ${context.length} to check</summary><p class="context-explanation">Confirm that these are titles or descriptive headings with no borrowing conditions.</p>${context.map(e => `<div class="context-entry"><div><strong>${esc(e.version === "current" ? "Current" : "Proposed")} · ${esc(e.original.excerpt)}</strong><p>${esc(e.reason)}</p>${sourceLink(e)}</div><div class="entry-actions">${badge(e)}<button class="button small" data-action="acknowledge" data-entry="${esc(e.id)}">Confirm heading</button><button class="button small reject" data-action="reject" data-entry="${esc(e.id)}">Contains a condition</button></div></div>`).join("")}</details>`;
  $("#rule-cards").innerHTML = html;
  const reviewed = entries.filter(e => e.status !== "pending").length;
  $("#review-count").textContent = `${reviewed} / ${entries.length}`;
  const blockers = Object.values(analysis.readiness).flat();
  $("#review-guidance").textContent = analysis.review_complete ? blockers.length ? "Review recorded. Unresolved or rejected interpretations remain; affected policies return Needs review." : "All interpretations reviewed. You can now test their impact." : "Approve, edit, or reject each interpretation, then check the document headings to continue.";
  nav();
}

function findEntry(id) { return state.analysis?.policies.flatMap(p => p.entries).find(e => e.id === id); }

async function reviewEntry(id, action, correction = null) {
  if (state.busy) return;
  clearError();
  busy(true);
  try {
    state.analysis = await api(`/api/analyses/${state.analysis.id}/rules/${id}/review`, {revision:state.analysis.revision, policies:policies(), action, ...(correction ? {correction} : {})});
    invalidateResults("A reviewed rule changed. Previous results are stale; evaluate again.");
    renderReview();
    if ($("#edit-dialog").open) $("#edit-dialog").close();
    toast(action === "edit" ? "Reviewer correction saved with original evidence" : "Review action recorded");
    const next = $(`[data-entry="${CSS.escape(id)}"][data-action="${action === "edit" ? "edit" : action}"]`);
    requestAnimationFrame(() => next?.focus({preventScroll:true}));
  } catch (error) { showError(error, () => reviewEntry(id,action,correction)); }
  finally { busy(false); }
}

function editEntry(id) {
  const entry = findEntry(id);
  if (!entry?.rule) return;
  state.edit = id;
  $("#edit-description").textContent = `${entry.version === "current" ? "Current" : "Proposed"} policy · ${labels[entry.rule.field]}`;
  $("#edit-evidence").textContent = entry.original.excerpt;
  const training = entry.rule.field === "training_completed";
  $("#edit-value").hidden = training;
  $("#edit-value").required = !training;
  $("#edit-value").disabled = training;
  $("#edit-training").hidden = !training;
  $("#edit-training").disabled = !training;
  $("#edit-value").value = training ? "" : entry.rule.value;
  $("#edit-training").value = String(entry.rule.value);
  $("#edit-dialog").showModal();
  (training ? $("#edit-training") : $("#edit-value")).focus();
}

function showSource(version = null, paragraph = null) {
  if (!state.analysis) return;
  $("#source-content").innerHTML = state.analysis.policies.map(p => `<article class="source-policy"><h3>${p.version === "current" ? "Current policy" : "Proposed policy"}</h3>${p.paragraphs.map(para => `<div id="source-${esc(p.version)}-${esc(para.id)}" class="source-paragraph ${version === p.version && paragraph === para.id ? "highlighted" : ""}"><small>${esc(para.id)}</small>${esc(para.text)}</div>`).join("")}</article>`).join("");
  if (!$("#source-dialog").open) $("#source-dialog").showModal();
  if (version && paragraph) requestAnimationFrame(() => document.getElementById(`source-${version}-${paragraph}`)?.scrollIntoView({block:"center"}));
}

function renderCases() {
  $("#case-rows").innerHTML = state.cases.map((c,i) => `<tr><td><input aria-label="Case ${i+1} name" data-case="${i}" data-key="name" maxlength="80" required value="${esc(c.name)}"></td><td><input aria-label="Case ${i+1} items requested" data-case="${i}" data-key="items_requested" type="number" min="1" max="365" step="1" placeholder="Unknown" value="${esc(c.items_requested)}"></td><td><input aria-label="Case ${i+1} days requested" data-case="${i}" data-key="days_requested" type="number" min="1" max="365" step="1" placeholder="Unknown" value="${esc(c.days_requested)}"></td><td><select aria-label="Case ${i+1} training completed" data-case="${i}" data-key="training_completed"><option value="true" ${c.training_completed === true ? "selected" : ""}>Yes</option><option value="false" ${c.training_completed === false ? "selected" : ""}>No</option><option value="unknown" ${c.training_completed === null ? "selected" : ""}>Unknown</option></select></td><td><button class="icon-button" data-remove-case="${i}" aria-label="Remove case ${i+1}">×</button></td></tr>`).join("");
  nav();
}

async function loadCases() {
  try {
    state.cases = (await api("/api/examples",null,"GET")).cases;
    invalidateResults(); renderCases(); toast("Five fictional requests loaded");
  } catch(error) { showError(error, loadCases); }
}

async function evaluateCases() {
  if (state.busy) return;
  clearError();
  for (const input of $$("#case-rows input")) { if (!input.reportValidity()) return; }
  if (state.cases.some(c => !c.name.trim())) { showError(new Error("Every case needs a name.")); return; }
  busy(true);
  $("#evaluate").textContent = "Evaluating…";
  try {
    state.evaluation = await api("/api/evaluate", {analysis_id:state.analysis.id, revision:state.analysis.revision, policies:policies(), cases:state.cases});
    state.filter = "all";
    notice("");
    renderResults(); renderReport();
    $("#case-editor").open = false;
    toast(`${state.evaluation.summary.total} requests evaluated against the reviewed policies`);
  } catch(error) { showError(error,evaluateCases); }
  finally { $("#evaluate").innerHTML = 'Evaluate requests <span aria-hidden="true">→</span>'; busy(false); }
}

function outcome(decision) {
  const allowed = decision.outcome === "Allowed under reviewed rules", disallowed = decision.outcome === "Disallowed under reviewed rules";
  return `<span class="outcome ${allowed ? "allowed" : disallowed ? "disallowed" : "needs-review"}"><span class="outcome-icon" aria-hidden="true">${allowed ? "✓" : disallowed ? "×" : "!"}</span><span>${esc(decision.outcome)}</span></span>`;
}

function reason(decision) {
  const important = decision.conditions.filter(c => c.status !== "pass");
  if (important.length) return important.map(c => c.explanation).join(" ");
  if (decision.outcome === "Needs review") return decision.explanations.join(" ");
  return "All reviewed conditions pass.";
}

function renderResults() {
  if (!state.evaluation) return;
  $("#results-empty").hidden = true;
  $("#results").hidden = false;
  const summary = state.evaluation.summary;
  $("#metrics").innerHTML = [["total","Requests evaluated","≡",""],["changed","Changed outcomes","↗","changed"],["allowed_both","Allowed under both","✓","allowed"],["needs_review","Requests needing review","!","review"]].map(([key,label,icon,cls]) => `<div class="metric ${cls}"><div><strong>${summary[key]}</strong><span class="metric-icon" aria-hidden="true">${icon}</span></div><span>${label}</span></div>`).join("");
  $$("[data-filter]").forEach(b => { const active = b.dataset.filter === state.filter; b.classList.toggle("selected",active); b.setAttribute("aria-pressed",String(active)); });
  const results = state.evaluation.results.filter(r => state.filter === "all" || (state.filter === "changed" ? r.changed : r.current.outcome === "Needs review" || r.proposed.outcome === "Needs review"));
  $("#result-rows").innerHTML = results.length ? results.map(r => `<tr class="${r.changed ? "changed-row" : ""}"><td><span class="result-name">${esc(r.case.name)}</span><span class="case-facts">${r.case.items_requested ?? "?"} items · ${r.case.days_requested ?? "?"} days<br>Training: ${r.case.training_completed === null ? "Unknown" : r.case.training_completed ? "Yes" : "No"}</span>${r.changed ? '<br><span class="badge">↗ Changed</span>' : ""}</td><td>${outcome(r.current)}<p class="decision-explanation">${esc(reason(r.current))}</p></td><td>${outcome(r.proposed)}<p class="decision-explanation">${esc(reason(r.proposed))}</p></td><td><span class="decision-explanation">${r.changed ? "The policy change affects this request." : r.current.outcome === "Needs review" ? "An interpretation or input still needs review." : "The outcome is unchanged."}</span><details class="result-details"><summary>Inspect rules & sources</summary>${["current","proposed"].map(version => `<div class="condition-detail"><strong>${version === "current" ? "Current" : "Proposed"} policy</strong>${r[version].conditions.length ? r[version].conditions.map(c => { const entry = findEntry(c.rule_id); return `<div><span aria-label="${esc(c.status)}">${c.status === "pass" ? "✓" : c.status === "fail" ? "×" : "!"}</span> ${esc(c.explanation)} ${entry ? sourceLink(entry) : ""}</div>`; }).join("") : `<p>${esc(r[version].explanations.join(" "))}</p>`}</div>`).join("")}</details></td></tr>`).join("") : '<tr><td colspan="4" class="filter-empty">No cases match this filter.</td></tr>';
  nav();
}

function metadata(rows) { return rows.map(([key,value]) => `<div class="metadata-row"><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join(""); }

function renderReport() {
  if (!state.evaluation || !state.analysis) return;
  const summary = state.evaluation.summary, analysis = state.analysis;
  const entries = analysis.policies.flatMap(p => p.entries);
  const unresolved = entries.filter(e => e.kind === "unresolved" || e.status === "rejected");
  const used = new Set(state.evaluation.results.flatMap(r => [...r.current.conditions,...r.proposed.conditions].map(c => c.rule_id))).size;
  $("#report-summary").innerHTML = [["Requests evaluated",summary.total],["Changed outcomes",summary.changed],["Requiring review",summary.needs_review]].map(([label,value]) => `<div class="report-line"><span>${label}</span><strong>${value}</strong></div>`).join("");
  $("#review-metadata").innerHTML = metadata([["Review completion",analysis.review_complete ? "Complete" : "Incomplete"],["Approved rules",entries.filter(e => e.kind === "rule" && ["accepted","edited"].includes(e.status)).length],["Reviewed rules used",used],["Reviewer corrections",entries.filter(e => e.status === "edited").length],["Unresolved / rejected entries",unresolved.length],["Review revision",analysis.revision]]) + (unresolved.length ? `<ul class="report-unresolved">${unresolved.map(e => `<li>${esc(e.version)}: ${esc(e.reason || "Rejected rule interpretation")}</li>`).join("")}</ul>` : "");
  $("#inference-metadata").innerHTML = metadata([["Original inference latency",analysis.inference.original_latency_seconds == null ? "Fresh inference" : `${analysis.inference.original_latency_seconds.toFixed(2)} seconds`],["Generated at",analysis.inference.generated_at || "See analysis timestamp"],["Actual model",analysis.inference.model],["Inference mode",analysis.inference.mode],["Measured pair latency",`${analysis.inference.latency_seconds.toFixed(2)} seconds`],["Model requests incl. repairs",analysis.inference.attempts],["Model digest",analysis.inference.digest],["Evaluated at",new Date(state.evaluation.created_at).toLocaleString()]]);
}

async function downloadReportFile(path, data, filename, format) {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),format === "pdf" ? 120000 : 30000);
  try {
    const response=await fetch(path,{method:data ? "POST":"GET",headers:data ? {"Content-Type":"application/json"}:{},body:data ? JSON.stringify(data):undefined,signal:controller.signal});
    if(!response.ok){
      const payload=await response.json().catch(()=>({}));
      const error=new Error(payload.error?.message || "The report could not be generated. Try again.");error.code=payload.error?.code;throw error;
    }
    const expected=format === "pdf" ? "application/pdf":"application/json";
    if(!response.headers.get("content-type")?.includes(expected))throw new Error("The server returned an unexpected report format.");
    const blob=await response.blob();
    const url=URL.createObjectURL(blob), link=document.createElement("a");
    link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){
    if(error.name === "AbortError")throw new Error("Report generation timed out. Your comparison is preserved; try the export again.");
    throw error;
  }finally{clearTimeout(timer);}
}

async function downloadReport(format="pdf") {
  if (!state.evaluation || state.busy) return;
  clearError(); busy(true);
  const button=$(format === "pdf" ? "#download":"#download-json"), label=button.textContent;
  button.textContent=format === "pdf" ? "Preparing PDF…":"Exporting audit data…";
  try {
    await downloadReportFile(`/api/report?format=${format}`,{evaluation_id:state.evaluation.id, policies:policies()},`ruletrace-report.${format}`,format);
    toast(format === "pdf" ? "PDF report downloaded":"JSON audit data downloaded");
  } catch(error) { showError(error,()=>downloadReport(format)); }
  finally { button.textContent=label;busy(false); }
}

for (const version of ["current","proposed"]) {
  $(`#text-${version}`).addEventListener("input", () => { invalidatePolicies(); $(`#filename-${version}`).textContent = "Edited text"; $(`#upload-status-${version}`).hidden=true; updateSize(version); });
  $(`#file-${version}`).addEventListener("change", event => readFile(version,event.target.files[0]));
  const drop = $(`#drop-${version}`);
  drop.addEventListener("dragover", event => { event.preventDefault(); if (!state.busy) drop.classList.add("dragging"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("dragging"));
  drop.addEventListener("drop", event => { event.preventDefault(); drop.classList.remove("dragging"); if (event.dataTransfer.files.length !== 1) { const error = $(`#file-error-${version}`); error.textContent = "Drop one PDF file at a time."; error.hidden = false; return; } readFile(version,event.dataTransfer.files[0]); });
}

$("#load-example").addEventListener("click",loadExample);
$("#analyze").addEventListener("click",() => analyze(false));
$("#model-status").addEventListener("click",health);
$("#help-button").addEventListener("click", () => $("#help-dialog").showModal());
$("#dismiss-error").addEventListener("click",clearError);
$("#retry").addEventListener("click", () => { const retry = state.retry; clearError(); retry?.(); });
$$(".step").forEach(b => b.addEventListener("click", () => stage(Number(b.dataset.stage))));
$$("[data-close]").forEach(b => b.addEventListener("click", () => document.getElementById(b.dataset.close).close()));
$("#view-sources").addEventListener("click", () => showSource());
$("#fresh-analysis").addEventListener("click", () => { state.stage=0; $$(".stage").forEach((section,i)=>section.hidden=i!==0); analyze(true); });
$("#to-requests").addEventListener("click", () => stage(2));
$("#to-report").addEventListener("click", () => { state.view="rules"; renderReport(); stage(3); });
$("#download").addEventListener("click",()=>downloadReport("pdf"));
$("#download-json").addEventListener("click",()=>downloadReport("json"));
$("#evaluate").addEventListener("click",evaluateCases);
$("#load-cases").addEventListener("click",loadCases);
$("#add-case").addEventListener("click", () => { if (state.cases.length >= 100) { showError(new Error("Use at most 100 cases.")); return; } state.cases.push({name:`Case ${state.cases.length+1}`,items_requested:null,days_requested:null,training_completed:null}); invalidateResults(); renderCases(); $("#case-rows tr:last-child input")?.focus(); });

document.addEventListener("click", event => {
  const source = event.target.closest("[data-source-id]");
  if (source) { showSource(source.dataset.sourceVersion, source.dataset.sourceId); return; }
  const action = event.target.closest("[data-entry]");
  if (action && !state.busy) { if (action.dataset.action === "edit") editEntry(action.dataset.entry); else reviewEntry(action.dataset.entry,action.dataset.action); }
  const remove = event.target.closest("[data-remove-case]");
  if (remove && !state.busy) { state.cases.splice(Number(remove.dataset.removeCase),1); invalidateResults(); renderCases(); }
});

$("#case-rows").addEventListener("input", event => {
  const control = event.target;
  if (!control.matches("[data-case]")) return;
  const key = control.dataset.key;
  state.cases[Number(control.dataset.case)][key] = key === "name" ? control.value : key === "training_completed" ? control.value === "unknown" ? null : control.value === "true" : control.value === "" ? null : Number(control.value);
  invalidateResults();
});

$("#edit-form").addEventListener("submit", event => {
  event.preventDefault();
  const entry = findEntry(state.edit);
  if (!entry) return;
  const training = entry.rule.field === "training_completed";
  const value = training ? $("#edit-training").value === "true" : Number($("#edit-value").value);
  reviewEntry(entry.id,"edit", {field:entry.rule.field, operator:training ? "eq" : "lte", value});
});

$$("[data-filter]").forEach(b => b.addEventListener("click", () => { state.filter = b.dataset.filter; renderResults(); }));
renderCases(); nav(); health();
setInterval(health,30000);
