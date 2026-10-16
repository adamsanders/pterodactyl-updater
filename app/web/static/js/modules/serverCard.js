/**
 * Server card interactions: dirty state tracking, single-server save,
 * auto-sync server details, manifest updates, and power button state management.
 */

import { showToast } from './toast.js';

export const STOP_ICON = `<svg class="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>`;
export const KILL_ICON = `<svg class="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24"><path d="M12 2a9 9 0 0 0-9 9c0 3.3 1.8 6.2 4.5 7.7V21a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1v-2.3c2.7-1.5 4.5-4.4 4.5-7.7a9 9 0 0 0-9-9zm-3 10a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm6 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/></svg>`;

export const POWER_BUTTON_STYLES = {
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

export const serverBaselines = {};
export const stoppingStateTrackers = {};
const serverIdDebounceTimers = {};

/**
 * Resolves the 1-based display number of a server card based on its actual DOM position.
 */
export function getCardDisplayNumber(idx, titleEl = null) {
  const el = titleEl || document.getElementById('srv_title_' + idx);
  if (el) {
    const allTitles = Array.from(document.querySelectorAll('[id^="srv_title_"]'));
    const pos = allTitles.indexOf(el);
    if (pos !== -1) return pos + 1;
  }
  return parseInt(idx, 10) + 1;
}

/**
 * Initializes baseline configuration snapshots for all servers on page load.
 */
export function initServerBaselines() {
  document.querySelectorAll('[id^="srv_title_"]').forEach(el => {
    const idx = el.id.replace('srv_title_', '');
    const nameInput = document.getElementById('srv_name_input_' + idx);
    const idInput = document.getElementById('srv_id_input_' + idx);
    const appidInput = document.getElementById('srv_appid_input_' + idx);
    const manifestInput = document.getElementById('srv_manifest_input_' + idx);
    const portOffsetInput = document.getElementById('srv_port_offset_input_' + idx);
    const broadcastCmdInput = document.getElementById('srv_broadcast_cmd_input_' + idx);

    serverBaselines[idx] = {
      name: nameInput ? nameInput.value : '',
      server_id: idInput ? idInput.value : '',
      app_id: appidInput ? appidInput.value : '',
      manifest_path: manifestInput ? manifestInput.value : '',
      query_port_offset: portOffsetInput ? portOffsetInput.value : '0',
      broadcast_command_template: broadcastCmdInput ? broadcastCmdInput.value : 'say {message}'
    };
  });
}

/**
 * Checks if inputs for server at index differ from baseline snapshot.
 *
 * @param {number|string} idx - Server index.
 * @returns {boolean} - True if dirty.
 */
export function isServerDirty(idx) {
  const base = serverBaselines[idx];
  if (!base) return false;
  const nameInput = document.getElementById('srv_name_input_' + idx);
  const idInput = document.getElementById('srv_id_input_' + idx);
  const appidInput = document.getElementById('srv_appid_input_' + idx);
  const manifestInput = document.getElementById('srv_manifest_input_' + idx);
  const portOffsetInput = document.getElementById('srv_port_offset_input_' + idx);
  const broadcastCmdInput = document.getElementById('srv_broadcast_cmd_input_' + idx);

  return (
    (nameInput && nameInput.value !== base.name) ||
    (idInput && idInput.value !== base.server_id) ||
    (appidInput && appidInput.value !== base.app_id) ||
    (manifestInput && manifestInput.value !== base.manifest_path) ||
    (portOffsetInput && portOffsetInput.value !== base.query_port_offset) ||
    (broadcastCmdInput && broadcastCmdInput.value !== base.broadcast_command_template)
  );
}

/**
 * Toggles visibility of the single-server Save button based on dirty state.
 *
 * @param {number|string} idx - Server index.
 */
export function checkServerDirty(idx) {
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

/**
 * Input event listener for any text input on a server card.
 *
 * @param {number|string} idx - Server index.
 */
export function onServerTextInput(idx) {
  checkServerDirty(idx);
}

/**
 * Debounced input handler for Server ID field.
 *
 * @param {string} identifier - Server ID or index.
 * @param {number|string} idx - Server index.
 */
export function onServerIdInput(identifier, idx) {
  checkServerDirty(idx);
  if (serverIdDebounceTimers[idx]) {
    clearTimeout(serverIdDebounceTimers[idx]);
  }
  serverIdDebounceTimers[idx] = setTimeout(() => {
    autoSyncServerDetails(identifier, idx);
  }, 700);
}

/**
 * Change handler for Server ID field triggering immediate metadata lookup.
 *
 * @param {string} identifier - Server ID or index.
 * @param {number|string} idx - Server index.
 */
export function onServerIdChange(identifier, idx) {
  checkServerDirty(idx);
  autoSyncServerDetails(identifier, idx);
}

/**
 * Auto-detects server name and App ID from Pterodactyl when a Server ID is entered.
 *
 * @param {string} identifier - Server ID or index.
 * @param {number|string} idx - Server index.
 */
export async function autoSyncServerDetails(identifier, idx) {
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
        if (titleEl) titleEl.textContent = `Server #${getCardDisplayNumber(idx, titleEl)}: ${d.name}`;
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

/**
 * Intelligently updates the manifest path based on a newly entered or selected App ID.
 *
 * @param {number|string} idx - Server index.
 * @param {string} newAppId - New Steam App ID.
 */
export function updateManifestAppId(idx, newAppId) {
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

/**
 * Input event listener for manual App ID input field.
 *
 * @param {number|string} idx - Server index.
 */
export function onSteamAppIdInput(idx) {
  checkServerDirty(idx);
  const appidInput = document.getElementById('srv_appid_input_' + idx);
  const val = appidInput?.value.trim();
  if (val && /^\d+$/.test(val) && val !== '1007' && val !== '228980') {
    updateManifestAppId(idx, val);
  }
}

/**
 * Refreshes server name directly from Pterodactyl API and updates UI and baseline.
 *
 * @param {string} identifier - Server ID or index.
 * @param {number|string} idx - Server index.
 */
export async function refreshServerName(identifier, idx) {
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
    if (titleEl) titleEl.textContent = `Server #${getCardDisplayNumber(idx, titleEl)}: ${data.name}`;

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

/**
 * Toggles a server-specific boolean switch slider asynchronously.
 *
 * @param {string} identifier - Server ID or index.
 * @param {number|string} idx - Server index.
 * @param {string} field - Field name.
 * @param {HTMLInputElement} el - Checkbox element.
 */
export async function toggleServerSlider(identifier, idx, field, el) {
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
    const cardNum = getCardDisplayNumber(idx);
    showToast(`${label} ${isChecked ? 'enabled' : 'disabled'} for Server #${cardNum}`, 'success');
  } catch (err) {
    console.error(err);
    el.checked = !isChecked;
    showToast(`Failed to update ${label}: ${err.message}`, 'error');
  }
}

/**
 * Saves configuration for a single server card without submitting the entire dashboard form.
 *
 * @param {string} identifier - Server ID or index.
 * @param {number|string} idx - Server index.
 */
export async function saveSingleServer(identifier, idx) {
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
  const broadcastCmdVal = document.getElementById('srv_broadcast_cmd_input_' + idx)?.value || 'say {message}';

  try {
    const res = await fetch(`/api/servers/${encodeURIComponent(identifier)}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: nameVal,
        server_id: idVal,
        app_id: appidVal,
        manifest_path: manifestVal,
        query_port_offset: portOffsetVal,
        broadcast_command_template: broadcastCmdVal
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
      query_port_offset: String(savedSrv.query_port_offset ?? 0),
      broadcast_command_template: savedSrv.broadcast_command_template ?? 'say {message}'
    };

    const nameInput = document.getElementById('srv_name_input_' + idx);
    if (nameInput) nameInput.value = savedSrv.name;
    const portOffsetInput = document.getElementById('srv_port_offset_input_' + idx);
    if (portOffsetInput) portOffsetInput.value = savedSrv.query_port_offset ?? 0;
    const broadcastCmdInput = document.getElementById('srv_broadcast_cmd_input_' + idx);
    if (broadcastCmdInput) broadcastCmdInput.value = savedSrv.broadcast_command_template ?? 'say {message}';
    const titleEl = document.getElementById('srv_title_' + idx);
    const cardNum = getCardDisplayNumber(idx, titleEl);
    if (titleEl) titleEl.textContent = `Server #${cardNum}: ${savedSrv.name}`;

    checkServerDirty(idx);
    showToast(`Server #${cardNum} (${savedSrv.name}) saved successfully!`, 'success');
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

/**
 * Toggles edit mode for server name input field.
 *
 * @param {number|string} idx - Server index.
 */
export function toggleEditName(idx) {
  const input = document.getElementById('srv_name_input_' + idx);
  const saveBtn = document.getElementById('save_name_btn_' + idx);
  const editBtn = document.getElementById('edit_btn_' + idx);

  if (!input) return;

  if (input.readOnly) {
    input.readOnly = false;
    input.classList.remove('bg-gray-950/60', 'text-gray-400', 'cursor-not-allowed');
    input.classList.add('bg-gray-950', 'text-white', 'border-indigo-500');
    input.focus();
    if (saveBtn) saveBtn.classList.remove('hidden');
    if (editBtn) {
      editBtn.innerText = 'Cancel';
      editBtn.classList.remove('text-indigo-400', 'hover:text-indigo-300');
      editBtn.classList.add('text-gray-400', 'hover:text-gray-300');
    }
  } else {
    input.readOnly = true;
    input.classList.add('bg-gray-950/60', 'text-gray-400', 'cursor-not-allowed');
    input.classList.remove('bg-gray-950', 'text-white', 'border-indigo-500');
    if (saveBtn) saveBtn.classList.add('hidden');
    if (editBtn) {
      editBtn.innerText = 'Edit';
      editBtn.classList.remove('text-gray-400', 'hover:text-gray-300');
      editBtn.classList.add('text-indigo-400', 'hover:text-indigo-300');
    }
    if (serverBaselines[idx]) {
      input.value = serverBaselines[idx].name;
      checkServerDirty(idx);
    }
  }
}

/**
 * Helper to update button visual and disabled state.
 */
export function setButtonState(btn, type, isEnabled) {
  if (!btn) return;
  btn.disabled = !isEnabled;
  const base = "flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition ";
  btn.className = base + (isEnabled ? POWER_BUTTON_STYLES[type].enabled : POWER_BUTTON_STYLES[type].disabled);
}

/**
 * Renders the Stop button.
 */
export function renderStopButton(btn, idx, isEnabled, serverId = null) {
  if (!btn) return;
  btn.disabled = !isEnabled;
  const ident = serverId || idx;
  btn.onclick = () => triggerPowerAction(ident, 'stop', idx);
  btn.innerHTML = `${STOP_ICON} Stop`;
  const base = "flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition ";
  btn.className = base + (isEnabled ? POWER_BUTTON_STYLES.stop.enabled : POWER_BUTTON_STYLES.stop.disabled);
}

/**
 * Renders the Kill button during stopping state.
 */
export function renderKillButton(btn, idx, isEnabled, serverId = null) {
  if (!btn) return;
  btn.disabled = !isEnabled;
  const ident = serverId || idx;
  btn.onclick = () => triggerPowerAction(ident, 'kill', idx);
  btn.innerHTML = `${KILL_ICON} Kill`;
  const base = "flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition ";
  btn.className = base + (isEnabled ? POWER_BUTTON_STYLES.kill.enabled : POWER_BUTTON_STYLES.kill.disabled);
}

/**
 * Updates power button styles and states based on current power state.
 *
 * @param {number|string} idx - Server index.
 * @param {string} powerState - Power state string ('running', 'offline', etc.).
 * @param {string|null} [serverId=null] - Server ID.
 */
export function updatePowerButtons(idx, powerState, serverId = null) {
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

/**
 * Triggers a power action (start, restart, stop, kill) for a server.
 *
 * @param {string|number} identifier - Server ID or index.
 * @param {string} action - 'start', 'restart', 'stop', or 'kill'.
 * @param {number|null} [uiIndex=null] - UI index.
 */
export async function triggerPowerAction(identifier, action, uiIndex = null) {
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
    if (typeof window.pollLiveStatus === 'function') {
      window.pollLiveStatus();
    }
  } catch (err) {
    console.error(err);
    showToast(`Failed to ${action} server: ${err.message}`, 'error');
    if (typeof window.pollLiveStatus === 'function') {
      window.pollLiveStatus();
    }
  }
}
