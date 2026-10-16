// Generalized draggable window function
function makeDraggable(elId, headerId) {
  const el = document.getElementById(elId);
  const header = document.getElementById(headerId);
  if (!el || !header) return;

  let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
  header.onmousedown = (e) => {
    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
    e.preventDefault();
    pos3 = e.clientX;
    pos4 = e.clientY;
    document.onmouseup = () => {
      document.onmouseup = null;
      document.onmousemove = null;
    };
    document.onmousemove = (ev) => {
      ev.preventDefault();
      pos1 = pos3 - ev.clientX;
      pos2 = pos4 - ev.clientY;
      pos3 = ev.clientX;
      pos4 = ev.clientY;
      el.style.top = (el.offsetTop - pos2) + "px";
      el.style.left = (el.offsetLeft - pos1) + "px";
      el.style.right = 'auto';
      el.style.bottom = 'auto';
    };
  };
}

let telemetryPollTimer = null;
let isConsoleOpen = false;

function toggleLiveConsole() {
  const win = document.getElementById('live-console-window');
  if (!win) return;

  isConsoleOpen = !isConsoleOpen;
  if (isConsoleOpen) {
    win.classList.remove('hidden');
    pollTelemetry();
    if (!telemetryPollTimer) {
      telemetryPollTimer = setInterval(pollTelemetry, 1000);
    }
  } else {
    win.classList.add('hidden');
    if (telemetryPollTimer) {
      clearInterval(telemetryPollTimer);
      telemetryPollTimer = null;
    }
  }
}

async function clearTelemetryLogs() {
  try {
    await fetch('/api/telemetry/clear', { method: 'POST' });
    const stream = document.getElementById('console-log-stream');
    if (stream) stream.innerHTML = '<div class="text-gray-500 italic text-[11px] py-2 text-center">Logs cleared.</div>';
  } catch (err) {}
}

async function pollTelemetry() {
  if (!isConsoleOpen) return;
  try {
    const res = await fetch('/api/telemetry');
    if (!res.ok) return;
    const data = await res.json();

    // 1. Render Log Stream
    const stream = document.getElementById('console-log-stream');
    if (stream && Array.isArray(data.logs)) {
      if (data.logs.length === 0) {
        stream.innerHTML = '<div class="text-gray-500 italic text-[11px] py-2 text-center">No recent calls recorded.</div>';
      } else {
        const isScrolledToBottom = stream.scrollHeight - stream.clientHeight <= stream.scrollTop + 30;
        stream.innerHTML = data.logs.map(log => {
          const methodColor = log.method === 'POST' ? 'text-blue-400 font-bold' : log.method === 'UDP' ? 'text-purple-400 font-bold' : 'text-emerald-400 font-semibold';
          const statusColor = (log.status === '200' || log.status === '204') ? 'text-emerald-400' : 'text-rose-400';
          return `<div class="leading-tight py-0.5 flex items-start gap-1.5 hover:bg-gray-900/60 px-1 rounded">
            <span class="text-gray-500 shrink-0 select-none">${log.timestamp}</span>
            <span class="${methodColor} shrink-0 w-8 text-center text-[10px] bg-gray-900 px-1 rounded border border-gray-800">${log.method}</span>
            <span class="text-gray-200 font-semibold shrink-0">${log.endpoint}</span>
            <span class="${statusColor} shrink-0">(${log.status})</span>
            <span class="text-gray-500 shrink-0">${log.duration_ms}ms</span>
            <span class="text-gray-400 truncate flex-1">${log.details || ''}</span>
          </div>`;
        }).join('');
        if (isScrolledToBottom) {
          stream.scrollTop = stream.scrollHeight;
        }
      }
    }

    // 2. Render Call Frequency Table (Calls/Minute)
    const ratesBody = document.getElementById('console-rates-body');
    if (ratesBody && Array.isArray(data.rates)) {
      if (data.rates.length === 0) {
        ratesBody.innerHTML = '<tr><td colspan="2" class="py-3 px-3 text-center text-gray-500 italic">No calls in the last 60 seconds.</td></tr>';
      } else {
        ratesBody.innerHTML = data.rates.map(r => {
          const badgeBg = r.cpm > 25 ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' : 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30';
          return `<tr class="hover:bg-gray-800/40 transition">
            <td class="py-1 px-3 font-semibold text-gray-200">${r.endpoint}</td>
            <td class="py-1 px-3 text-right">
              <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border ${badgeBg}">${r.cpm} cpm</span>
            </td>
          </tr>`;
        }).join('');
      }
    }
  } catch (err) {}
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  const borderBg = type === 'success' 
    ? 'bg-emerald-950/90 border-emerald-500/40 text-emerald-200' 
    : type === 'error' 
    ? 'bg-red-950/90 border-red-500/40 text-red-200' 
    : 'bg-indigo-950/90 border-indigo-500/40 text-indigo-200';

  toast.className = 'pointer-events-auto flex items-center gap-2.5 px-4 py-3 rounded-lg border shadow-xl text-sm font-medium transition-all duration-300 transform translate-y-2 opacity-0 ' + borderBg;

  const icon = type === 'success'
    ? '<svg class="w-4 h-4 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>'
    : type === 'error'
    ? '<svg class="w-4 h-4 text-red-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>'
    : '<svg class="w-4 h-4 text-indigo-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';

  toast.innerHTML = icon + '<span>' + message + '</span>';
  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.classList.remove('translate-y-2', 'opacity-0');
  });

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

