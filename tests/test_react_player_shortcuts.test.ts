import { describe, expect, it } from 'bun:test';
import { shouldIgnorePlayerShortcut } from '../src/utils/playerShortcuts';

describe('shouldIgnorePlayerShortcut', () => {
  it('ignora quando o evento já foi tratado (defaultPrevented)', () => {
    expect(
      shouldIgnorePlayerShortcut({ key: ' ', code: 'Space', defaultPrevented: true })
    ).toBe(true);
  });

  it('ignora campos interativos: INPUT, TEXTAREA, SELECT, OPTION e contentEditable', () => {
    for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT', 'OPTION']) {
      expect(
        shouldIgnorePlayerShortcut({
          key: ' ',
          code: 'Space',
          target: { tagName, isContentEditable: false } as unknown as EventTarget,
        })
      ).toBe(true);
    }

    expect(
      shouldIgnorePlayerShortcut({
        key: 'm',
        target: { tagName: 'DIV', isContentEditable: true } as unknown as EventTarget,
      })
    ).toBe(true);
  });

  it('ignora eventos originados dentro de diálogos ou modais', () => {
    const insideDialog = {
      tagName: 'BUTTON',
      isContentEditable: false,
      closest: (sel: string) => (sel.includes('[role="dialog"]') ? ({} as Element) : null),
    } as unknown as EventTarget;

    expect(
      shouldIgnorePlayerShortcut({ key: 'Escape', target: insideDialog })
    ).toBe(true);
  });

  it('ignora Escape quando há modal aberto na interface', () => {
    expect(
      shouldIgnorePlayerShortcut({ key: 'Escape', target: null }, true)
    ).toBe(true);
  });

  it('permite atalhos do player quando foco está em área neutra e sem modal', () => {
    const neutralTarget = {
      tagName: 'DIV',
      isContentEditable: false,
      closest: () => null,
    } as unknown as EventTarget;

    expect(
      shouldIgnorePlayerShortcut({ key: ' ', code: 'Space', target: neutralTarget }, false)
    ).toBe(false);
    expect(
      shouldIgnorePlayerShortcut({ key: 'Escape', target: neutralTarget }, false)
    ).toBe(false);
  });
});
