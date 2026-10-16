/**
 * Drag and drop utilities for interactive modal windows and server card reordering.
 */

/**
 * Makes a floating window element draggable by its header element.
 *
 * @param {string} elId - ID of the container element to move.
 * @param {string} headerId - ID of the header handle element.
 */
export function makeDraggable(elId, headerId) {
  const el = document.getElementById(elId);
  const header = document.getElementById(headerId);
  if (!el || !header) return;

  let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
  header.onmousedown = (e) => {
    if (e.target.tagName === 'BUTTON' || e.target.closest('button') || e.target.tagName === 'INPUT') return;
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

/**
 * Initializes HTML5 Drag and Drop reordering for server cards on the dashboard.
 *
 * @param {string} [containerSelector='#main-form > div'] - Selector for the server list wrapper.
 * @param {string} [cardSelector='[id^="srv_title_"]'] - Selector identifying server card headers.
 */
export function initServerDragAndDrop(containerSelector = '#main-form > div', cardSelector = '[id^="srv_title_"]') {
  const titles = document.querySelectorAll(cardSelector);
  if (!titles.length) return;

  // Each card is the parent container of the header
  const cards = Array.from(titles).map(t => t.closest('.rounded-lg') || t.parentElement.parentElement);
  const container = cards[0]?.parentElement;
  if (!container) return;

  let draggedCard = null;

  cards.forEach(card => {
    if (!card) return;
    card.setAttribute('draggable', 'true');
    card.classList.add('transition-transform');

    card.addEventListener('dragstart', (e) => {
      // Don't drag if user is typing in an input, interacting with a slider, label, button, or link
      if (
        ['INPUT', 'BUTTON', 'A', 'SELECT', 'TEXTAREA', 'LABEL'].includes(e.target.tagName) ||
        e.target.closest('button, label, input, select, textarea, a')
      ) {
        e.preventDefault();
        return;
      }
      draggedCard = card;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', '');
      card.classList.add('opacity-40', 'border-indigo-500/60', 'scale-[0.99]');
    });

    card.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (!draggedCard || draggedCard === card) return;

      const rect = card.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      if (e.clientY < midY) {
        container.insertBefore(draggedCard, card);
      } else {
        container.insertBefore(draggedCard, card.nextSibling);
      }
    });

    card.addEventListener('dragend', () => {
      card.classList.remove('opacity-40', 'border-indigo-500/60', 'scale-[0.99]');
      draggedCard = null;
      reindexServerCards(container);
    });
  });
}

/**
 * Re-indexes visible server numbers and indices after a drag-and-drop reorder.
 *
 * @param {HTMLElement} container - The container element holding server cards.
 */
export function reindexServerCards(container) {
  const titles = container.querySelectorAll('[id^="srv_title_"]');
  titles.forEach((titleEl, newIdx) => {
    const rawText = titleEl.textContent || '';
    const match = rawText.match(/Server #\d+:\s*(.*)/);
    const serverName = match ? match[1] : rawText.replace(/^Server #\d+:?\s*/, '');
    titleEl.textContent = `Server #${newIdx + 1}: ${serverName}`;
  });
}
