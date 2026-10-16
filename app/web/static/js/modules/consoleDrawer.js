/**
 * Live telemetry console drawer, auto-scroll handling, and log filtering.
 * Hardened with safe DOM element construction to eliminate injection risks.
 */

import { clearChildren } from './domUtils.js';

let telemetryPollTimer = null;
let isConsoleOpen = false;
let currentFilter = '';

/**
 * Toggles the live console drawer window visibility and telemetry polling.
 */
export function toggleLiveConsole() {
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

/**
 * Clears recorded telemetry logs on the backend and updates the UI stream.
 */
export async function clearTelemetryLogs() {
  try {
    await fetch('/api/telemetry/clear', { method: 'POST' });
    const stream = document.getElementById('console-log-stream');
    if (stream) {
      clearChildren(stream);
      const msg = document.createElement('div');
      msg.className = 'text-gray-500 italic text-[11px] py-2 text-center';
      msg.textContent = 'Logs cleared.';
      stream.appendChild(msg);
    }
  } catch (err) {}
}

/**
 * Sets an optional log filter query (by endpoint, method, or details).
 *
 * @param {string} query - Filter term.
 */
export function filterLogs(query) {
  currentFilter = (query || '').toLowerCase().trim();
  pollTelemetry();
}

/**
 * Polls the backend telemetry endpoint and safely renders log streams and call frequency rates.
 */
export async function pollTelemetry() {
  if (!isConsoleOpen) return;
  try {
    const res = await fetch('/api/telemetry');
    if (!res.ok) return;
    const data = await res.json();

    // 1. Render Log Stream with Safe DOM Construction
    const stream = document.getElementById('console-log-stream');
    if (stream && Array.isArray(data.logs)) {
      clearChildren(stream);

      const logsToRender = currentFilter
        ? data.logs.filter(log =>
            (log.endpoint || '').toLowerCase().includes(currentFilter) ||
            (log.method || '').toLowerCase().includes(currentFilter) ||
            (log.details || '').toLowerCase().includes(currentFilter)
          )
        : data.logs;

      if (logsToRender.length === 0) {
        const emptyEl = document.createElement('div');
        emptyEl.className = 'text-gray-500 italic text-[11px] py-2 text-center';
        emptyEl.textContent = data.logs.length === 0 ? 'No recent calls recorded.' : 'No calls matching filter.';
        stream.appendChild(emptyEl);
      } else {
        const isScrolledToBottom = stream.scrollHeight - stream.clientHeight <= stream.scrollTop + 30;

        logsToRender.forEach(log => {
          const row = document.createElement('div');
          row.className = 'leading-tight py-0.5 flex items-start gap-1.5 hover:bg-gray-900/60 px-1 rounded';

          const timeSpan = document.createElement('span');
          timeSpan.className = 'text-gray-500 shrink-0 select-none';
          timeSpan.textContent = log.timestamp || '';

          const methodColor = log.method === 'POST' ? 'text-blue-400 font-bold' : log.method === 'UDP' ? 'text-purple-400 font-bold' : 'text-emerald-400 font-semibold';
          const methodSpan = document.createElement('span');
          methodSpan.className = `${methodColor} shrink-0 w-8 text-center text-[10px] bg-gray-900 px-1 rounded border border-gray-800`;
          methodSpan.textContent = log.method || '';

          const epSpan = document.createElement('span');
          epSpan.className = 'text-gray-200 font-semibold shrink-0';
          epSpan.textContent = log.endpoint || '';

          const statusColor = (log.status === '200' || log.status === '204') ? 'text-emerald-400' : 'text-rose-400';
          const statusSpan = document.createElement('span');
          statusSpan.className = `${statusColor} shrink-0`;
          statusSpan.textContent = `(${log.status || ''})`;

          const durSpan = document.createElement('span');
          durSpan.className = 'text-gray-500 shrink-0';
          durSpan.textContent = `${log.duration_ms ?? 0}ms`;

          const detailsSpan = document.createElement('span');
          detailsSpan.className = 'text-gray-400 truncate flex-1';
          detailsSpan.textContent = log.details || '';

          row.appendChild(timeSpan);
          row.appendChild(methodSpan);
          row.appendChild(epSpan);
          row.appendChild(statusSpan);
          row.appendChild(durSpan);
          row.appendChild(detailsSpan);

          stream.appendChild(row);
        });

        if (isScrolledToBottom) {
          stream.scrollTop = stream.scrollHeight;
        }
      }
    }

    // 2. Render Call Frequency Table (Calls/Minute)
    const ratesBody = document.getElementById('console-rates-body');
    if (ratesBody && Array.isArray(data.rates)) {
      clearChildren(ratesBody);

      if (data.rates.length === 0) {
        const emptyTr = document.createElement('tr');
        const emptyTd = document.createElement('td');
        emptyTd.colSpan = 2;
        emptyTd.className = 'py-3 px-3 text-center text-gray-500 italic';
        emptyTd.textContent = 'No calls in the last 60 seconds.';
        emptyTr.appendChild(emptyTd);
        ratesBody.appendChild(emptyTr);
      } else {
        data.rates.forEach(r => {
          const badgeBg = r.cpm > 25 ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' : 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30';

          const tr = document.createElement('tr');
          tr.className = 'hover:bg-gray-800/40 transition';

          const tdEndpoint = document.createElement('td');
          tdEndpoint.className = 'py-1 px-3 font-semibold text-gray-200';
          tdEndpoint.textContent = r.endpoint || '';

          const tdRate = document.createElement('td');
          tdRate.className = 'py-1 px-3 text-right';

          const badge = document.createElement('span');
          badge.className = `inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border ${badgeBg}`;
          badge.textContent = `${r.cpm} cpm`;
          tdRate.appendChild(badge);

          tr.appendChild(tdEndpoint);
          tr.appendChild(tdRate);
          ratesBody.appendChild(tr);
        });
      }
    }
  } catch (err) {}
}