const STOP_ICON = `<svg class="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>`;
const KILL_ICON = `<svg class="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24"><path d="M12 2a9 9 0 0 0-9 9c0 3.3 1.8 6.2 4.5 7.7V21a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1v-2.3c2.7-1.5 4.5-4.4 4.5-7.7a9 9 0 0 0-9-9zm-3 10a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm6 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/></svg>`;

const POWER_BUTTON_STYLES = {
  start: {
    enabled: "bg-emerald-600/90 hover:bg-emerald-500 text-white border border-emerald-500/40 cursor-pointer shadow-sm shadow-emerald-950",
    disabled: "bg-gray-800/40 border border-gray-700/50 text-gray-500 cursor-not-allowed opacity-50"
  },
  restart: {
    enabled: "bg-amber-600/90 hover:bg-amber-500 text-white border border-amber-500/40 cursor-pointer shadow-sm shadow-amber-950",
    disabled: "bg-gray-800/40 border border-gray-700/50 text-gray-500 cursor-not-allowed opacity-50"
  },
  stop: {
    enabled: "bg-rose-600/90 hover:bg-rose-500 text-white border border-rose-500/40 cursor-pointer shadow-sm shadow-rose-950",
    disabled: "bg-gray-800/40 border border-gray-700/50 text-gray-500 cursor-not-allowed opacity-50"
  },
  kill: {
    enabled: "bg-red-700/90 hover:bg-red-600 text-white border border-red-500/50 cursor-pointer shadow-sm shadow-red-950",
    disabled: "bg-gray-800/40 border border-gray-700/50 text-gray-500 cursor-not-allowed opacity-50"
  }
};

const stoppingStateTrackers = {};

function setButtonState(btn, type, isEnabled) {
  if (!btn) return;
  btn.disabled = !isEnabled;
  const base = "flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition ";
  btn.className = base + (isEnabled ? POWER_BUTTON_STYLES[type].enabled : POWER_BUTTON_STYLES[type].disabled);
}

function renderStopButton(btn, idx, isEnabled, serverId = null) {
  if (!btn) return;
  btn.disabled = !isEnabled;
  const ident = serverId || idx;
  btn.onclick = () => triggerPowerAction(ident, 'stop', idx);
  btn.innerHTML = `${STOP_ICON} Stop`;
  const base = "flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition ";
  btn.className = base + (isEnabled ? POWER_BUTTON_STYLES.stop.enabled : POWER_BUTTON_STYLES.stop.disabled);
}

function renderKillButton(btn, idx, isEnabled, serverId = null) {
  if (!btn) return;
  btn.disabled = !isEnabled;
  const ident = serverId || idx;
  btn.onclick = () => triggerPowerAction(ident, 'kill', idx);
  btn.innerHTML = `${KILL_ICON} Kill`;
  const base = "flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition ";
  btn.className = base + (isEnabled ? POWER_BUTTON_STYLES.kill.enabled : POWER_BUTTON_STYLES.kill.disabled);
}

function updatePowerButtons(idx, powerState, serverId = null) {
  const startBtn = document.getElementById('btn_start_' + idx);
  const restartBtn = document.getElementById('btn_restart_' + idx);
  const stopBtn = document.getElementById('btn_stop_' + idx);
  const st = (powerState || '').toLowerCase();

  if (st === 'stopping') {
    setButtonState(startBtn, 'start', false);
    setButtonState(restartBtn, 'restart', false);

    if (!stoppingStateTrackers[idx]) {
      stoppingStateTrackers[idx] = { startTime: Date.now(), timerId: null };
    }

    const elapsed = Date.now() - stoppingStateTrackers[idx].startTime;
    if (elapsed < 1000) {
      renderStopButton(stopBtn, idx, false, serverId);

      if (!stoppingStateTrackers[idx].timerId) {
        stoppingStateTrackers[idx].timerId = setTimeout(() => {
          const badge = document.getElementById('srv_power_badge_' + idx);
          if (badge && badge.innerText.toLowerCase().includes('stopping')) {
            renderKillButton(stopBtn, idx, true, serverId);
          }
        }, 1000 - elapsed);
      }
    } else {
      renderKillButton(stopBtn, idx, true, serverId);
    }
  } else {
    if (stoppingStateTrackers[idx]) {
      if (stoppingStateTrackers[idx].timerId) {
        clearTimeout(stoppingStateTrackers[idx].timerId);
      }
      delete stoppingStateTrackers[idx];
    }

    if (st === 'running') {
      setButtonState(startBtn, 'start', false);
      setButtonState(restartBtn, 'restart', true);
      renderStopButton(stopBtn, idx, true, serverId);
    } else if (st === 'offline') {
      setButtonState(startBtn, 'start', true);
      setButtonState(restartBtn, 'restart', false);
      renderStopButton(stopBtn, idx, false, serverId);
    } else if (st === 'starting') {
      setButtonState(startBtn, 'start', false);
      setButtonState(restartBtn, 'restart', false);
      renderStopButton(stopBtn, idx, true, serverId);
    } else {
      setButtonState(startBtn, 'start', true);
      setButtonState(restartBtn, 'restart', true);
      renderStopButton(stopBtn, idx, true, serverId);
    }
  }
}

