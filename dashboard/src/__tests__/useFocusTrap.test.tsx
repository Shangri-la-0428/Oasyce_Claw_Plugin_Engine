import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'preact';
import { useState } from 'preact/hooks';
import { act } from 'preact/test-utils';
import { useFocusTrap } from '../hooks/useFocusTrap';

// ---------------------------------------------------------------------------
// Test harnesses
// ---------------------------------------------------------------------------

function TrapWrapper({ active }: { active: boolean }) {
  const ref = useFocusTrap(active);
  return (
    <div ref={ref as any} data-testid="trap">
      <button data-testid="btn-a">A</button>
      <input data-testid="input-b" />
      <button data-testid="btn-c">C</button>
    </div>
  );
}

function ToggleTrap() {
  const [active, setActive] = useState(false);
  const ref = useFocusTrap(active);
  return (
    <div>
      <button data-testid="trigger" onClick={() => setActive(true)}>Open</button>
      {active && (
        <div ref={ref as any} data-testid="trap">
          <button data-testid="btn-x">X</button>
          <button data-testid="btn-y" onClick={() => setActive(false)}>Close</button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useFocusTrap', () => {
  let root: HTMLDivElement;

  beforeEach(() => {
    root = document.createElement('div');
    document.body.appendChild(root);
  });

  afterEach(() => {
    render(null, root);
    root.remove();
  });

  it('returns a ref object', () => {
    let trapRef: any;
    function Probe() {
      trapRef = useFocusTrap(false);
      return <div ref={trapRef as any} />;
    }
    act(() => { render(<Probe />, root); });
    expect(trapRef).toBeDefined();
    expect(trapRef.current).toBeInstanceOf(HTMLElement);
  });

  it('does nothing when active is false', () => {
    const outside = document.createElement('button');
    document.body.appendChild(outside);
    outside.focus();

    act(() => { render(<TrapWrapper active={false} />, root); });
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });

  it('traps Tab at last element — wraps to first', () => {
    act(() => { render(<TrapWrapper active={true} />, root); });

    const btnA = root.querySelector('[data-testid="btn-a"]') as HTMLElement;
    const btnC = root.querySelector('[data-testid="btn-c"]') as HTMLElement;
    btnC.focus();
    expect(document.activeElement).toBe(btnC);

    // Press Tab on last element
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true });
    const spy = vi.spyOn(event, 'preventDefault');
    document.dispatchEvent(event);

    // Focus should wrap to first
    expect(spy).toHaveBeenCalled();
    expect(document.activeElement).toBe(btnA);
  });

  it('traps Shift+Tab at first element — wraps to last', () => {
    act(() => { render(<TrapWrapper active={true} />, root); });

    const btnA = root.querySelector('[data-testid="btn-a"]') as HTMLElement;
    const btnC = root.querySelector('[data-testid="btn-c"]') as HTMLElement;
    btnA.focus();

    const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true });
    const spy = vi.spyOn(event, 'preventDefault');
    document.dispatchEvent(event);

    expect(spy).toHaveBeenCalled();
    expect(document.activeElement).toBe(btnC);
  });

  it('ignores non-Tab keys', () => {
    act(() => { render(<TrapWrapper active={true} />, root); });

    const btnA = root.querySelector('[data-testid="btn-a"]') as HTMLElement;
    btnA.focus();

    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
    const spy = vi.spyOn(event, 'preventDefault');
    document.dispatchEvent(event);

    expect(spy).not.toHaveBeenCalled();
  });

  it('cleans up keydown listener on unmount', () => {
    act(() => { render(<TrapWrapper active={true} />, root); });

    const removeSpy = vi.spyOn(document, 'removeEventListener');
    act(() => { render(null, root); });
    expect(removeSpy.mock.calls.some(c => c[0] === 'keydown')).toBe(true);
    removeSpy.mockRestore();
  });
});
