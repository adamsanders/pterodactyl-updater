/**
 * Adaptive polling loop for /api/status, server telemetry counters, and UI updates.
 * Throttles polling intervals based on tab visibility and server lifecycle transitions.
 */

import { showToast } from './toast.js';
import { updatePowerButtons, isServerDirty } from './serverCard.js';
import { renderTestPreview } from './simulatorModal.js';
import { clearChildren } from './domUtils.js';

export const FAST_POLL_INTERVAL = 1500;       // 1.5s when a server is starting/stopping/updating
export const STEADY_POLL_INTERVAL = 4000;     // 4.0s when all servers are steady
export const BACKGROUND_POLL_INTERVAL = 8000; // 8.0s when tab is hidden

let statusPollTimer = null;
let currentPollInterval = STEADY_POLL_INTERVAL;

const redundantStatuses = [
  "up to date",
  "update available",
  "update available — countdown started",
  "update available (countdown active)",
  "countdown in progress...",
  "idle"
];

/**
 * Starts status polling at the specified interval.
 *
 * @param {number} [interval=STEADY_POLL_INTERVAL] - Polling interval in ms.
 */
export function startStatusPolling(interval = STEADY_POLL_INTERVAL) {
  if (statusPollTimer) clearInterval(statusPollTimer);
  currentPollInterval = interval;
  statusPollTimer = setInterval(pollLiveStatus, interval);
}

/**
 * Fetches server status snapshot from /api/status and updates DOM elements safely.
 */
