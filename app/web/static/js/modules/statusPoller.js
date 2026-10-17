/**
 * Adaptive polling loop for /api/status, server telemetry counters, and UI updates.
 * Throttles polling intervals based on tab visibility and server lifecycle transitions.
 */

import { showToast } from './toast.js';
import { updatePowerButtons, isServerDirty, updateServerCardStatus } from './serverCard.js';
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
 * Resolves visual card number based on actual DOM position (allTitles.indexOf(titleEl) => cardNum).
 *
 * @param {HTMLElement} titleEl - Title element.
 * @param {number|string} idx - Card index fallback.
 * @returns {number}
 */
export function getVisualCardNumber(titleEl, idx) {
  if (!titleEl) return parseInt(idx, 10) + 1;
  const allTitles = Array.from(document.querySelectorAll('[id^="srv_title_"]'));
  const displayIdx = allTitles.indexOf(titleEl);
  const cardNum = displayIdx !== -1 ? displayIdx + 1 : (parseInt(idx, 10) + 1);
  return cardNum;
}

/**
 * Fallback to recover "Checking..." badges to "Unknown" with enabled power buttons on network or polling errors.
 */
export function fallbackUnknownStatus() {
  document.querySelectorAll('[id^="srv_power_badge_"]').forEach(badge => {
    if (badge.textContent && badge.textContent.includes('Checking...')) {
      const idx = badge.id.replace('srv_power_badge_', '');
      clearChildren(badge);
      const dot = document.createElement('span');
      badge.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-800 text-gray-400 border border-gray-700';
      dot.className = 'w-1.5 h-1.5 rounded-full bg-gray-500';
      badge.appendChild(dot);
      badge.appendChild(document.createTextNode('Unknown'));
      updatePowerButtons(idx, 'unknown');
    }
  });
}

/**
 * Fetches server status snapshot from /api/status and updates DOM elements safely.
 */
export async function pollLiveStatus() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    if (!res.ok) {
      fallbackUnknownStatus();
      return;
    }
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
        updateServerCardStatus(srv);
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
  } catch (err) {
    fallbackUnknownStatus();
  }
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
