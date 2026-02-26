const apiBase = "";

const qs = (s) => document.querySelector(s);
const actionItemsBody = qs("#actionItemsBody");
const mappedList = qs("#mappedList");
const unmappedList = qs("#unmappedList");
const suggestionsList = qs("#suggestionsList");
const momText = qs("#momText");
const historyBody = qs("#historyBody");
const lastRunId = qs("#lastRunId");
const manualMappingsBody = qs("#manualMappingsBody");

async function request(path, method = "GET", body = null) {
  const res = await fetch(`${apiBase}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

function badge(type) {
  return `<span class="pill ${type}">${type}</span>`;
}

async function loadActionItems() {
  const items = await request("/action-items");
  actionItemsBody.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.id}</td>
      <td>${item.title}</td>
      <td>${badge(item.type)}</td>
      <td><button class="warn" data-id="${item.id}">Delete</button></td>
    `;
    actionItemsBody.appendChild(row);
  }
}

async function loadHistory() {
  const runs = await request("/analysis-runs");
  historyBody.innerHTML = "";
  for (const run of runs) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${run.id}</td>
      <td>${run.created_at}</td>
      <td>${run.mapped_count}</td>
      <td>${run.unmapped_count}</td>
      <td>${run.suggestion_count}</td>
      <td>${run.transcript_preview}</td>
    `;
    historyBody.appendChild(row);
  }
}

async function loadManualMappings(runId) {
  if (!runId) {
    manualMappingsBody.innerHTML = "";
    return;
  }
  const mappings = await request(`/mappings/manual?run_id=${encodeURIComponent(runId)}`);
  manualMappingsBody.innerHTML = "";
  for (const m of mappings) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${m.id}</td>
      <td>${m.analysis_run_id}</td>
      <td>${badge(m.feedback_type)}</td>
      <td>${m.action_item_id}</td>
      <td>${m.feedback_text}</td>
      <td>
        <button class="secondary" data-edit="${m.id}" style="margin-bottom: 4px;">Edit</button>
        <button class="warn" data-delete="${m.id}">Delete</button>
      </td>
    `;
    manualMappingsBody.appendChild(row);
  }
}

async function addActionItem(e) {
  e.preventDefault();
  const id = qs("#itemId").value.trim();
  const title = qs("#itemTitle").value.trim();
  const description = qs("#itemDescription").value.trim();
  const type = qs("#itemType").value;
  const criteria = qs("#itemCriteria").value.split("\n").map((x) => x.trim()).filter(Boolean);

  if (!id || !title) {
    alert("Action item id and title are required");
    return;
  }

  await request("/action-items", "POST", {
    id,
    title,
    description,
    type,
    acceptance_criteria: criteria,
  });

  e.target.reset();
  await loadActionItems();
}

async function deleteActionItem(id) {
  await request(`/action-items/${encodeURIComponent(id)}`, "DELETE");
  await loadActionItems();
}

function renderFeedback(container, items, filterType) {
  const filtered = filterType === "All" ? items : items.filter((x) => x.type === filterType);
  container.innerHTML = "";
  if (filtered.length === 0) {
    container.innerHTML = "<li>No items</li>";
    return;
  }
  for (const fb of filtered) {
    const li = document.createElement("li");
    const mapped = fb.mapped_action_item_id ? ` -> ${fb.mapped_action_item_id}` : "";
    li.innerHTML = `${badge(fb.type)} ${fb.text}${mapped} (conf: ${fb.confidence.toFixed(2)})`;
    container.appendChild(li);
  }
}

function renderSuggestions(items, filterType) {
  suggestionsList.innerHTML = "";
  if (items.length === 0) {
    suggestionsList.innerHTML = "<li>No suggestions</li>";
    return;
  }
  for (const s of items) {
    const li = document.createElement("li");
    li.textContent = `${s.action_item_id}: ${s.suggestion} (${s.rationale})`;
    suggestionsList.appendChild(li);
  }
}

let lastAnalyze = null;

async function runAnalyze() {
  const transcript = qs("#transcript").value.trim();
  const useMock = qs("#useMock").checked;
  const filterType = qs("#filterType").value;

  if (transcript.length < 10) {
    alert("Transcript must be at least 10 characters");
    return;
  }

  const result = await request("/analyze", "POST", { transcript, use_mock: useMock });
  lastAnalyze = result;
  lastRunId.textContent = result.analysis_run_id ?? "N/A";
  qs("#manualRunId").value = result.analysis_run_id ?? "";
  qs("#manualMappingId").value = "";
  renderFeedback(mappedList, result.mapped_feedback, filterType);
  renderFeedback(unmappedList, result.unmapped_feedback, filterType);
  renderSuggestions(result.suggestions, filterType);
  await loadHistory();
  await loadManualMappings(result.analysis_run_id);
}

