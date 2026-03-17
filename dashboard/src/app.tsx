/**
 * App — 5 pages
 * 首页 / 我的数据 / 探索 / 自动化 / 网络
 */
import { useEffect, useState } from 'preact/hooks';
import { initUI } from './store/ui';
import Nav from './components/nav';
import ToastContainer from './components/toast';
import Home from './pages/home';
import MyData from './pages/mydata';
import Explore from './pages/explore';
import Network from './pages/network';
import Automation from './pages/automation';

export type Page = 'home' | 'mydata' | 'explore' | 'auto' | 'network';

export default function App() {
  const [page, setPage] = useState<Page>('home');

  useEffect(() => {
    initUI();
    const onPop = () => {
      const p = location.pathname.slice(1) || 'home';
      if (['home', 'mydata', 'explore', 'auto', 'network'].includes(p)) setPage(p as Page);
    };
    onPop();
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const go = (p: Page) => {
    setPage(p);
    history.pushState(null, '', p === 'home' ? '/' : '/' + p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    // Move focus to main content for screen readers
    requestAnimationFrame(() => {
      const main = document.getElementById('main-content');
      if (main) { main.focus({ preventScroll: true }); }
    });
  };

  return (
    <div class="app">
      <a href="#main-content" class="skip-link">Skip to content</a>
      <Nav current={page} go={go} />
      <main class="main" id="main-content" tabIndex={-1} style="outline:none">
        {page === 'home' && <Home go={go} />}
        {page === 'mydata' && <MyData />}
        {page === 'explore' && <Explore />}
        {page === 'network' && <Network />}
        {page === 'auto' && <Automation />}
      </main>
      <ToastContainer />
    </div>
  );
}
