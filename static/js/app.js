function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toast-message';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2400);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  return response.json();
}

async function allocateAllTasks() {
  const data = await requestJson('/allocate', { method: 'POST', body: JSON.stringify({}) });
  if (data.success) {
    showToast('AI allocation completed successfully.');
    window.location.reload();
  } else {
    showToast(data.message || 'Allocation did not complete.');
  }
}

async function runDemoScenario() {
  const data = await requestJson('/demo', { method: 'POST', body: JSON.stringify({}) });
  if (data.success) {
    showToast(data.summary || 'Demo scenario completed.');
    window.location.reload();
  } else {
    showToast(data.message || 'Demo scenario failed.');
  }
}

function bindReasonButtons() {
  document.querySelectorAll('.reason-button').forEach((button) => {
    button.addEventListener('click', () => {
      const reason = button.getAttribute('data-reason') || 'No reason available.';
      alert(reason);
    });
  });
}

function bindReallocateButtons() {
  document.querySelectorAll('.reallocate-btn').forEach((button) => {
    button.addEventListener('click', async () => {
      const taskId = button.getAttribute('data-task-id');
      const response = await requestJson('/reallocate', {
        method: 'POST',
        body: JSON.stringify({ task_id: Number(taskId) })
      });
      if (response.success) {
        showToast('Reallocation completed.');
        window.location.reload();
      } else {
        showToast(response.message || 'Reallocation failed.');
      }
    });
  });
}

function handleScenarioFields() {
  const scenarioType = document.getElementById('scenarioType');
  const fields = document.querySelectorAll('.scenario-field');
  if (!scenarioType) return;

  function toggle() {
    const current = scenarioType.value;
    fields.forEach((field) => {
      const scenarios = (field.getAttribute('data-scenario') || '').split(/\s+/).filter(Boolean);
      const visible = scenarios.includes(current);
      field.style.display = visible ? 'block' : 'none';
    });
  }

  scenarioType.addEventListener('change', toggle);
  toggle();
}

function buildScenarioPayload() {
  const form = document.getElementById('simulationForm');
  const scenarioType = document.getElementById('scenarioType')?.value || '';
  if (!form) return {};

  const payload = {};
  Array.from(form.querySelectorAll('[name]')).forEach((field) => {
    const group = field.closest('.scenario-field');
    if (group) {
      const scenarios = (group.getAttribute('data-scenario') || '').split(/\s+/).filter(Boolean);
      if (!scenarios.includes(scenarioType)) {
        return;
      }
    }

    const name = field.name;
    if (!name) return;
    let value = field.value;
    if (field.type === 'checkbox') value = field.checked;
    if (field.type === 'number' && value !== '') value = Number(value);
    payload[name] = value;
  });

  if (scenarioType === 'workload_increase') {
    const workloadValue = payload.workload_increase ?? payload.workload_increase_percent ?? payload.increase ?? payload.increase_percent ?? payload.change ?? payload.scenario_value;
    if (workloadValue !== undefined && workloadValue !== '') {
      payload.workload_increase = workloadValue;
    }
  }

  return payload;
}

