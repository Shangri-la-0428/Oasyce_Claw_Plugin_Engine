/**
 * App — 4 个核心页面
 * 首页（引导 + 注册）/ 我的数据 / 探索 / 网络
 */
import { useEffect, useState } from 'preact/hooks';
import { initUI } from './store/ui';
import Nav from './components/nav';
import ToastContainer from './components/toast';
import Home from './pages/home';
import MyData from './pages/mydata';
import Explore from './pages/explore';
import Network from './pages/network';

export type Page = 'home' | 'mydata' | 'explore' | 'network';

export default function App() {
  const [page, setPage] = useState<Page>('home');

  useEffect(() => {
    initUI();
    const onPop = () => {
      const p = location.pathname.slice(1) || 'home';
      if (['home', 'mydata', 'explore', 'network'].includes(p)) setPage(p as Page);
    };
    onPop();
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const go = (p: Page) => {
    setPage(p);
    history.pushState(null, '', p === 'home' ? '/' : '/' + p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div class="app">
      <Nav current={page} go={go} />
      <main class="main">
        {page === 'home' && <Home go={go} />}
        {page === 'mydata' && <MyData />}
        {page === 'explore' && <Explore />}
        {page === 'network' && <Network />}
      </main>
      <ToastContainer />
    </div>
  );
}
