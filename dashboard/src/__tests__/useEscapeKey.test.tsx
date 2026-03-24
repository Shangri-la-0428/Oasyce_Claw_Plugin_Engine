import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';
import { useEscapeKey } from '../hooks/useEscapeKey';

// ---------------------------------------------------------------------------
// Test harness
// ---------------------------------------------------------------------------

function Harness({ handler, enabled }: { handler: () => void; enabled?: boolean }) {
  useEscapeKey(handler, enabled);
  return null;
}

function pressKey(key: string) {
  document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useEscapeKey', () => {
  let container: HTMLElement | null = null;

  function mountInto(handler: () => void, enabled?: boolean) {
    const el = document.createElement('div');
    document.body.appendChild(el);
    container = el;
    act(() => { render(<Harness handler={handler} enabled={enabled} />, el); });
    return el;
  }

  afterEach(() => {
    if (container) {
      act(() => { render(null, container!); });
      container.remove();
      container = null;
    }
  });

  it('calls handler when Escape is pressed', () => {
    const handler = vi.fn();
    mountInto(handler);

    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('calls handler on each Escape press', () => {
    const handler = vi.fn();
    mountInto(handler);

    pressKey('Escape');
    pressKey('Escape');
    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(3);
  });

  it('does NOT call handler for Enter key', () => {
    const handler = vi.fn();
    mountInto(handler);

    pressKey('Enter');
    expect(handler).not.toHaveBeenCalled();
  });

  it('does NOT call handler for Tab key', () => {
    const handler = vi.fn();
    mountInto(handler);

    pressKey('Tab');
    expect(handler).not.toHaveBeenCalled();
  });

  it('does NOT call handler for letter keys', () => {
    const handler = vi.fn();
    mountInto(handler);

    pressKey('a');
    pressKey('z');
    pressKey('Backspace');
    pressKey('ArrowDown');
    expect(handler).not.toHaveBeenCalled();
  });

  it('does NOT call handler when enabled=false', () => {
    const handler = vi.fn();
    mountInto(handler, false);

    pressKey('Escape');
    expect(handler).not.toHaveBeenCalled();
  });

  it('enabled defaults to true', () => {
    const handler = vi.fn();
    mountInto(handler);

    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('removes event listener on unmount', () => {
    const handler = vi.fn();
    mountInto(handler);

    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1);

    // Unmount
    act(() => { render(null, container!); });
    container!.remove();
    container = null;

    // Should NOT fire after unmount
    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1); // still 1, not 2
  });

  it('re-attaches listener when enabled changes from false to true', () => {
    const handler = vi.fn();
    const el = document.createElement('div');
    document.body.appendChild(el);
    container = el;

    // Initially disabled
    act(() => { render(<Harness handler={handler} enabled={false} />, el); });

    pressKey('Escape');
    expect(handler).not.toHaveBeenCalled();

    // Now enable
    act(() => { render(<Harness handler={handler} enabled={true} />, el); });

    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('detaches listener when enabled changes from true to false', () => {
    const handler = vi.fn();
    const el = document.createElement('div');
    document.body.appendChild(el);
    container = el;

    // Initially enabled
    act(() => { render(<Harness handler={handler} enabled={true} />, el); });

    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1);

    // Now disable
    act(() => { render(<Harness handler={handler} enabled={false} />, el); });

    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1); // still 1
  });

  it('responds only to Escape, not Esc (older browsers)', () => {
    const handler = vi.fn();
    mountInto(handler);

    // 'Esc' is the old IE key value; modern browsers use 'Escape'
    pressKey('Esc');
    expect(handler).not.toHaveBeenCalled();

    pressKey('Escape');
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('updates handler reference without leaking listeners', () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();
    const el = document.createElement('div');
    document.body.appendChild(el);
    container = el;

    // Mount with handler1
    act(() => { render(<Harness handler={handler1} enabled={true} />, el); });

    pressKey('Escape');
    expect(handler1).toHaveBeenCalledTimes(1);
    expect(handler2).not.toHaveBeenCalled();

    // Swap to handler2
    act(() => { render(<Harness handler={handler2} enabled={true} />, el); });

    pressKey('Escape');
    // handler1 should not get called again (old listener removed)
    expect(handler1).toHaveBeenCalledTimes(1);
    expect(handler2).toHaveBeenCalledTimes(1);
  });
});
