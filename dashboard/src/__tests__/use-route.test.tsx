import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';
import { useRoute, type Page } from '../hooks/use-route';

// ---------------------------------------------------------------------------
// Test harness — renders a dummy component that captures the hook's return
// ---------------------------------------------------------------------------

let captured: { page: Page; subpath: string; go: (page: Page, subpath?: string) => void };

function Harness() {
  const route = useRoute();
  captured = route;
  return null;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useRoute', () => {
  let container: HTMLElement | null = null;

  function mount() {
    const el = document.createElement('div');
    document.body.appendChild(el);
    container = el;
    act(() => { render(<Harness />, el); });
    return el;
  }

  beforeEach(() => {
    // Reset hash to empty before each test
    location.hash = '';
    // Stub scrollTo so go() doesn't throw
    vi.stubGlobal('scrollTo', vi.fn());
  });

  afterEach(() => {
    if (container) {
      act(() => { render(null, container!); });
      container.remove();
      container = null;
    }
    vi.restoreAllMocks();
  });

  // ── parseHash mapping (tested indirectly via initial hook state) ───────

  describe('hash parsing', () => {
    it('empty hash defaults to home with empty subpath', () => {
      location.hash = '';
      mount();
      expect(captured.page).toBe('home');
      expect(captured.subpath).toBe('');
    });

    it('#home -> page home', () => {
      location.hash = '#home';
      mount();
      expect(captured.page).toBe('home');
      expect(captured.subpath).toBe('');
    });

    it('#explore -> page explore', () => {
      location.hash = '#explore';
      mount();
      expect(captured.page).toBe('explore');
      expect(captured.subpath).toBe('');
    });

    it('#mydata -> page mydata', () => {
      location.hash = '#mydata';
      mount();
      expect(captured.page).toBe('mydata');
      expect(captured.subpath).toBe('');
    });

    it('#auto -> page auto', () => {
      location.hash = '#auto';
      mount();
      expect(captured.page).toBe('auto');
      expect(captured.subpath).toBe('');
    });

    it('#network -> page network', () => {
      location.hash = '#network';
      mount();
      expect(captured.page).toBe('network');
      expect(captured.subpath).toBe('');
    });

    it('#explore/CAP_ABC -> page explore, subpath CAP_ABC', () => {
      location.hash = '#explore/CAP_ABC';
      mount();
      expect(captured.page).toBe('explore');
      expect(captured.subpath).toBe('CAP_ABC');
    });

    it('#network/consensus -> page network, subpath consensus', () => {
      location.hash = '#network/consensus';
      mount();
      expect(captured.page).toBe('network');
      expect(captured.subpath).toBe('consensus');
    });

    it('#explore/deep/path -> subpath preserves slashes', () => {
      location.hash = '#explore/deep/path';
      mount();
      expect(captured.page).toBe('explore');
      expect(captured.subpath).toBe('deep/path');
    });

    it('invalid page falls back to home', () => {
      location.hash = '#invalid';
      mount();
      expect(captured.page).toBe('home');
      expect(captured.subpath).toBe('');
    });

    it('invalid page with subpath falls back to home, keeps subpath', () => {
      location.hash = '#badpage/some/sub';
      mount();
      expect(captured.page).toBe('home');
      expect(captured.subpath).toBe('some/sub');
    });
  });

  // ── go() side effects ─────────────────────────────────────────────────

  describe('go()', () => {
    it('sets location.hash for non-home pages', () => {
      location.hash = '';
      mount();

      act(() => { captured.go('explore'); });
      expect(location.hash).toBe('#explore');
    });

    it('sets location.hash with subpath', () => {
      location.hash = '';
      mount();

      act(() => { captured.go('explore', 'CAP_123'); });
      expect(location.hash).toBe('#explore/CAP_123');
    });

    it('clears hash when navigating to home', () => {
      location.hash = '#explore';
      mount();

      act(() => { captured.go('home'); });
      // home sets hash to '' which means location.hash is '' or '#'
      expect(location.hash === '' || location.hash === '#').toBe(true);
    });

    it('calls window.scrollTo({ top: 0 })', () => {
      location.hash = '';
      mount();

      act(() => { captured.go('network'); });
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 0 });
    });

    it('sets hash for network with subpath', () => {
      location.hash = '';
      mount();

      act(() => { captured.go('network', 'consensus'); });
      expect(location.hash).toBe('#network/consensus');
    });
  });

  // ── hashchange event listener ─────────────────────────────────────────

  describe('hashchange listener', () => {
    it('updates page when hash changes externally', () => {
      location.hash = '';
      mount();
      expect(captured.page).toBe('home');

      // Simulate external hash change
      act(() => {
        location.hash = '#mydata';
        window.dispatchEvent(new HashChangeEvent('hashchange'));
      });
      expect(captured.page).toBe('mydata');
    });

    it('updates subpath when hash changes externally', () => {
      location.hash = '';
      mount();

      act(() => {
        location.hash = '#explore/ASSET_XYZ';
        window.dispatchEvent(new HashChangeEvent('hashchange'));
      });
      expect(captured.page).toBe('explore');
      expect(captured.subpath).toBe('ASSET_XYZ');
    });
  });

  // ── Page ordering / direction ─────────────────────────────────────────

  describe('page ordering', () => {
    it('navigates through all valid pages in sequence', () => {
      location.hash = '';
      mount();

      const pages: Page[] = ['home', 'mydata', 'explore', 'auto', 'network'];
      for (const p of pages) {
        act(() => { captured.go(p); });
        if (p === 'home') {
          expect(location.hash === '' || location.hash === '#').toBe(true);
        } else {
          expect(location.hash).toBe(`#${p}`);
        }
      }
    });

    it('navigates backward through pages', () => {
      location.hash = '#network';
      mount();

      const backward: Page[] = ['auto', 'explore', 'mydata', 'home'];
      for (const p of backward) {
        act(() => { captured.go(p); });
        if (p === 'home') {
          expect(location.hash === '' || location.hash === '#').toBe(true);
        } else {
          expect(location.hash).toBe(`#${p}`);
        }
      }
    });
  });
});