async function triggerPowerAction(identifier, action, uiIndex = null) {
  const targetIdx = (uiIndex !== null && uiIndex !== undefined) ? uiIndex : identifier;
  const btn = document.getElementById(`btn_${action === 'kill' ? 'stop' : action}_${targetIdx}`);
  if (btn && btn.disabled) return;

  if (btn) btn.disabled = true;

  if (action === 'stop') {
    if (stoppingStateTrackers[targetIdx]?.timerId) {
      clearTimeout(stoppingStateTrackers[targetIdx].timerId);
    }
    stoppingStateTrackers[targetIdx] = { startTime: Date.now(), timerId: null };
    renderStopButton(btn, targetIdx, false, identifier);
  }

  try {
    const res = await fetch(`/api/servers/${encodeURIComponent(identifier)}/power/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      throw new Error(data.message || 'Signal rejected by panel');
    }
    showToast(`Server ${action.toUpperCase()} signal dispatched successfully`, 'success');
    pollLiveStatus();
  } catch (err) {
    console.error(err);
    showToast(`Failed to ${action} server: ${err.message}`, 'error');
    pollLiveStatus();
  }
}

async function toggleTestModeImmediate(el) {
  try {
    const res = await fetch('/toggle-test-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: el.checked })
    });
    if (!res.ok) throw new Error('Failed to update Test Mode');
    
    const simWindow = document.getElementById('test-simulator-window');
    if (simWindow) {
      if (el.checked) {
        simWindow.classList.remove('hidden');
      } else {
        simWindow.classList.add('hidden');
      }
    }
    showToast(el.checked ? 'Test Mode enabled (Simulation window active)' : 'Test Mode disabled', 'success');
  } catch (err) {
    console.error(err);
    el.checked = !el.checked;
    showToast('Failed to update Test Mode.', 'error');
  }
}

const serverBaselines = {};

function initServerBaselines() {
  document.querySelectorAll('[id^="srv_title_"]').forEach(el => {
    const idx = el.id.replace('srv_title_', '');
    const nameInput = document.getElementById('srv_name_input_' + idx);
    const idInput = document.getElementById('srv_id_input_' + idx);
    const appidInput = document.getElementById('srv_appid_input_' + idx);
    const manifestInput = document.getElementById('srv_manifest_input_' + idx);
    const portOffsetInput = document.getElementById('srv_port_offset_input_' + idx);

    serverBaselines[idx] = {
      name: nameInput ? nameInput.value : '',
      server_id: idInput ? idInput.value : '',
      app_id: appidInput ? appidInput.value : '',
      manifest_path: manifestInput ? manifestInput.value : '',
      query_port_offset: portOffsetInput ? portOffsetInput.value : '0'
    };
  });
}

function isServerDirty(idx) {
  const base = serverBaselines[idx];
  if (!base) return false;
  const nameInput = document.getElementById('srv_name_input_' + idx);
  const idInput = document.getElementById('srv_id_input_' + idx);
  const appidInput = document.getElementById('srv_appid_input_' + idx);
  const manifestInput = document.getElementById('srv_manifest_input_' + idx);
  const portOffsetInput = document.getElementById('srv_port_offset_input_' + idx);

  return (
    (nameInput && nameInput.value !== base.name) ||
    (idInput && idInput.value !== base.server_id) ||
    (appidInput && appidInput.value !== base.app_id) ||
    (manifestInput && manifestInput.value !== base.manifest_path) ||
    (portOffsetInput && portOffsetInput.value !== base.query_port_offset)
  );
}

function checkServerDirty(idx) {
  const saveBtn = document.getElementById('srv_save_btn_' + idx);
  if (!saveBtn) return;
  if (isServerDirty(idx)) {
    saveBtn.classList.remove('hidden');
    saveBtn.classList.add('inline-flex');
  } else {
    saveBtn.classList.add('hidden');
    saveBtn.classList.remove('inline-flex');
  }
}

function onServerTextInput(idx) {
  checkServerDirty(idx);
}

let serverIdDebounceTimers = {};

function onServerIdInput(identifier, idx) {
  checkServerDirty(idx);
  if (serverIdDebounceTimers[idx]) {
    clearTimeout(serverIdDebounceTimers[idx]);
  }
  serverIdDebounceTimers[idx] = setTimeout(() => {
    autoSyncServerDetails(identifier, idx);
  }, 700);
}

function onServerIdChange(identifier, idx) {
  checkServerDirty(idx);
  autoSyncServerDetails(identifier, idx);
}

async function autoSyncServerDetails(identifier, idx) {
  const idInput = document.getElementById('srv_id_input_' + idx);
  const srvId = idInput?.value.trim();
  if (!srvId || srvId.length < 2) return;
  const nameInput = document.getElementById('srv_name_input_' + idx);
  const appidInput = document.getElementById('srv_appid_input_' + idx);
  const manifestInput = document.getElementById('srv_manifest_input_' + idx);

  try {
    const res = await fetch(`/api/servers/detect-details?server_id=${encodeURIComponent(srvId)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok' && data.details) {
      const d = data.details;
      let changed = false;
      if (d.name && nameInput && (nameInput.value.trim() === 'New Server' || nameInput.value.trim() === '')) {
        nameInput.value = d.name;
        const titleEl = document.getElementById('srv_title_' + idx);
        if (titleEl) titleEl.innerText = `Server #${parseInt(idx) + 1}: ${d.name}`;
        changed = true;
      }
      const isBadAppId = !appidInput.value.trim() || appidInput.value.trim() === '1007' || appidInput.value.trim() === '228980';
      if (d.app_id && appidInput && isBadAppId && d.app_id !== '1007' && d.app_id !== '228980') {
        appidInput.value = d.app_id;
        changed = true;
      }
      const isBadManifest = !manifestInput.value.trim() || /appmanifest_1007\.acf/i.test(manifestInput.value) || /appmanifest_228980\.acf/i.test(manifestInput.value);
      if (d.manifest_path && manifestInput && isBadManifest) {
        manifestInput.value = d.manifest_path;
        changed = true;
      } else if (d.app_id && manifestInput && (isBadManifest || /appmanifest_896660\.acf/i.test(manifestInput.value))) {
        updateManifestAppId(idx, d.app_id);
        changed = true;
      }

      if (changed) {
        checkServerDirty(idx);
        if (d.app_id) {
          showToast(`Detected ${d.name || 'Server'} (App ID: ${d.app_id}) from Pterodactyl`, 'info');
        } else if (d.name) {
          showToast(`Server name detected from Pterodactyl: ${d.name}`, 'info');
        }
      }
    }
  } catch (err) {
    // Quiet fail on debounce lookup
  }
}

function updateManifestAppId(idx, newAppId) {
  const manifestInput = document.getElementById('srv_manifest_input_' + idx);
  if (!manifestInput || !newAppId || newAppId === '1007' || newAppId === '228980') return;
  const currentPath = manifestInput.value.trim();
  if (!currentPath || /appmanifest_1007\.acf/i.test(currentPath) || /appmanifest_228980\.acf/i.test(currentPath)) {
    manifestInput.value = `steamapps/appmanifest_${newAppId}.acf`;
  } else if (/appmanifest_.*\.acf/i.test(currentPath)) {
    manifestInput.value = currentPath.replace(/appmanifest_.*\.acf/i, `appmanifest_${newAppId}.acf`);
  } else if (currentPath.endsWith('.acf')) {
    manifestInput.value = currentPath.replace(/[^\/\\\\]+\.acf$/i, `appmanifest_${newAppId}.acf`);
  } else {
    manifestInput.value = `${currentPath.replace(/\/+$/, '')}/appmanifest_${newAppId}.acf`;
  }
  checkServerDirty(idx);
}

function onSteamAppIdInput(idx) {
  checkServerDirty(idx);
  const appidInput = document.getElementById('srv_appid_input_' + idx);
  const val = appidInput?.value.trim();
  if (val && /^\d+$/.test(val) && val !== '1007' && val !== '228980') {
    updateManifestAppId(idx, val);
  }
}

let steamSearchDebounceTimers = {};

function openSteamAppSearch(idx) {
  const dropdown = document.getElementById('steam_search_dropdown_' + idx);
  if (!dropdown) return;
  dropdown.classList.remove('hidden');
  const queryInput = document.getElementById('steam_search_query_' + idx);
  if (queryInput && !queryInput.value.trim()) {
    fetchSteamSearchResults(idx, '');
  }
}

function toggleSteamAppSearch(idx) {
  const dropdown = document.getElementById('steam_search_dropdown_' + idx);
  if (!dropdown) return;
  if (dropdown.classList.contains('hidden')) {
    openSteamAppSearch(idx);
    const queryInput = document.getElementById('steam_search_query_' + idx);
    if (queryInput) queryInput.focus();
  } else {
    dropdown.classList.add('hidden');
  }
}

function closeSteamAppSearch(idx) {
  const dropdown = document.getElementById('steam_search_dropdown_' + idx);
  if (dropdown) dropdown.classList.add('hidden');
}

function onSteamSearchQueryInput(idx) {
  if (steamSearchDebounceTimers[idx]) {
    clearTimeout(steamSearchDebounceTimers[idx]);
  }
  steamSearchDebounceTimers[idx] = setTimeout(() => {
    const queryInput = document.getElementById('steam_search_query_' + idx);
    fetchSteamSearchResults(idx, queryInput?.value.trim() || '');
  }, 300);
}

async function fetchSteamSearchResults(idx, query) {
  const resultsContainer = document.getElementById('steam_search_results_' + idx);
  if (!resultsContainer) return;
  resultsContainer.innerHTML = '<div class="text-gray-400 italic text-[11px] p-2 text-center">Searching Steam catalog...</div>';

  try {
    const res = await fetch(`/api/steam/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok' && Array.isArray(data.results)) {
      if (data.results.length === 0) {
        resultsContainer.innerHTML = '<div class="text-gray-500 italic text-[11px] p-2 text-center">No matching Steam games found.</div>';
        return;
      }
      resultsContainer.innerHTML = data.results.map(item => {
        const isDedi = item.type === 'dedicated_server';
        const badgeBg = isDedi ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40' : 'bg-gray-800 text-gray-400 border-gray-700';
        const labelBadge = isDedi ? 'Dedicated Server' : 'Game';
        const safeName = item.name.replace(/'/g, "\\'");
        return `<div onclick="selectSteamGame(${idx}, '${item.app_id}', '${safeName}')" 
                     class="flex items-center justify-between p-2 rounded hover:bg-gray-800/80 cursor-pointer transition border border-transparent hover:border-gray-700 select-none">
          <div class="flex items-center gap-2 min-w-0 pr-2">
            <span class="text-gray-200 font-medium truncate">${item.name}</span>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold border ${badgeBg} whitespace-nowrap">${labelBadge}</span>
          </div>
          <span class="font-mono text-[11px] text-amber-300 bg-gray-950 px-1.5 py-0.5 rounded border border-gray-800 shrink-0">${item.app_id}</span>
        </div>`;
      }).join('');
    } else {
      resultsContainer.innerHTML = '<div class="text-red-400 text-[11px] p-2 text-center">Error loading results.</div>';
    }
  } catch (err) {
    resultsContainer.innerHTML = '<div class="text-gray-500 italic text-[11px] p-2 text-center">Search unavailable.</div>';
  }
}

function selectSteamGame(idx, appId, gameName) {
  const appidInput = document.getElementById('srv_appid_input_' + idx);
  if (appidInput) {
    appidInput.value = appId;
  }
  updateManifestAppId(idx, appId);
  closeSteamAppSearch(idx);
  checkServerDirty(idx);
  showToast(`Selected ${gameName} (${appId}). Manifest path updated.`, 'success');
}

async function refreshServerName(identifier, idx) {
  const idInput = document.getElementById('srv_id_input_' + idx);
  const srvId = idInput?.value.trim() || identifier;
  if (!srvId) {
    showToast('Please enter a Server ID (Hash) first.', 'error');
    return;
  }

  const icon = document.getElementById('refresh_icon_svg_' + idx);
  if (icon) icon.classList.add('animate-spin');

  try {
    const res = await fetch(`/api/servers/${encodeURIComponent(identifier)}/sync-name`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server_id: srvId })
    });
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      throw new Error(data.message || 'Failed to sync server name');
    }

    const nameInput = document.getElementById('srv_name_input_' + idx);
    if (nameInput) nameInput.value = data.name;
    const titleEl = document.getElementById('srv_title_' + idx);
    if (titleEl) titleEl.innerText = `Server #${parseInt(idx) + 1}: ${data.name}`;

    if (!serverBaselines[idx]) serverBaselines[idx] = {};
    serverBaselines[idx].name = data.name;
    serverBaselines[idx].server_id = srvId;
    checkServerDirty(idx);
    showToast(`Server name refreshed and saved: ${data.name}`, 'success');
  } catch (err) {
    console.error(err);
    showToast(`Failed to sync name: ${err.message}`, 'error');
  } finally {
    if (icon) icon.classList.remove('animate-spin');
  }
}

async function toggleServerSlider(identifier, idx, field, el) {
  const isChecked = el.checked;
  const labelMap = {
    'auto_restart': 'Auto-Restart',
    'discord_alerts': 'Discord Alerts',
    'warn_ingame_countdown': 'In-Game Countdown Warnings',
    'warn_discord_countdown': 'Discord Countdown Warnings'
  };
  const label = labelMap[field] || field;

  try {
    const res = await fetch(`/api/servers/${encodeURIComponent(identifier)}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field: field, value: isChecked })
    });
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      throw new Error(data.message || 'Failed to update setting');
    }
    showToast(`${label} ${isChecked ? 'enabled' : 'disabled'} for Server #${parseInt(idx) + 1}`, 'success');
  } catch (err) {
    console.error(err);
    el.checked = !isChecked; // Revert checkbox
    showToast(`Failed to update ${label}: ${err.message}`, 'error');
  }
}

async function saveSingleServer(identifier, idx) {
  const saveBtn = document.getElementById('srv_save_btn_' + idx);
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<svg class="animate-spin w-3.5 h-3.5 inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Saving...';
  }

  const nameVal = document.getElementById('srv_name_input_' + idx)?.value || '';
  const idVal = document.getElementById('srv_id_input_' + idx)?.value || '';
  const appidVal = document.getElementById('srv_appid_input_' + idx)?.value || '';
  const manifestVal = document.getElementById('srv_manifest_input_' + idx)?.value || '';
  const rawOffset = document.getElementById('srv_port_offset_input_' + idx)?.value;
  const parsedOffset = parseInt(rawOffset, 10);
  const portOffsetVal = isNaN(parsedOffset) ? 0 : parsedOffset;

  try {
    const res = await fetch(`/api/servers/${encodeURIComponent(identifier)}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: nameVal,
        server_id: idVal,
        app_id: appidVal,
        manifest_path: manifestVal,
        query_port_offset: portOffsetVal
      })
    });
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      throw new Error(data.message || 'Save failed');
    }

    const savedSrv = data.server;
    serverBaselines[idx] = {
      name: savedSrv.name,
      server_id: savedSrv.server_id,
      app_id: savedSrv.app_id,
      manifest_path: savedSrv.manifest_path,
      query_port_offset: String(savedSrv.query_port_offset ?? 0)
    };

    const nameInput = document.getElementById('srv_name_input_' + idx);
    if (nameInput) nameInput.value = savedSrv.name;
    const portOffsetInput = document.getElementById('srv_port_offset_input_' + idx);
    if (portOffsetInput) portOffsetInput.value = savedSrv.query_port_offset ?? 0;
    const titleEl = document.getElementById('srv_title_' + idx);
    if (titleEl) titleEl.innerText = `Server #${parseInt(idx) + 1}: ${savedSrv.name}`;

    checkServerDirty(idx);
    showToast(`Server #${parseInt(idx) + 1} (${savedSrv.name}) saved successfully!`, 'success');
  } catch (err) {
    console.error(err);
    showToast(`Failed to save server: ${err.message}`, 'error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg> Save Server';
    }
  }
}

function toggleEditName(idx) {
  const input = document.getElementById('srv_name_input_' + idx);
  const saveBtn = document.getElementById('save_name_btn_' + idx);
  const editBtn = document.getElementById('edit_btn_' + idx);

  if (input.readOnly) {
    input.readOnly = false;
    input.classList.remove('bg-gray-950/60', 'text-gray-400', 'cursor-not-allowed');
    input.classList.add('bg-gray-950', 'text-white', 'border-indigo-500');
    input.focus();
    saveBtn.classList.remove('hidden');
    editBtn.innerText = 'Cancel';
    editBtn.classList.remove('text-indigo-400', 'hover:text-indigo-300');
    editBtn.classList.add('text-gray-400', 'hover:text-gray-300');
  } else {
    input.readOnly = true;
    input.classList.add('bg-gray-950/60', 'text-gray-400', 'cursor-not-allowed');
    input.classList.remove('bg-gray-950', 'text-white', 'border-indigo-500');
    saveBtn.classList.add('hidden');
    editBtn.innerText = 'Edit';
    editBtn.classList.remove('text-gray-400', 'hover:text-gray-300');
    editBtn.classList.add('text-indigo-400', 'hover:text-indigo-300');
    if (serverBaselines[idx]) {
      input.value = serverBaselines[idx].name;
      checkServerDirty(idx);
    }
  }
}

function updateCountdowns() {
  const now = Date.now() / 1000;
  document.querySelectorAll('.countdown-timer').forEach(el => {
    const target = parseFloat(el.getAttribute('data-target'));
    const wrap = el.closest('[id^="srv_countdown_wrap_"]');
    if (!target || target <= now) {
      if (wrap) wrap.classList.add('hidden');
      el.innerText = "";
      return;
    }
    if (wrap) wrap.classList.remove('hidden');
    const remaining = Math.floor(target - now);
    const mins = Math.floor(remaining / 60);
    const secs = remaining % 60;
    el.innerText = mins + "m " + secs + "s";
  });
}
setInterval(updateCountdowns, 1000);

async function triggerCheckNow(btn) {
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('opacity-75', 'cursor-not-allowed');
  const originalHtml = btn.innerHTML;
  btn.innerHTML = '<svg class="animate-spin w-4 h-4 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Checking all servers...';

  try {
    const res = await fetch('/check-now', {
      method: 'POST',
      headers: { 'Accept': 'application/json' }
    });
    if (!res.ok) throw new Error('Update check failed');
    showToast('Unified update check finished across all servers.', 'info');
    pollLiveStatus();
  } catch (err) {
    console.error(err);
    showToast('Failed to complete update check.', 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('opacity-75', 'cursor-not-allowed');
    btn.innerHTML = originalHtml;
  }
}

async function triggerSimulateBuild() {
  const select = document.getElementById('sim-server-select');
  const input = document.getElementById('sim-build-input');
  const btn = document.getElementById('btn-sim-trigger');
  if (!select || !input || !btn) return;

  const serverIdent = select.value;
  const buildId = input.value.trim();
  if (!buildId) {
    showToast('Please specify a build ID to simulate.', 'error');
    return;
  }

  btn.disabled = true;
  const originalText = btn.innerText;
  btn.innerText = 'Simulating...';

  try {
    const res = await fetch('/api/test/simulate-build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        server_id: serverIdent,
        server_idx: parseInt(serverIdent) || 0,
        build_id: buildId
      })
    });
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      throw new Error(data.message || 'Simulation rejected');
    }
    showToast(`Simulated build ${buildId} applied. Update check dispatched!`, 'success');
    pollLiveStatus();
  } catch (err) {
    console.error(err);
    showToast(`Simulation failed: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerText = originalText;
  }
}

async function clearTestPreview() {
  try {
    await fetch('/api/test/clear-preview', { method: 'POST' });
    renderTestPreview(null);
  } catch (err) {}
}

function renderTestPreview(preview) {
  const container = document.getElementById('sim-preview-container');
  const emptyState = document.getElementById('sim-preview-empty');
  if (!container || !emptyState) return;

  if (!preview) {
    container.classList.add('hidden');
    emptyState.classList.remove('hidden');
    return;
  }

  emptyState.classList.add('hidden');
  container.classList.remove('hidden');

  document.getElementById('sim-preview-time').innerText = preview.timestamp || '';
  document.getElementById('sim-preview-msg').innerHTML = preview.formatted_message || '';

  const embedWrap = document.getElementById('sim-preview-embed');
  if (preview.embed) {
    embedWrap.classList.remove('hidden');
    const titleEl = document.getElementById('sim-preview-title');
    if (preview.embed.url) {
      titleEl.innerHTML = `<a href="${preview.embed.url}" target="_blank" rel="noopener noreferrer" class="font-bold text-blue-400 hover:underline text-sm">${preview.embed.title || 'Steam Announcement'}</a>`;
    } else {
      titleEl.innerText = preview.embed.title || 'Steam Announcement';
    }
    document.getElementById('sim-preview-desc').innerHTML = preview.formatted_description || '';
    
    const imgEl = document.getElementById('sim-preview-img');
    if (preview.embed.image && preview.embed.image.url) {
      imgEl.src = preview.embed.image.url;
      imgEl.classList.remove('hidden');
    } else {
      imgEl.classList.add('hidden');
    }

    const footerEl = document.getElementById('sim-preview-footer');
    if (preview.embed.footer && preview.embed.footer.text) {
      footerEl.innerText = preview.embed.footer.text;
      footerEl.classList.remove('hidden');
    } else {
      footerEl.classList.add('hidden');
    }
  } else {
    embedWrap.classList.add('hidden');
  }
}

async function pollLiveStatus() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();

    const globalCheckEl = document.getElementById('global-last-check');
    if (globalCheckEl && data.last_check) {
      globalCheckEl.innerText = data.last_check;
    }

    const versionEl = document.getElementById('app-version');
    if (versionEl && data.app_version) {
      versionEl.innerText = 'v' + data.app_version.replace(/^v/, '');
    }

    const commitEl = document.getElementById('app-commit');
    if (commitEl && data.commit_code) {
      commitEl.innerText = 'commit ' + data.commit_code;
    }

    const redundantStatuses = [
      "up to date",
      "update available",
      "update available — countdown started",
      "update available (countdown active)",
      "countdown in progress...",
      "idle"
    ];

    if (Array.isArray(data.servers)) {
      data.servers.forEach(srv => {
        const idx = srv.idx;
        updatePowerButtons(idx, srv.power_state, srv.server_id);

        const badgeEl = document.getElementById('srv_power_badge_' + idx);
        if (badgeEl && srv.power_state) {
          const st = srv.power_state.toLowerCase();
          if (st === 'running') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-500/40';
            badgeEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>Online';
          } else if (st === 'offline') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-950/80 text-red-300 border border-red-500/40';
            badgeEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-red-400"></span>Offline';
          } else if (st === 'starting') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-500/40';
            badgeEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span>Starting...';
          } else if (st === 'stopping') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-orange-950/80 text-orange-300 border border-orange-500/40';
            badgeEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse"></span>Stopping...';
          } else {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-800 text-gray-400 border border-gray-700';
            badgeEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-gray-500"></span>Unknown';
          }
        }

        const statusEl = document.getElementById('srv_status_' + idx);
        if (statusEl) {
          const rawStatus = (srv.last_status || '').trim();
          if (!rawStatus || redundantStatuses.includes(rawStatus.toLowerCase())) {
            statusEl.innerText = '';
            statusEl.className = 'hidden';
          } else if (rawStatus.toLowerCase().startsWith('error') || rawStatus.toLowerCase().includes('failed')) {
            statusEl.className = 'text-xs font-semibold text-red-400 bg-red-950/50 px-2 py-0.5 rounded border border-red-800/60';
            statusEl.innerText = rawStatus;
          } else {
            statusEl.className = 'text-xs font-medium text-indigo-300 bg-indigo-950/40 px-2 py-0.5 rounded border border-indigo-800/50';
            statusEl.innerText = rawStatus;
          }
        }

        const cdWrap = document.getElementById('srv_countdown_wrap_' + idx);
        const cdEl = document.getElementById('srv_countdown_' + idx);
        const now = Date.now() / 1000;
        if (cdEl && cdWrap) {
          cdEl.setAttribute('data-target', srv.target_timestamp || '0');
          if (srv.target_timestamp && srv.target_timestamp > now) {
            cdWrap.classList.remove('hidden');
            cdWrap.classList.add('inline-flex');
          } else {
            cdWrap.classList.add('hidden');
            cdWrap.classList.remove('inline-flex');
          }
        }

        const buildsEl = document.getElementById('srv_builds_' + idx);
        if (buildsEl) {
          const cur = srv.current_build || 'Unknown';
          const lat = srv.latest_build || 'Unknown';
          const isUpdating = srv.is_updating;

          const greenTick = '<svg class="w-4 h-4 text-emerald-400 inline-block ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>';
          const swirlSpinner = '<svg class="animate-spin w-4 h-4 text-indigo-400 inline-block ml-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';

          if (cur === lat && cur !== 'Unknown' && cur !== '?') {
            buildsEl.innerHTML = '<span class="text-gray-400 mr-1.5">Build:</span><span class="font-mono text-gray-200">' + lat + '</span>' + greenTick;
          } else if (cur !== 'Unknown' && lat !== 'Unknown') {
            const swirl = isUpdating ? swirlSpinner : '';
            buildsEl.innerHTML = '<span class="text-gray-400 mr-1.5">Builds:</span><span class="font-mono text-gray-200">' + cur + ' &rarr; ' + lat + '</span>' + swirl;
          } else {
            buildsEl.innerHTML = '<span class="text-gray-400 mr-1.5">Builds:</span><span class="font-mono text-gray-200">' + cur + ' &rarr; ' + lat + '</span>';
          }
        }

        const titleEl = document.getElementById('srv_title_' + idx);
        const inputEl = document.getElementById('srv_name_input_' + idx);
        if (titleEl && srv.name && !isServerDirty(idx)) {
          titleEl.innerText = 'Server #' + (idx + 1) + ': ' + srv.name;
          if (inputEl && inputEl.readOnly) {
            inputEl.value = srv.name;
          }
        }

        // 1. Address & Mouseover Internal IP Tooltip
        const netWrap = document.getElementById('srv_net_wrap_' + idx);
        const addrEl = document.getElementById('srv_address_' + idx);
        const internalEl = document.getElementById('srv_internal_ip_' + idx);
        if (netWrap && addrEl && internalEl) {
          if (srv.external_ip && srv.port) {
            addrEl.innerText = `${srv.external_ip}:${srv.port}`;
            internalEl.innerText = `${srv.internal_ip || 'Local'}:${srv.port}`;
            netWrap.classList.remove('hidden');
          } else {
            netWrap.classList.add('hidden');
          }
        }

        // 2. Live Player Count Pill
        const playersWrap = document.getElementById('srv_players_wrap_' + idx);
        const playersEl = document.getElementById('srv_players_' + idx);
        if (playersWrap && playersEl) {
          if (srv.player_count !== null && srv.player_count !== undefined) {
            playersEl.innerText = `${srv.player_count} / ${srv.max_players}`;
            playersWrap.classList.remove('hidden');
            playersWrap.classList.add('inline-flex');
          } else {
            playersWrap.classList.add('hidden');
            playersWrap.classList.remove('inline-flex');
          }
        }
      });
    }

    renderTestPreview(data.preview);
    // Dynamically adjust polling frequency based on server states
    if (!document.hidden) {
      const hasTransitionalServer = data.servers.some(s => 
        ['starting', 'stopping'].includes((s.power_state || '').toLowerCase()) ||
        ((s.power_state || '').toLowerCase() !== 'offline' && s.is_updating)
      );
      const desiredInterval = hasTransitionalServer ? FAST_POLL_INTERVAL : STEADY_POLL_INTERVAL;
      
      if (currentPollInterval !== desiredInterval) {
        currentPollInterval = desiredInterval;
        startStatusPolling(desiredInterval);
      }
    }
  } catch (err) {}
}
// Dynamic status poll timer & tab visibility throttling
let statusPollTimer = null;
let currentPollInterval = null; // <-- FIX: Declare currentPollInterval
const FAST_POLL_INTERVAL = 1500;       // 1.5s when a server is starting/stopping
const STEADY_POLL_INTERVAL = 4000;     // 4.0s when all servers are steady
const BACKGROUND_POLL_INTERVAL = 8000; // 8.0s when tab is hidden

function startStatusPolling(interval = STEADY_POLL_INTERVAL) {
  if (statusPollTimer) clearInterval(statusPollTimer);
  statusPollTimer = setInterval(pollLiveStatus, interval);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    startStatusPolling(BACKGROUND_POLL_INTERVAL);
    if (telemetryPollTimer) {
      clearInterval(telemetryPollTimer);
      telemetryPollTimer = null;
    }
  } else {
    pollLiveStatus();
    startStatusPolling(STEADY_POLL_INTERVAL); // <-- FIX: was ACTIVE_POLL_INTERVAL
    if (isConsoleOpen && !telemetryPollTimer) {
      pollTelemetry();
      telemetryPollTimer = setInterval(pollTelemetry, 1000);
    }
  }
});

window.addEventListener('DOMContentLoaded', () => {
  makeDraggable('test-simulator-window', 'test-simulator-header');
  makeDraggable('live-console-window', 'live-console-header');
  pollLiveStatus();
  initServerBaselines();
  startStatusPolling(STEADY_POLL_INTERVAL); // <-- FIX: was ACTIVE_POLL_INTERVAL

  const urlParams = new URLSearchParams(window.location.search);
  const toastType = urlParams.get('toast');
  if (toastType) {
    const messages = {
      saved: ['All settings saved successfully!', 'success'],
      checked: ['Unified update check finished across all servers.', 'info'],
      renamed: ['Server name updated in Pterodactyl.', 'success'],
      server_added: ['New server added. Configure details and save.', 'info'],
      server_removed: ['Server removed from configuration.', 'info']
    };
    if (messages[toastType]) {
      showToast(messages[toastType][0], messages[toastType][1]);
    }
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  document.addEventListener('click', (e) => {
    document.querySelectorAll('[id^="steam_search_dropdown_"]').forEach(dropdown => {
      if (!dropdown.classList.contains('hidden')) {
        const idx = dropdown.id.replace('steam_search_dropdown_', '');
        const input = document.getElementById('srv_appid_input_' + idx);
        const toggleBtn = document.getElementById('steam_search_btn_' + idx);
        if (!dropdown.contains(e.target) && e.target !== input && (!toggleBtn || !toggleBtn.contains(e.target))) {
          dropdown.classList.add('hidden');
        }
      }
    });
  });
});
