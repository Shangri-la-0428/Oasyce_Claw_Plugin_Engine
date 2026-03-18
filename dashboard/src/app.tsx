/**
 * App — 5 pages
 * 首页 / 我的数据 / 探索 / 自动化 / 网络
 */
import { useEffect } from 'preact/hooks';
import { initUI } from './store/ui';
import Nav from './components/nav';
import ToastContainer from './components/toast';
import Home from './pages/home';
import MyData from './pages/mydata';
import Explore from './pages/explore';
import Network from './pages/network';
import Automation from './pages/automation';
import { useRoute } from './hooks/use-route';

export type { Page } from './hooks/use-route';

export default function App() {
  const { page, subpath, go } = useRoute();

  useEffect(() => {
    initUI();
  }, []);

  return (
    <div class="app">
      <a href="#main-content" class="skip-link">Skip to content</a>
      <Nav current={page} go={go} />
      <main class="main no-outline" id="main-content" tabIndex={-1}>
        {page === 'home' && <Home go={go} />}
        {page === 'mydata' && <MyData />}
        {page === 'explore' && <Explore subpath={subpath} />}
        {page === 'network' && <Network subpath={subpath} />}
        {page === 'auto' && <Automation />}
      </main>
      <ToastContainer />
    </div>
  );
}
