/**
 * Test Mode build simulator modal, MitM controls, and live webhook preview renderer.
 * Hardened with safe DOM element construction and strict URL sanitization.
 */

import { showToast } from './toast.js';
import { sanitizeUrl, clearChildren } from './domUtils.js';

/**
 * Toggles Test Mode immediately and displays or hides the simulation floating window.
 *
 * @param {HTMLInputElement} el - Checkbox input element.
 */
export async function toggleTestModeImmediate(el) {
  const isEnabled = el.checked;
  const simWindow = document.getElementById('test-simulator-window');
  if (simWindow) {
    if (isEnabled) {
      simWindow.classList.remove('hidden');
    } else {
      simWindow.classList.add('hidden');
    }
  }

  try {
    const res = await fetch('/api/toggle-test-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: isEnabled })
    });
    if (!res.ok) throw new Error('Failed to update Test Mode');
    showToast(isEnabled ? 'Test Mode enabled (Simulation window active)' : 'Test Mode disabled', 'success');
  } catch (err) {
    console.error(err);
    el.checked = !isEnabled;
    if (simWindow) {
      if (!isEnabled) {
        simWindow.classList.remove('hidden');
      } else {
        simWindow.classList.add('hidden');
      }
    }
    showToast('Failed to update Test Mode.', 'error');
  }
}

/**
 * Toggles SSL verification immediately and persists configuration.
 *
 * @param {HTMLInputElement} el - Checkbox input element.
 */
export async function toggleSslVerifyImmediate(el) {
  const isEnabled = el.checked;
  try {
    const res = await fetch('/api/toggle-ssl-verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: isEnabled })
    });
    if (!res.ok) throw new Error('Failed to update SSL verification setting');
    showToast(isEnabled ? 'SSL Certificate Verification enabled' : 'SSL Certificate Verification disabled', 'success');
  } catch (err) {
    console.error(err);
    el.checked = !isEnabled;
    showToast('Failed to update SSL verification setting.', 'error');
  }
}

/**
 * Dispatches a simulated Steam build update for the target server.
 */
export async function triggerSimulateBuild() {
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
        server_idx: parseInt(serverIdent, 10) || 0,
        build_id: buildId
      })
    });
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      throw new Error(data.message || 'Simulation rejected');
    }
    showToast(`Simulated build ${buildId} applied. Update check dispatched!`, 'success');
    if (typeof window.pollLiveStatus === 'function') {
      window.pollLiveStatus();
    }
  } catch (err) {
    console.error(err);
    showToast(`Simulation failed: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerText = originalText;
  }
}

/**
 * Clears the active webhook preview from server store and resets the preview window.
 */
export async function clearTestPreview() {
  try {
    await fetch('/api/test/clear-preview', { method: 'POST' });
    renderTestPreview(null);
  } catch (err) {}
}

/**
 * Renders the simulated webhook preview card with safe DOM construction and sanitized links.
 *
 * @param {Object|null} preview - Preview payload or null.
 */
export function renderTestPreview(preview) {
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

  const timeEl = document.getElementById('sim-preview-time');
  if (timeEl) timeEl.textContent = preview.timestamp || '';

  const msgEl = document.getElementById('sim-preview-msg');
  if (msgEl) {
    if (preview.formatted_message) {
      msgEl.innerHTML = preview.formatted_message;
    } else {
      msgEl.textContent = preview.message || '';
    }
  }

  const embedWrap = document.getElementById('sim-preview-embed');
  if (preview.embed) {
    embedWrap.classList.remove('hidden');

    // Safe Title construction with URL sanitization
    const titleEl = document.getElementById('sim-preview-title');
    if (titleEl) {
      clearChildren(titleEl);
      const titleText = preview.embed.title || 'Steam Announcement';
      const safeUrl = sanitizeUrl(preview.embed.url);

      if (safeUrl) {
        const a = document.createElement('a');
        a.href = safeUrl;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'font-bold text-blue-400 hover:underline text-sm';
        a.textContent = titleText;
        titleEl.appendChild(a);
      } else {
        const span = document.createElement('span');
        span.className = 'font-bold text-white text-sm';
        span.textContent = titleText;
        titleEl.appendChild(span);
      }
    }

    const descEl = document.getElementById('sim-preview-desc');
    if (descEl) {
      if (preview.formatted_description) {
        descEl.innerHTML = preview.formatted_description;
      } else if (preview.embed.description) {
        descEl.textContent = preview.embed.description;
      } else {
        descEl.textContent = '';
      }
    }

    // Safe Image URL validation
    const imgEl = document.getElementById('sim-preview-img');
    const rawImgUrl = (preview.embed.image && preview.embed.image.url) ? preview.embed.image.url : (typeof preview.embed.image === 'string' ? preview.embed.image : null);
    const safeImgUrl = rawImgUrl ? sanitizeUrl(rawImgUrl) : '';

    if (imgEl) {
      if (safeImgUrl) {
        imgEl.src = safeImgUrl;
        imgEl.classList.remove('hidden');
      } else {
        imgEl.src = '';
        imgEl.classList.add('hidden');
      }
    }

    // Footer Text
    const footerEl = document.getElementById('sim-preview-footer');
    const footerText = (preview.embed.footer && preview.embed.footer.text) ? preview.embed.footer.text : (typeof preview.embed.footer === 'string' ? preview.embed.footer : null);

    if (footerEl) {
      if (footerText) {
        footerEl.textContent = footerText;
        footerEl.classList.remove('hidden');
      } else {
        footerEl.textContent = '';
        footerEl.classList.add('hidden');
      }
    }
  } else if (embedWrap) {
    embedWrap.classList.add('hidden');
  }
}
