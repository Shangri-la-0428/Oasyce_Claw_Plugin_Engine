/**
 * App — 5 pages
 * 首页 / 我的数据 / 探索 / 自动化 / 网络
 */
import { useEffect } from 'preact/hooks';
import { lazy, Suspense } from 'preact/compat';
import { initUI, i18n, lang } from './store/ui';
import Nav from './components/nav';
import ToastContainer from './components/toast';
import ErrorBoundary from './components/error-boundary';
import { useRoute } from './hooks/use-route';

const Home = lazy(() => import('./pages/home'));
const MyData = lazy(() => import('./pages/mydata'));
const Explore = lazy(() => import('./pages/explore'));
const Network = lazy(() => import('./pages/network'));
const Automation = lazy(() => import('./pages/automation'));

function SkipLink() {
  return <a href="#main-content" class="skip-link">{i18n.value['skip-to-content']}</a>;
}

export type { Page } from './hooks/use-route';

export default function App() {
  const { page, subpath, go } = useRoute();

  useEffect(() => {
    initUI();
  }, []);

  // H4: Sync HTML lang attribute with language signal
  useEffect(() => {
    document.documentElement.lang = lang.value === 'zh' ? 'zh-CN' : 'en';
  }, [lang.value]);

  return (
    <div class="app app-shell">
      <div class="app-backdrop" aria-hidden="true">
        <div class="app-backdrop-grid" />
        <div class="app-backdrop-orb app-backdrop-orb-a" />
        <div class="app-backdrop-orb app-backdrop-orb-b" />
      </div>
      <SkipLink />
      <div class="app-frame">
        <Nav current={page} go={go} />
        <main class="main no-outline" id="main-content" tabIndex={-1}>
          <ErrorBoundary>
            <Suspense fallback={<div class="skeleton skeleton-lg" />}>
              {page === 'home' && <Home go={go} />}
              {page === 'mydata' && <MyData />}
              {page === 'explore' && <Explore subpath={subpath} />}
              {page === 'network' && <Network subpath={subpath} />}
              {page === 'auto' && <Automation />}
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
      <ToastContainer />
    </div>
  );
}