function validateWorkloadIncrease(payload) {
  const employeeId = Number(payload.employee_id);
  const raw = payload.workload_increase ?? payload.workload_increase_percent ?? payload.increase ?? payload.increase_percent ?? payload.change ?? payload.scenario_value;

  if (!Number.isFinite(employeeId) || employeeId <= 0) {
    return 'Please select an employee before running the workload simulation.';
  }

  if (raw === undefined || raw === null || String(raw).trim() === '') {
    return 'Please enter a workload increase percentage.';
  }

  const value = Number(raw);
  if (!Number.isFinite(value)) {
    return 'Workload increase must be a valid number.';
  }
  if (value < 1 || value > 100) {
    return 'Workload increase must be between 1% and 100%.';
  }

  return { employee_id: employeeId, workload_increase: Math.round(value) };
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderScenarioPreview(data) {
  const preview = document.getElementById('simulationPreview');
  if (!preview) return;

  if (!data || !data.success) {
    preview.innerHTML = `<div class="alert alert-danger mb-0">${escapeHtml(data?.message || 'Scenario preview failed.')}</div>`;
    return;
  }

  const beforeState = data.before || {};
  const afterState = data.after || {};
  const workloadBefore = Number(beforeState.workload ?? NaN);
  const workloadAfter = Number(afterState.workload ?? NaN);
  const isWorkloadPreview = data.scenario === 'Employee workload increases' || data.event === 'Workload increase preview' || (!Number.isNaN(workloadBefore) && !Number.isNaN(workloadAfter) && (data.event === 'Workload increase preview' || document.getElementById('scenarioType')?.value === 'workload_increase'));

  if (isWorkloadPreview) {
    const employeeName = escapeHtml(data.employee || beforeState.employee || afterState.employee || 'Employee');
    const requestedChange = Number(data.requested_change ?? data.increase ?? data.workload_increase ?? (Number.isFinite(workloadAfter) && Number.isFinite(workloadBefore) ? Math.max(0, workloadAfter - workloadBefore) : 0));
    const effectiveChange = Number(data.effective_change ?? Math.max(0, workloadAfter - workloadBefore));
    const impact = data.impact || {};
    const affectedTasks = Number(impact.affected_tasks ?? 0);
    const slaRisk = escapeHtml(impact.sla_risk || 'Low');
    const impactMessage = escapeHtml(impact.message || 'No active tasks require reassignment.');
    const decisionText = escapeHtml(data.decision || 'No reallocation required.');
    const reasonText = escapeHtml(data.reason || data.explanation || 'The workload change was evaluated.');

    preview.innerHTML = `
      <div class="scenario-summary-box">
        <span class="eyebrow">Scenario</span>
        <h4>Workload increase preview</h4>
        <p class="summary-text">Employee: ${employeeName}</p>
      </div>

      <div class="before-after-layout">
        <div class="state-panel">
          <h5>Before</h5>
          <div class="preview-grid">
            <div class="mini-stat"><span>Employee</span><strong>${employeeName}</strong></div>
            <div class="mini-stat"><span>Workload</span><strong>${workloadBefore}%</strong></div>
          </div>
        </div>

        <div class="state-panel">
          <h5>Scenario Change</h5>
          <div class="preview-grid">
            <div class="mini-stat"><span>Change</span><strong>+${requestedChange}%</strong></div>
            <div class="mini-stat"><span>Type</span><strong>Workload increase</strong></div>
          </div>
        </div>
      </div>

      <div class="state-panel mt-3">
        <h5>After</h5>
        <div class="preview-grid">
          <div class="mini-stat"><span>Employee</span><strong>${employeeName}</strong></div>
          <div class="mini-stat"><span>Workload</span><strong>${workloadAfter}%</strong></div>
        </div>
      </div>

      <div class="state-panel mt-3">
        <h5>Impact</h5>
        <div class="preview-grid">
          <div class="mini-stat"><span>Affected Tasks</span><strong>${affectedTasks}</strong></div>
          <div class="mini-stat"><span>SLA Risk</span><strong>${slaRisk}</strong></div>
        </div>
        <p class="mt-3 mb-0">${impactMessage}</p>
      </div>

      <div class="state-panel mt-3">
        <h5>Decision</h5>
        <p class="mb-2">${decisionText}</p>
        <p class="mb-0 text-muted">${reasonText}</p>
      </div>
    `;

    const style = document.getElementById('scenarioPreviewStyles');
    if (!style) {
      const css = document.createElement('style');
      css.id = 'scenarioPreviewStyles';
      css.textContent = `
        .scenario-summary-box {
          background: #f8fafc;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          padding: 14px 16px;
          margin-bottom: 16px;
        }
        .eyebrow {
          display: inline-block;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: #475569;
          margin-bottom: 6px;
        }
        .summary-text {
          margin: 0;
          color: #334155;
        }
        .before-after-layout {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }
        .state-panel {
          background: #fff;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          padding: 14px;
        }
        .state-panel h5 {
          margin: 0 0 12px;
          font-size: 1rem;
        }
        .preview-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
          gap: 10px;
        }
        .mini-stat {
          background: #f8fafc;
          border: 1px solid #e2e8f0;
          border-radius: 10px;
          padding: 8px 10px;
        }
        .mini-stat span {
          display: block;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: #64748b;
        }
        .mini-stat strong {
          display: block;
          margin-top: 4px;
          color: #0f172a;
          word-break: break-word;
        }
        @media (max-width: 767px) {
          .before-after-layout {
            grid-template-columns: 1fr;
          }
        }
      `;
      document.head.appendChild(css);
    }
    return;
  }

  const eventLabel = escapeHtml(data.scenario || data.event || 'Scenario preview');

  const fallbackSummary = Array.isArray(data.after) && data.after.length
    ? `Review the proposed adjustments for ${data.after.length} affected task${data.after.length > 1 ? 's' : ''}.`
    : 'No active tasks require reallocation for this scenario.';
  const summary = escapeHtml(data.summary && !data.summary.includes('{"success"') ? data.summary : fallbackSummary);

  const beforeHtml = (before) => {
    if (!before) return '<p class="text-muted mb-0">No before-state details were provided.</p>';
    const entries = Object.entries(before).map(([key, value]) => {
      let displayValue = '';
      if (Array.isArray(value)) {
        displayValue = value.length ? value.map((item) => item?.name || item?.task_name || item).join(', ') : 'No tasks assigned';
      } else if (value === null || value === undefined) {
        displayValue = 'Not available';
      } else if (typeof value === 'object') {
        displayValue = JSON.stringify(value, null, 2);
      } else {
        displayValue = String(value);
      }
      return `
        <div class="mini-stat">
          <span>${escapeHtml(key.replace(/_/g, ' '))}</span>
          <strong>${escapeHtml(displayValue)}</strong>
        </div>
      `;
    });
    return `<div class="preview-grid">${entries.join('')}</div>`;
  };

  const afterHtml = (after) => {
    if (!after) return '<p class="text-muted mb-0">No after-state details were provided.</p>';

    if (Array.isArray(after)) {
      if (!after.length) {
        return '<div class="decision-card"><p>No active task reassignment is required for this scenario.</p></div>';
      }
      return after.map((item) => `
        <div class="decision-card">
          <div class="decision-header">
            <span class="badge-pill">${escapeHtml(item.status || 'Decision')}</span>
            <strong>${escapeHtml(item.task_name || item.name || 'Task')}</strong>
          </div>
          <div class="decision-meta">
            <div><span>From</span><strong>${escapeHtml(item.previous_employee || 'Unassigned')}</strong></div>
            <div><span>To</span><strong>${escapeHtml(item.proposed_employee || 'No feasible replacement')}</strong></div>
            ${item.suitability_score !== undefined && item.suitability_score !== null ? `<div><span>Fit</span><strong>${escapeHtml(item.suitability_score)}%</strong></div>` : ''}
          </div>
          <p>${escapeHtml(item.reason || item.decision || 'No decision detail available.')}</p>
        </div>
      `).join('');
    }

    const safeAfterName = after.employee || after.name || after.task_name || 'No assignment required';
    const safeAfterReason = after.reason || after.decision || 'No decision detail available.';
    const safeStatus = after.status || 'Decision';

    return `
      <div class="decision-card">
        <div class="decision-header">
          <span class="badge-pill">${escapeHtml(safeStatus)}</span>
          <strong>${escapeHtml(safeAfterName)}</strong>
        </div>
        <div class="decision-meta">
          ${after.suitability_score !== undefined && after.suitability_score !== null ? `<div><span>Fit</span><strong>${escapeHtml(after.suitability_score)}%</strong></div>` : ''}
          ${after.priority ? `<div><span>Priority</span><strong>${escapeHtml(after.priority)}</strong></div>` : ''}
        </div>
        <p>${escapeHtml(safeAfterReason)}</p>
      </div>
    `;
  };

  preview.innerHTML = `
    <div class="scenario-summary-box">
      <div class="scenario-summary-header">
        <div>
          <span class="eyebrow">Scenario</span>
          <h4>${eventLabel}</h4>
        </div>
      </div>
      <p class="summary-text">${summary}</p>
    </div>

    <div class="before-after-layout">
      <div class="state-panel">
        <h5>Before</h5>
        ${beforeHtml(beforeState)}
      </div>
      <div class="state-panel">
        <h5>After</h5>
        ${afterHtml(afterState)}
      </div>
    </div>
  `;

  const style = document.getElementById('scenarioPreviewStyles');
  if (!style) {
    const css = document.createElement('style');
    css.id = 'scenarioPreviewStyles';
    css.textContent = `
      .scenario-summary-box {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 16px;
      }
      .eyebrow {
        display: inline-block;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #475569;
        margin-bottom: 6px;
      }
      .summary-text {
        margin: 0;
        color: #334155;
      }
      .before-after-layout {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
      }
      .state-panel {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 14px;
      }
      .state-panel h5 {
        margin: 0 0 12px;
        font-size: 1rem;
      }
      .preview-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 10px;
      }
      .mini-stat {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 8px 10px;
      }
      .mini-stat span {
        display: block;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #64748b;
      }
      .mini-stat strong {
        display: block;
        margin-top: 4px;
        color: #0f172a;
        word-break: break-word;
      }
      .decision-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px;
        margin-bottom: 12px;
      }
      .decision-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 10px;
      }
      .badge-pill {
        display: inline-block;
        padding: 4px 8px;
        background: #dbeafe;
        color: #1d4ed8;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
      }
      .decision-meta {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
        gap: 8px;
        margin-bottom: 8px;
      }
      .decision-meta div {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 8px;
      }
      .decision-meta span {
        display: block;
        font-size: 11px;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .decision-meta strong {
        display: block;
        margin-top: 4px;
        word-break: break-word;
      }
      .decision-card p {
        margin: 0;
        color: #334155;
        line-height: 1.5;
      }
      @media (max-width: 767px) {
        .before-after-layout {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(css);
  }
}

async function runSimulation() {
  const form = document.getElementById('simulationForm');
  const preview = document.getElementById('simulationPreview');
  if (!form || !preview) return;

  const scenarioType = document.getElementById('scenarioType')?.value || '';
  const payload = buildScenarioPayload();

  if (scenarioType === 'workload_increase') {
    const validation = validateWorkloadIncrease(payload);
    if (typeof validation === 'string') {
      preview.innerHTML = `<div class="alert alert-warning mb-0">${escapeHtml(validation)}</div>`;
      showToast(validation);
      return;
    }
    payload.employee_id = validation.employee_id;
    payload.workload_increase = validation.workload_increase;
  }

  const data = await requestJson('/simulate', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

  const payloadField = document.getElementById('simulationPayload');
  if (payloadField) payloadField.value = JSON.stringify(payload);
  renderScenarioPreview(data);
}

async function applySimulation() {
  const payloadField = document.getElementById('simulationPayload');
  const form = document.getElementById('simulationForm');
  if (!form || !payloadField) return;

  const scenarioType = document.getElementById('scenarioType')?.value || '';
  const payload = buildScenarioPayload();

  if (scenarioType === 'workload_increase') {
    const validation = validateWorkloadIncrease(payload);
    if (typeof validation === 'string') {
      const preview = document.getElementById('simulationPreview');
      if (preview) preview.innerHTML = `<div class="alert alert-warning mb-0">${escapeHtml(validation)}</div>`;
      showToast(validation);
      return;
    }
    payload.employee_id = validation.employee_id;
    payload.workload_increase = validation.workload_increase;
  }

  payloadField.value = JSON.stringify(payload);
  const response = await requestJson('/apply-simulation', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

  if (response.success) {
    showToast(response.message || 'Scenario applied.');
    window.location.reload();
  } else {
    showToast(response.message || 'Could not apply scenario.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  bindReasonButtons();
  bindReallocateButtons();
  handleScenarioFields();

  const runBtn = document.getElementById('runSimulationBtn');
  if (runBtn) runBtn.addEventListener('click', runSimulation);

  const applyBtn = document.getElementById('applySimulationBtn');
  if (applyBtn) applyBtn.addEventListener('click', applySimulation);

  const style = document.createElement('style');
  style.textContent = `
    .toast-message {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #111827;
      color: #fff;
      padding: 12px 16px;
      border-radius: 10px;
      box-shadow: 0 12px 24px rgba(0,0,0,0.18);
      z-index: 2000;
    }
  `;
  document.head.appendChild(style);
});
