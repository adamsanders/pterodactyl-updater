/**
 * Toast notification rendering and timeout handling.
 */

/**
 * Displays a toast notification in the toast container.
 *
 * @param {string} message - Notification text.
 * @param {'success'|'error'|'info'} type - Toast type / color scheme.
 */
export function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  const borderBg = type === 'success'
    ? 'bg-emerald-950/90 border-emerald-500/40 text-emerald-200'
    : type === 'error'
    ? 'bg-red-950/90 border-red-500/40 text-red-200'
    : 'bg-indigo-950/90 border-indigo-500/40 text-indigo-200';

  toast.className = 'pointer-events-auto flex items-center gap-2.5 px-4 py-3 rounded-lg border shadow-xl text-sm font-medium transition-all duration-300 transform translate-y-2 opacity-0 ' + borderBg;

  // Safe SVG icon construction
  const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  iconSvg.setAttribute('viewBox', '0 0 24 24');
  iconSvg.setAttribute('fill', 'none');
  iconSvg.setAttribute('stroke', 'currentColor');

  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  path.setAttribute('stroke-width', '2');

  if (type === 'success') {
    iconSvg.setAttribute('class', 'w-4 h-4 text-emerald-400 shrink-0');
    path.setAttribute('d', 'M5 13l4 4L19 7');
  } else if (type === 'error') {
    iconSvg.setAttribute('class', 'w-4 h-4 text-red-400 shrink-0');
    path.setAttribute('d', 'M6 18L18 6M6 6l12 12');
  } else {
    iconSvg.setAttribute('class', 'w-4 h-4 text-indigo-400 shrink-0');
    path.setAttribute('d', 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z');
  }
  iconSvg.appendChild(path);
  toast.appendChild(iconSvg);

  const span = document.createElement('span');
  span.textContent = message !== null && message !== undefined ? String(message) : '';
  toast.appendChild(span);

  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.classList.remove('translate-y-2', 'opacity-0');
  });

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
