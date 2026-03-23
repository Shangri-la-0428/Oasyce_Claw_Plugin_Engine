/**
 * useRoute — hash-based routing with deep link support
 *
 * URL format: #page/subpath (e.g. #explore/CAP_ABC123, #network/consensus)
 * Backward compatible: #home, #explore still work (subpath = '')
 */
import { useEffect, useState, useCallback } from 'preact/hooks';

export type Page = 'home' | 'mydata' | 'explore' | 'auto' | 'network';

const VALID_PAGES: Page[] = ['home', 'mydata', 'explore', 'auto', 'network'];

function parseHash(): { page: Page; subpath: string } {
  const raw = location.hash.slice(1); // remove '#'
  if (!raw) return { page: 'home', subpath: '' };
  const parts = raw.split('/');
  const first = parts[0] || 'home';
  const page = VALID_PAGES.includes(first as Page) ? (first as Page) : 'home';
  const subpath = parts.slice(1).join('/');
  return { page, subpath };
}

export function useRoute() {
  const [route, setRoute] = useState(parseHash);

  useEffect(() => {
    const onHashChange = () => {
      setRoute(parseHash());
    };
    window.addEventListener('hashchange', onHashChange);
    // Also handle initial load
    onHashChange();
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const go = useCallback((page: Page, subpath?: string) => {
    const hash = subpath ? `${page}/${subpath}` : page;
    const apply = () => { location.hash = hash === 'home' ? '' : hash; };
    const focusMain = () => {
      const el = document.getElementById('main-content');
      if (el) el.focus({ preventScroll: true });
    };

    if ('startViewTransition' in document) {
      window.scrollTo({ top: 0 });
      (document as any).startViewTransition(() => {
        apply();
        return new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      }).finished.then(focusMain);
    } else {
      apply();
      window.scrollTo({ top: 0, behavior: 'smooth' });
      requestAnimationFrame(focusMain);
    }
  }, []);

  return { page: route.page, subpath: route.subpath, go };
}