export async function pollLiveStatus() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();

    const globalCheckEl = document.getElementById('global-last-check');
    if (globalCheckEl && data.last_check) {
      globalCheckEl.textContent = data.last_check;
    }

    const versionEl = document.getElementById('app-version');
    if (versionEl && data.app_version) {
      versionEl.textContent = 'v' + data.app_version.replace(/^v/, '');
    }

    const commitEl = document.getElementById('app-commit');
    if (commitEl && data.commit_code) {
      commitEl.textContent = 'commit ' + data.commit_code;
    }

    if (Array.isArray(data.servers)) {
      data.servers.forEach(srv => {
        const idx = srv.idx;
        updatePowerButtons(idx, srv.power_state, srv.server_id);

        // Power Status Badge
        const badgeEl = document.getElementById('srv_power_badge_' + idx);
        if (badgeEl && srv.power_state) {
          const st = srv.power_state.toLowerCase();
          clearChildren(badgeEl);
          const dot = document.createElement('span');

          if (st === 'running') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-500/40';
            dot.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse';
            badgeEl.appendChild(dot);
            badgeEl.appendChild(document.createTextNode('Online'));
          } else if (st === 'offline') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-950/80 text-red-300 border border-red-500/40';
            dot.className = 'w-1.5 h-1.5 rounded-full bg-red-400';
            badgeEl.appendChild(dot);
            badgeEl.appendChild(document.createTextNode('Offline'));
          } else if (st === 'starting') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-500/40';
            dot.className = 'w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping';
            badgeEl.appendChild(dot);
            badgeEl.appendChild(document.createTextNode('Starting...'));
          } else if (st === 'stopping') {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-orange-950/80 text-orange-300 border border-orange-500/40';
            dot.className = 'w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse';
            badgeEl.appendChild(dot);
            badgeEl.appendChild(document.createTextNode('Stopping...'));
          } else {
            badgeEl.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-800 text-gray-400 border border-gray-700';
            dot.className = 'w-1.5 h-1.5 rounded-full bg-gray-500';
            badgeEl.appendChild(dot);
            badgeEl.appendChild(document.createTextNode('Unknown'));
          }
        }

        // Server Status Message
        const statusEl = document.getElementById('srv_status_' + idx);
        if (statusEl) {
          const rawStatus = (srv.last_status || '').trim();
          if (!rawStatus || redundantStatuses.includes(rawStatus.toLowerCase())) {
            statusEl.textContent = '';
            statusEl.className = 'hidden';
          } else if (rawStatus.toLowerCase().startsWith('error') || rawStatus.toLowerCase().includes('failed')) {
            statusEl.className = 'text-xs font-semibold text-red-400 bg-red-950/50 px-2 py-0.5 rounded border border-red-800/60';
            statusEl.textContent = rawStatus;
          } else {
            statusEl.className = 'text-xs font-medium text-indigo-300 bg-indigo-950/40 px-2 py-0.5 rounded border border-indigo-800/50';
            statusEl.textContent = rawStatus;
          }
        }

        // Countdown Timer
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

        // Build Status Indicators (Safe DOM Construction)
        const buildsEl = document.getElementById('srv_builds_' + idx);
        if (buildsEl) {
          const cur = srv.current_build || 'Unknown';
          const lat = srv.latest_build || 'Unknown';
          const isUpdating = srv.is_updating;
          clearChildren(buildsEl);

          const labelSpan = document.createElement('span');
          labelSpan.className = 'text-gray-400 mr-1.5';

          const valSpan = document.createElement('span');
          valSpan.className = 'font-mono text-gray-200';

          if (cur === lat && cur !== 'Unknown' && cur !== '?') {
            labelSpan.textContent = 'Build:';
            valSpan.textContent = lat;
            buildsEl.appendChild(labelSpan);
            buildsEl.appendChild(valSpan);

            // Green tick SVG
            const tickSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            tickSvg.setAttribute('class', 'w-4 h-4 text-emerald-400 inline-block ml-1');
            tickSvg.setAttribute('fill', 'none');
            tickSvg.setAttribute('stroke', 'currentColor');
            tickSvg.setAttribute('viewBox', '0 0 24 24');
            tickSvg.setAttribute('stroke-width', '2.5');
            const tickPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            tickPath.setAttribute('stroke-linecap', 'round');
            tickPath.setAttribute('stroke-linejoin', 'round');
            tickPath.setAttribute('d', 'M5 13l4 4L19 7');
            tickSvg.appendChild(tickPath);
            buildsEl.appendChild(tickSvg);
          } else if (cur !== 'Unknown' && lat !== 'Unknown') {
            labelSpan.textContent = 'Builds:';
            valSpan.textContent = `${cur} → ${lat}`;
            buildsEl.appendChild(labelSpan);
            buildsEl.appendChild(valSpan);

            if (isUpdating) {
              const swirlSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
              swirlSvg.setAttribute('class', 'animate-spin w-4 h-4 text-indigo-400 inline-block ml-2');
              swirlSvg.setAttribute('fill', 'none');
              swirlSvg.setAttribute('viewBox', '0 0 24 24');
              const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
              circle.setAttribute('class', 'opacity-25');
              circle.setAttribute('cx', '12');
              circle.setAttribute('cy', '12');
              circle.setAttribute('r', '10');
              circle.setAttribute('stroke', 'currentColor');
              circle.setAttribute('stroke-width', '4');
              const swirlPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
              swirlPath.setAttribute('class', 'opacity-75');
              swirlPath.setAttribute('fill', 'currentColor');
              swirlPath.setAttribute('d', 'M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z');
              swirlSvg.appendChild(circle);
              swirlSvg.appendChild(swirlPath);
              buildsEl.appendChild(swirlSvg);
            }
          } else {
            labelSpan.textContent = 'Builds:';
            valSpan.textContent = `${cur} → ${lat}`;
            buildsEl.appendChild(labelSpan);
            buildsEl.appendChild(valSpan);
          }
        }

        // Server Title & Input Sync
        const titleEl = document.getElementById('srv_title_' + idx);
        const inputEl = document.getElementById('srv_name_input_' + idx);
        if (titleEl && srv.name && !isServerDirty(idx)) {
          const allTitles = Array.from(document.querySelectorAll('[id^="srv_title_"]'));
          const displayIdx = allTitles.indexOf(titleEl);
          const cardNum = displayIdx !== -1 ? displayIdx + 1 : (idx + 1);
          titleEl.textContent = 'Server #' + cardNum + ': ' + srv.name;
          if (inputEl && inputEl.readOnly) {
            inputEl.value = srv.name;
          }
        }

        // Network Address & Mouseover Internal IP
        const netWrap = document.getElementById('srv_net_wrap_' + idx);
        const addrEl = document.getElementById('srv_address_' + idx);
        const internalEl = document.getElementById('srv_internal_ip_' + idx);
        if (netWrap && addrEl && internalEl) {
          if (srv.external_ip && srv.port) {
            addrEl.textContent = `${srv.external_ip}:${srv.port}`;
            internalEl.textContent = `${srv.internal_ip || 'Local'}:${srv.port}`;
            netWrap.classList.remove('hidden');
          } else {
            netWrap.classList.add('hidden');
          }
        }

        // Player Count Pill
        const playersWrap = document.getElementById('srv_players_wrap_' + idx);
        const playersEl = document.getElementById('srv_players_' + idx);
        if (playersWrap && playersEl) {
          if (srv.player_count !== null && srv.player_count !== undefined) {
            playersEl.textContent = `${srv.player_count} / ${srv.max_players}`;
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
    if (!document.hidden && Array.isArray(data.servers)) {
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

/**
 * Calculates remaining countdown seconds and updates badge text every second.
 */
export function updateCountdowns() {
  const now = Date.now() / 1000;
  document.querySelectorAll('.countdown-timer').forEach(el => {
    const target = parseFloat(el.getAttribute('data-target'));
    const wrap = el.closest('[id^="srv_countdown_wrap_"]');
    if (!target || target <= now) {
      if (wrap) wrap.classList.add('hidden');
      el.textContent = "";
      return;
    }
    if (wrap) wrap.classList.remove('hidden');
    const remaining = Math.floor(target - now);
    const mins = Math.floor(remaining / 60);
    const secs = remaining % 60;
    el.textContent = mins + "m " + secs + "s";
  });
}

/**
 * Dispatches an on-demand update check across all servers.
 *
 * @param {HTMLButtonElement} btn - Trigger button.
 */
export async function triggerCheckNow(btn) {
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('opacity-75', 'cursor-not-allowed');
  const originalHtml = btn.innerHTML;
  btn.innerHTML = '<svg class="animate-spin w-4 h-4 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Checking all servers...';

  try {
    let res = await fetch('/api/check-now', {
      method: 'POST',
      headers: { 'Accept': 'application/json' }
    });
    if (!res.ok && res.status === 404) {
      res = await fetch('/check-now', {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
      });
    }
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
