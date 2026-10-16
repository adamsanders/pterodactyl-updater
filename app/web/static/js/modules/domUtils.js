/**
 * Safe DOM utilities, element construction helpers, and URL sanitization.
 */

/**
 * Sanitizes a URL, permitting only http: and https: protocols.
 * Explicitly rejects javascript:, data:, and vbscript: URIs to prevent XSS.
 *
 * @param {string} url - The URL to sanitize.
 * @returns {string} - The sanitized URL, or an empty string if unsafe.
 */
export function sanitizeUrl(url) {
  if (!url || typeof url !== 'string') return '';
  const trimmed = url.trim();

  // Strip control characters and whitespace from scheme check to prevent evasion
  const schemeCheck = trimmed.replace(/[\x00-\x20\s]+/g, '').toLowerCase();
  if (/^(?:javascript|data|vbscript):/.test(schemeCheck)) {
    return '';
  }

  const base = typeof window !== 'undefined' && window.location && window.location.origin && window.location.origin !== 'null'
    ? window.location.origin
    : 'https://example.com';

  try {
    const parsed = new URL(trimmed, base);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return trimmed;
    }
  } catch {
    return '';
  }

  return '';
}

/**
 * Safely sets the textContent of an element identified by ID or element reference.
 *
 * @param {string|HTMLElement} elOrId - Element or element ID.
 * @param {string|number} text - Text to set.
 */
export function setText(elOrId, text) {
  const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
  if (el) {
    el.textContent = text !== null && text !== undefined ? String(text) : '';
  }
}

/**
 * Safely clears all child nodes of an element.
 *
 * @param {string|HTMLElement} elOrId - Element or element ID.
 */
export function clearChildren(elOrId) {
  const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
  if (!el) return;
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

/**
 * Safely creates a link or fallback span with validated href.
 *
 * @param {string} url - Target URL.
 * @param {string} text - Link display text.
 * @param {string} className - Optional CSS classes.
 * @returns {HTMLElement} - Constructed <a> or <span> element.
 */
export function createSafeLink(url, text, className = '') {
  const safe = sanitizeUrl(url);
  const displayText = (text !== null && text !== undefined && text !== '') ? String(text) : (safe || '');
  if (safe) {
    const a = document.createElement('a');
    a.href = safe;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    if (className) a.className = className;
    a.textContent = displayText;
    return a;
  }
  const span = document.createElement('span');
  if (className) span.className = className;
  span.textContent = displayText;
  return span;
}

/**
 * Helper to construct DOM elements safely with attributes and children.
 *
 * @param {string} tag - HTML tag name.
 * @param {Object} attrs - Attribute key-value pairs.
 * @param {Array|Node|string} children - Child nodes or text.
 * @returns {HTMLElement} - Created DOM element.
 */
export function createElement(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  const tagLower = tag.toLowerCase();
  for (const [key, val] of Object.entries(attrs)) {
    if (key === 'className' || key === 'class') {
      el.className = val;
    } else if (key === 'href' && (tagLower === 'a' || tagLower === 'area')) {
      const safe = sanitizeUrl(val);
      if (safe) el.setAttribute('href', safe);
    } else if (key === 'src' && (tagLower === 'img' || tagLower === 'audio' || tagLower === 'video')) {
      const safe = sanitizeUrl(val);
      if (safe) el.setAttribute('src', safe);
    } else if (key.startsWith('on') && typeof val === 'function') {
      const eventName = key.slice(2).toLowerCase();
      el.addEventListener(eventName, val);
    } else if (val !== null && val !== undefined) {
      el.setAttribute(key, String(val));
    }
  }

  const childList = Array.isArray(children) ? children : [children];
  for (const child of childList) {
    if (child instanceof Node) {
      el.appendChild(child);
    } else if (child !== null && child !== undefined) {
      el.appendChild(document.createTextNode(String(child)));
    }
  }
  return el;
}
