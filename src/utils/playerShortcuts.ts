export interface ShortcutEventLike {
  key: string;
  code?: string;
  defaultPrevented?: boolean;
  target?: EventTarget | null;
}

const INTERACTIVE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT', 'OPTION']);

/**
 * Determina se um atalho global do player deve ser ignorado para não interferir
 * com campos interativos, diálogos/modais ou eventos já tratados por outros componentes.
 */
export function shouldIgnorePlayerShortcut(
  e: ShortcutEventLike,
  hasOpenModal?: boolean
): boolean {
  if (e.defaultPrevented) {
    return true;
  }

  const target = e.target as (HTMLElement | null);
  if (target) {
    const tag = (target.tagName || '').toUpperCase();
    if (INTERACTIVE_TAGS.has(tag) || target.isContentEditable) {
      return true;
    }
    if (
      typeof target.closest === 'function' &&
      target.closest(
        'input, textarea, select, option, [contenteditable="true"], [role="dialog"], [aria-modal="true"], dialog'
      )
    ) {
      return true;
    }
  }

  if (e.key === 'Escape') {
    if (hasOpenModal) {
      return true;
    }
    if (
      typeof document !== 'undefined' &&
      document.querySelector('[role="dialog"], [aria-modal="true"], dialog[open]')
    ) {
      return true;
    }
  }

  return false;
}
