/**
 * Main dashboard application entry point orchestrating modular ES frontend architecture.
 * Initializes core services, status polling, interactive windows, and drag-and-drop.
 */

import { showToast } from './modules/toast.js';
import { sanitizeUrl, setText, clearChildren, createSafeLink, createElement } from './modules/domUtils.js';
import {
  makeDraggable as _makeDraggable,
  initServerDragAndDrop,
  reindexServerCards
} from './modules/dragDrop.js';
import {
  pollLiveStatus as _pollLiveStatus,
  startStatusPolling,
  updateCountdowns,
  triggerCheckNow,
  FAST_POLL_INTERVAL,
  STEADY_POLL_INTERVAL,
  BACKGROUND_POLL_INTERVAL
} from './modules/statusPoller.js';
import {
  serverBaselines,
  stoppingStateTrackers,
  initServerBaselines,
  isServerDirty,
  checkServerDirty,
  onServerTextInput,
  onServerIdInput,
  onServerIdChange,
  autoSyncServerDetails,
  updateManifestAppId,
  onSteamAppIdInput,
  refreshServerName,
  toggleServerSlider,
  saveSingleServer,
  toggleEditName,
  setButtonState,
  renderStopButton,
  renderKillButton,
  updatePowerButtons,
  renderPowerButtons as _renderPowerButtons,
  updateServerCardStatus as _updateServerCardStatus,
  triggerTestWebhook as _triggerTestWebhook,
  triggerPowerAction as _triggerPowerAction,
  getCardContext,
  initServerCardDelegation
} from './modules/serverCard.js';
import {
  openSteamAppSearch,
  toggleSteamAppSearch,
  closeSteamAppSearch,
  onSteamSearchQueryInput,
  fetchSteamSearchResults,
  selectSteamGame
} from './modules/steamSearch.js';
import {
  toggleLiveConsole as _toggleLiveConsole,
  clearTelemetryLogs,
  pollTelemetry,
  filterLogs
} from './modules/consoleDrawer.js';
import {
  openSimulatorWindow as _openSimulatorWindow,
  closeSimulatorWindow as _closeSimulatorWindow,
  toggleSimulatorWindow as _toggleSimulatorWindow,
  toggleTestModeImmediate,
  toggleSslVerifyImmediate,
  triggerSimulateBuild,
  clearTestPreview,
  renderTestPreview
} from './modules/simulatorModal.js';

// Re-export named functions guaranteeing 100% backward compatibility for inline HTML handlers & tests
export function makeDraggable(elId, headerId) {
  return _makeDraggable(elId, headerId);
}

export function toggleLiveConsole() {
  return _toggleLiveConsole();
}

export function openSimulatorWindow() {
  return _openSimulatorWindow();
}

export function closeSimulatorWindow() {
  return _closeSimulatorWindow();
}

export function toggleSimulatorWindow() {
  return _toggleSimulatorWindow();
}

export function updateServerCardStatus(srv) {
  return _updateServerCardStatus(srv);
}

export function renderPowerButtons(idx, powerState, serverId = null) {
  return _renderPowerButtons(idx, powerState, serverId);
}

export function triggerTestWebhook(serverId, btn = null) {
  return _triggerTestWebhook(serverId, btn);
}

export function pollLiveStatus() {
  return _pollLiveStatus();
}

export function triggerPowerAction(identifier, action, uiIndex = null) {
  return _triggerPowerAction(identifier, action, uiIndex);
}

export { getCardContext, initServerCardDelegation, toggleSslVerifyImmediate };

// Bind handlers to global window object for HTML inline onclick/onchange/oninput attributes
window.makeDraggable = makeDraggable;
window.toggleLiveConsole = toggleLiveConsole;
window.openSimulatorWindow = openSimulatorWindow;
window.closeSimulatorWindow = closeSimulatorWindow;
window.toggleSimulatorWindow = toggleSimulatorWindow;
window.updateServerCardStatus = updateServerCardStatus;
window.renderPowerButtons = renderPowerButtons;
window.triggerTestWebhook = triggerTestWebhook;
window.pollLiveStatus = pollLiveStatus;
window.triggerPowerAction = triggerPowerAction;
window.showToast = showToast;
window.triggerCheckNow = triggerCheckNow;
window.clearTelemetryLogs = clearTelemetryLogs;
window.pollTelemetry = pollTelemetry;
window.filterLogs = filterLogs;
window.toggleTestModeImmediate = toggleTestModeImmediate;
window.toggleSslVerifyImmediate = toggleSslVerifyImmediate;
window.triggerSimulateBuild = triggerSimulateBuild;
window.clearTestPreview = clearTestPreview;
window.renderTestPreview = renderTestPreview;
window.saveSingleServer = saveSingleServer;
window.refreshServerName = refreshServerName;
window.toggleServerSlider = toggleServerSlider;
window.toggleEditName = toggleEditName;
window.openSteamAppSearch = openSteamAppSearch;
window.toggleSteamAppSearch = toggleSteamAppSearch;
window.closeSteamAppSearch = closeSteamAppSearch;
window.onSteamSearchQueryInput = onSteamSearchQueryInput;
window.fetchSteamSearchResults = fetchSteamSearchResults;
window.selectSteamGame = selectSteamGame;
window.onServerTextInput = onServerTextInput;
window.onServerIdInput = onServerIdInput;
window.onServerIdChange = onServerIdChange;
window.autoSyncServerDetails = autoSyncServerDetails;
window.updateManifestAppId = updateManifestAppId;
window.onSteamAppIdInput = onSteamAppIdInput;
window.initServerBaselines = initServerBaselines;
window.checkServerDirty = checkServerDirty;
window.initServerDragAndDrop = initServerDragAndDrop;
window.reindexServerCards = reindexServerCards;
window.getCardContext = getCardContext;
window.initServerCardDelegation = initServerCardDelegation;

// Countdown ticker
setInterval(updateCountdowns, 1000);

// Throttled background polling on tab visibility change
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    startStatusPolling(BACKGROUND_POLL_INTERVAL);
  } else {
    pollLiveStatus();
    startStatusPolling(STEADY_POLL_INTERVAL);
  }
});

// Orchestrate module initialization on DOM ready
function initDashboard() {
  initServerCardDelegation();
  makeDraggable('test-simulator-window', 'test-simulator-header');
  makeDraggable('live-console-window', 'live-console-header');
  initServerDragAndDrop();
  initServerBaselines();
  updateCountdowns();
  pollLiveStatus();
  startStatusPolling(STEADY_POLL_INTERVAL);

  // Check URL query parameters for toast notifications
  const urlParams = new URLSearchParams(window.location.search);
  const toastType = urlParams.get('toast');
  if (toastType) {
    const messages = {
      saved: ['All settings saved successfully!', 'success'],
      checked: ['Unified update check finished across all servers.', 'info'],
      renamed: ['Server name updated in Pterodactyl.', 'success'],
      server_added: ['New server added. Configure details and save.', 'info'],
      server_removed: ['Server removed from configuration.', 'info'],
      test_webhook: ['Test alert dispatched.', 'info']
    };
    if (messages[toastType]) {
      showToast(messages[toastType][0], messages[toastType][1]);
    }
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  if (urlParams.get('open_sim') === '1' || urlParams.get('open_sim') === 'true') {
    openSimulatorWindow();
  }

  // Close Steam search popovers when clicking outside
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
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDashboard);
} else {
  initDashboard();
}
