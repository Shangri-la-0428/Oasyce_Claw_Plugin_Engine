/**
 * useRoute — hash-based routing with deep link support
 *
 * URL format: #page/subpath (e.g. #explore/CAP_ABC123, #network/consensus)
 * Backward compatible: #home, #explore still work (subpath = '')
 *
 * Features:
 * - Direction-aware View Transitions (forward/backward based on tab index)
 * - Graceful fallback — apply() always runs first, transition is visual-only
 */
import { useEffect, useState, useCallback, useRef } from 'preact/hooks';

export type Page = 'home' | 'mydata' | 'explore' | 'auto' | 'network';

const VALID_PAGES: Page[] = ['home', 'mydata', 'explore', 'auto', 'network'];
const PAGE_INDEX: Record<Page, number> = { home: 0, mydata: 1, explore: 2, auto: 3, network: 4 };

function parseHash(): { page: Page; subpath: string } {
  const raw = location.hash.slice(1);
  if (!raw) return { page: 'home', subpath: '' };
  const parts = raw.split('/');
  const first = parts[0] || 'home';
  const page = VALID_PAGES.includes(first as Page) ? (first as Page) : 'home';
  const subpath = parts.slice(1).join('/');
  return { page, subpath };
}

/** Can we use View Transitions safely? */
const canTransition = typeof document !== 'undefined'
  && 'startViewTransition' in document
  && !matchMedia('(prefers-reduced-motion: reduce)').matches;

export function useRoute() {
  const [route, setRoute] = useState(parseHash);
  const prevPageRef = useRef<Page>(route.page);

  useEffect(() => {
    const onHashChange = () => { setRoute(parseHash()); };
    window.addEventListener('hashchange', onHashChange);
    onHashChange();
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const go = useCallback((page: Page, subpath?: string) => {
    const hash = subpath ? `${page}/${subpath}` : page;
    const prev = prevPageRef.current;
    const direction = PAGE_INDEX[page] >= PAGE_INDEX[prev] ? 'forward' : 'backward';
    prevPageRef.current = page;

    const apply = () => { location.hash = hash === 'home' ? '' : hash; };
    const focusMain = () => {
      const el = document.getElementById('main-content');
      if (el) el.focus({ preventScroll: true });
    };

    // Always apply immediately — navigation must never be blocked
    apply();
    window.scrollTo({ top: 0 });

    // Layer View Transition on top (visual-only, non-blocking)
    if (canTransition && prev !== page) {
      document.documentElement.dataset.navDirection = direction;
      try {
        (document as any).startViewTransition(() => {
          // DOM already updated by apply() — just return resolved promise
          return Promise.resolve();
        }).finished.then(() => {
          delete document.documentElement.dataset.navDirection;
          focusMain();
        }).catch(() => {
          delete document.documentElement.dataset.navDirection;
        });
      } catch {
        delete document.documentElement.dataset.navDirection;
        requestAnimationFrame(focusMain);
      }
    } else {
      requestAnimationFrame(focusMain);
    }
  }, []);

  return { page: route.page, subpath: route.subpath, go };
}
