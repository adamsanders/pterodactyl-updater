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

  header.onmousedown = (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    if (e.target.tagName === 'BUTTON' || e.target.closest('button') || e.target.tagName === 'INPUT') return;
    e.preventDefault();
    const rect = el.getBoundingClientRect();
    const startX = e.clientX;
    const startY = e.clientY;
    const initialLeft = rect.left;
    const initialTop = rect.top;

    const onMouseMove = (ev) => {
      ev.preventDefault();
      const deltaX = ev.clientX - startX;
      const deltaY = ev.clientY - startY;

      let newTop = initialTop + deltaY;
      let newLeft = initialLeft + deltaX;

      const viewportWidth = window.innerWidth || document.documentElement?.clientWidth || 1000;
      const viewportHeight = window.innerHeight || document.documentElement?.clientHeight || 800;
      const maxLeft = Math.max(0, viewportWidth - (rect.width || 470));
      const maxTop = Math.max(0, viewportHeight - 40);

      newLeft = Math.max(0, Math.min(newLeft, maxLeft));
      newTop = Math.max(0, Math.min(newTop, maxTop));

      el.style.top = `${newTop}px`;
      el.style.left = `${newLeft}px`;
      el.style.right = 'auto';
      el.style.bottom = 'auto';
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
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
  let isDragging = false;
  let isHandleGrabbed = false;

  cards.forEach(card => {
    if (!card) return;
    card.classList.add('transition-transform');

    const handle = card.querySelector('.server-drag-handle');
    if (handle) {
      handle.addEventListener('mouseenter', () => {
        card.setAttribute('draggable', 'true');
      });

      handle.addEventListener('mouseleave', () => {
        if (!isDragging && !isHandleGrabbed) {
          card.removeAttribute('draggable');
        }
      });

      handle.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        isHandleGrabbed = true;
        card.setAttribute('draggable', 'true');
      });
    } else {
      // Fallback if no dedicated handle exists
      card.setAttribute('draggable', 'true');
    }

    card.addEventListener('dragstart', (e) => {
      // Don't drag if user is typing in an input, interacting with a slider, label, button, or link
      if (
        ['INPUT', 'BUTTON', 'A', 'SELECT', 'TEXTAREA', 'LABEL'].includes(e.target.tagName) ||
        e.target.closest('button, label, input, select, textarea, a')
      ) {
        e.preventDefault();
        card.removeAttribute('draggable');
        return;
      }

      // If a drag handle anchor exists, only allow reordering drags initiated from the handle
      const fromHandle = handle && (e.target === handle || handle.contains(e.target));
      if (handle && !isHandleGrabbed && !fromHandle) {
        card.removeAttribute('draggable');
        return;
      }

      isDragging = true;
      draggedCard = card;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', '');

      setTimeout(() => {
        if (draggedCard === card) {
          card.classList.add('opacity-40', 'border-indigo-500/60', 'scale-[0.99]');
        }
      }, 0);
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
      card.removeAttribute('draggable');
      isDragging = false;
      isHandleGrabbed = false;
      draggedCard = null;
      reindexServerCards(container);
    });
  });

  window.addEventListener('pointerup', () => {
    isHandleGrabbed = false;
    if (!isDragging) {
      cards.forEach(c => {
        if (c && c.querySelector('.server-drag-handle') && c.getAttribute('draggable') === 'true') {
          c.removeAttribute('draggable');
        }
      });
    }
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
