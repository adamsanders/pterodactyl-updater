/**
 * Steam game search modal, debounced input, and manifest auto-fill.
 * Hardened with safe DOM element construction to eliminate XSS risks.
 */

import { showToast } from './toast.js';
import { updateManifestAppId, checkServerDirty } from './serverCard.js';
import { clearChildren } from './domUtils.js';

const steamSearchDebounceTimers = {};

/**
 * Opens the Steam search dropdown for the specified server index.
 *
 * @param {number|string} idx - Server index.
 */
export function openSteamAppSearch(idx) {
  const dropdown = document.getElementById('steam_search_dropdown_' + idx);
  if (!dropdown) return;
  dropdown.classList.remove('hidden');
  const queryInput = document.getElementById('steam_search_query_' + idx);
  if (queryInput && !queryInput.value.trim()) {
    fetchSteamSearchResults(idx, '');
  }
}

/**
 * Toggles the Steam search dropdown open/closed.
 *
 * @param {number|string} idx - Server index.
 */
export function toggleSteamAppSearch(idx) {
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

/**
 * Closes the Steam search dropdown.
 *
 * @param {number|string} idx - Server index.
 */
export function closeSteamAppSearch(idx) {
  const dropdown = document.getElementById('steam_search_dropdown_' + idx);
  if (dropdown) dropdown.classList.add('hidden');
}

/**
 * Debounced input handler for Steam search input field.
 *
 * @param {number|string} idx - Server index.
 */
export function onSteamSearchQueryInput(idx) {
  if (steamSearchDebounceTimers[idx]) {
    clearTimeout(steamSearchDebounceTimers[idx]);
  }
  steamSearchDebounceTimers[idx] = setTimeout(() => {
    const queryInput = document.getElementById('steam_search_query_' + idx);
    fetchSteamSearchResults(idx, queryInput?.value.trim() || '');
  }, 300);
}

/**
 * Fetches Steam game search results and renders them using safe DOM construction.
 *
 * @param {number|string} idx - Server index.
 * @param {string} query - Search term.
 */
export async function fetchSteamSearchResults(idx, query) {
  const resultsContainer = document.getElementById('steam_search_results_' + idx);
  if (!resultsContainer) return;

  clearChildren(resultsContainer);
  const loadingEl = document.createElement('div');
  loadingEl.className = 'text-gray-400 italic text-[11px] p-2 text-center';
  loadingEl.textContent = 'Searching Steam catalog...';
  resultsContainer.appendChild(loadingEl);

  try {
    const res = await fetch(`/api/steam/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    clearChildren(resultsContainer);

    if (res.ok && data.status === 'ok' && Array.isArray(data.results)) {
      if (data.results.length === 0) {
        const emptyEl = document.createElement('div');
        emptyEl.className = 'text-gray-500 italic text-[11px] p-2 text-center';
        emptyEl.textContent = 'No matching Steam games found.';
        resultsContainer.appendChild(emptyEl);
        return;
      }

      data.results.forEach(item => {
        const isDedi = item.type === 'dedicated_server';
        const badgeBg = isDedi ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40' : 'bg-gray-800 text-gray-400 border-gray-700';
        const labelBadge = isDedi ? 'Dedicated Server' : 'Game';

        const row = document.createElement('div');
        row.className = 'flex items-center justify-between p-2 rounded hover:bg-gray-800/80 cursor-pointer transition border border-transparent hover:border-gray-700 select-none';
        row.addEventListener('click', () => {
          selectSteamGame(idx, item.app_id, item.name);
        });

        const leftCol = document.createElement('div');
        leftCol.className = 'flex items-center gap-2 min-w-0 pr-2';

        const nameSpan = document.createElement('span');
        nameSpan.className = 'text-gray-200 font-medium truncate';
        nameSpan.textContent = item.name || '';
        leftCol.appendChild(nameSpan);

        const badgeSpan = document.createElement('span');
        badgeSpan.className = `px-1.5 py-0.5 rounded text-[10px] font-bold border ${badgeBg} whitespace-nowrap`;
        badgeSpan.textContent = labelBadge;
        leftCol.appendChild(badgeSpan);

        const appIdSpan = document.createElement('span');
        appIdSpan.className = 'font-mono text-[11px] text-amber-300 bg-gray-950 px-1.5 py-0.5 rounded border border-gray-800 shrink-0';
        appIdSpan.textContent = item.app_id || '';

        row.appendChild(leftCol);
        row.appendChild(appIdSpan);
        resultsContainer.appendChild(row);
      });
    } else {
      const errEl = document.createElement('div');
      errEl.className = 'text-red-400 text-[11px] p-2 text-center';
      errEl.textContent = 'Error loading results.';
      resultsContainer.appendChild(errEl);
    }
  } catch (err) {
    clearChildren(resultsContainer);
    const errEl = document.createElement('div');
    errEl.className = 'text-gray-500 italic text-[11px] p-2 text-center';
    errEl.textContent = 'Search unavailable.';
    resultsContainer.appendChild(errEl);
  }
}

/**
 * Applies selected Steam App ID and updates manifest path.
 *
 * @param {number|string} idx - Server index.
 * @param {string} appId - Steam App ID.
 * @param {string} gameName - Selected game name.
 */
export function selectSteamGame(idx, appId, gameName) {
  const appidInput = document.getElementById('srv_appid_input_' + idx);
  if (appidInput) {
    appidInput.value = appId;
  }
  updateManifestAppId(idx, appId);
  closeSteamAppSearch(idx);
  checkServerDirty(idx);
  showToast(`Selected ${gameName} (${appId}). Manifest path updated.`, 'success');
}