function applyFilter() {
  if (!lastAnalyze) return;
  const filterType = qs("#filterType").value;
  renderFeedback(mappedList, lastAnalyze.mapped_feedback, filterType);
  renderFeedback(unmappedList, lastAnalyze.unmapped_feedback, filterType);
  renderSuggestions(lastAnalyze.suggestions, filterType);
}

async function generateMom() {
  const transcript = qs("#transcript").value.trim();
  const useMock = qs("#useMock").checked;
  if (transcript.length < 10) {
    alert("Transcript must be at least 10 characters");
    return;
  }
  const result = await request("/mom", "POST", { transcript, use_mock: useMock });
  momText.textContent = result.minutes;
}

async function saveManualMapping(e) {
  e.preventDefault();
  const mappingId = Number(qs("#manualMappingId").value || "0");
  const analysis_run_id = Number(qs("#manualRunId").value);
  const action_item_id = qs("#manualActionItemId").value.trim();
  const feedback_type = qs("#manualType").value;
  const feedback_text = qs("#manualFeedbackText").value.trim();

  if (!analysis_run_id || !action_item_id || !feedback_text) {
    alert("Run ID, action item ID, and feedback text are required");
    return;
  }

  if (mappingId) {
    await request(`/mappings/manual/${mappingId}`, "PUT", {
      action_item_id,
      feedback_type,
      feedback_text,
    });
    alert("Manual mapping updated");
  } else {
    await request("/mappings/manual", "POST", {
      analysis_run_id,
      action_item_id,
      feedback_type,
      feedback_text,
    });
    alert("Manual mapping saved");
  }
  qs("#manualMappingId").value = "";
  await loadManualMappings(analysis_run_id);
  await reloadRun();
}

async function reloadRun() {
  const runId = Number(qs("#manualRunId").value);
  const filterType = qs("#filterType").value;
  if (!runId) {
    alert("Enter a valid Run ID");
    return;
  }
  const run = await request(`/analysis-runs/${runId}`);
  lastAnalyze = run.result;
  lastRunId.textContent = run.id;
  renderFeedback(mappedList, run.result.mapped_feedback, filterType);
  renderFeedback(unmappedList, run.result.unmapped_feedback, filterType);
  renderSuggestions(run.result.suggestions, filterType);
  await loadManualMappings(runId);
}

async function deleteMapping(mappingId) {
  await request(`/mappings/manual/${mappingId}`, "DELETE");
  await reloadRun();
}

async function editMapping(mappingId) {
  const runId = Number(qs("#manualRunId").value);
  if (!runId) {
    alert("Run ID is required");
    return;
  }
  const mappings = await request(`/mappings/manual?run_id=${encodeURIComponent(runId)}`);
  const target = mappings.find((m) => m.id === mappingId);
  if (!target) {
    alert("Mapping not found");
    return;
  }
  qs("#manualMappingId").value = String(target.id);
  qs("#manualActionItemId").value = target.action_item_id;
  qs("#manualType").value = target.feedback_type;
  qs("#manualFeedbackText").value = target.feedback_text;
}

function hookEvents() {
  qs("#addActionItemForm").addEventListener("submit", (e) => {
    addActionItem(e).catch((err) => alert(err.message));
  });

  actionItemsBody.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-id]");
    if (!btn) return;
    deleteActionItem(btn.dataset.id).catch((err) => alert(err.message));
  });

  qs("#analyzeBtn").addEventListener("click", () => runAnalyze().catch((err) => alert(err.message)));
  qs("#momBtn").addEventListener("click", () => generateMom().catch((err) => alert(err.message)));
  qs("#filterType").addEventListener("change", applyFilter);
  qs("#manualMappingForm").addEventListener("submit", (e) => {
    saveManualMapping(e).catch((err) => alert(err.message));
  });
  qs("#reloadRunBtn").addEventListener("click", () => reloadRun().catch((err) => alert(err.message)));
  manualMappingsBody.addEventListener("click", (e) => {
    const editBtn = e.target.closest("button[data-edit]");
    if (editBtn) {
      editMapping(Number(editBtn.dataset.edit)).catch((err) => alert(err.message));
      return;
    }
    const delBtn = e.target.closest("button[data-delete]");
    if (delBtn) {
      deleteMapping(Number(delBtn.dataset.delete)).catch((err) => alert(err.message));
    }
  });
}

(async function init() {
  hookEvents();
  await loadActionItems();
  await loadHistory();
})();
