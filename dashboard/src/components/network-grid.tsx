/**
 * NetworkGrid — breathing dot matrix with network semantics
 *
 * Base layer: regular grid of tiny dots with a slow diagonal breathing wave.
 * Active nodes: some dots are "alive" — slightly larger, brighter, with lifecycle.
 * Broadcasts: clean expanding stroke rings from active nodes.
 * Connections: subtle lines between nearby active nodes.
 * Interaction: cursor glow + click-to-broadcast.
 */
import { useRef, useEffect } from 'preact/hooks';
import './network-grid.css';

const HEIGHT = 160;
const SPACE = 36;           // CSS px between dots
const MAX_NODES = 16;
const MAX_RINGS = 8;
const SPAWN_INTERVAL = 4000;
const RING_INTERVAL = 5000;
const FADE_AFTER = 12000;

interface ActiveNode {
  col: number; row: number;  // grid indices
  born: number;
  energy: number;            // 0..1 visual intensity
  targetEnergy: number;
  fading: boolean;
}

interface Ring {
  cx: number; cy: number;
  radius: number;
  maxRadius: number;
  alpha: number;
  startTime: number;
}

function isDark(): boolean {
  return document.documentElement.dataset.theme !== 'light';
}

export default function NetworkGrid() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef(0);
  const pendingClick = useRef<{ x: number; y: number } | null>(null);
  const cursorRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const prefersStill = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let visible = true;
    let imgW = 0, imgH = 0;

    // Theme colors — cached, refreshed on theme change
    let dark = isDark();
    let bgR = 0, bgG = 0, bgB = 0;
    function refreshColors() {
      dark = isDark();
      const s = getComputedStyle(document.documentElement);
      const hex = s.getPropertyValue('--bg-0').trim();
      bgR = parseInt(hex.slice(1, 3), 16) || (dark ? 10 : 250);
      bgG = parseInt(hex.slice(3, 5), 16) || (dark ? 10 : 249);
      bgB = parseInt(hex.slice(5, 7), 16) || (dark ? 10 : 246);
    }
    refreshColors();
    const themeObs = new MutationObserver(refreshColors);
    themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    // Grid state
    let dots: Array<{ x: number; y: number }> = [];
    let cols = 0, rows = 0;
    const activeNodes: ActiveNode[] = [];
    const rings: Ring[] = [];
    let lastSpawn = 0, lastRing = 0;

    function init() {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const w = canvas!.parentElement?.clientWidth ?? canvas!.clientWidth;
      imgW = Math.max(1, Math.floor(w * dpr));
      imgH = Math.max(1, Math.floor(HEIGHT * dpr));
      canvas!.width = imgW;
      canvas!.height = imgH;
      canvas!.style.width = `${w}px`;
      canvas!.style.height = `${HEIGHT}px`;

      dots = [];
      const sp = SPACE * dpr;
      cols = Math.ceil(imgW / sp);
      rows = Math.ceil(imgH / sp);
      const ox = (imgW - (cols - 1) * sp) / 2;
      const oy = (imgH - (rows - 1) * sp) / 2;
      for (let r = 0; r < rows; r++)
        for (let c = 0; c < cols; c++)
          dots.push({ x: ox + c * sp, y: oy + r * sp });

      activeNodes.length = 0;
      rings.length = 0;
      const now = performance.now();
      // Seed some active nodes
      const initial = 6 + Math.floor(Math.random() * 4);
      for (let i = 0; i < initial; i++) trySpawn(now);
      lastSpawn = lastRing = now;
    }

    function trySpawn(now: number) {
      if (activeNodes.length >= MAX_NODES) return;
      let tries = 0, c: number, r: number;
      do {
        c = Math.floor(Math.random() * cols);
        r = Math.floor(Math.random() * rows);
        const conflict = activeNodes.some(n => n.col === c && n.row === r);
        if (!conflict) break;
        tries++;
      } while (tries < 30);
      if (tries >= 30) return;
      activeNodes.push({
        col: c, row: r, born: now,
        energy: 0, targetEnergy: 0.4 + Math.random() * 0.3,
        fading: false,
      });
    }

    function emitRing(dotIdx: number) {
      if (rings.length >= MAX_RINGS) return;
      const d = dots[dotIdx];
      if (!d) return;
      rings.push({
        cx: d.x, cy: d.y, radius: 0,
        maxRadius: Math.max(imgW, imgH) * (0.2 + Math.random() * 0.15),
        alpha: dark ? 0.2 : 0.14,
        startTime: performance.now(),
      });
    }

    function dotIndex(col: number, row: number): number {
      return row * cols + col;
    }

    init();

    function frame(now: number) {
      if (!visible || !ctx) { rafRef.current = 0; return; }

      // User click → ring
      const click = pendingClick.current;
      if (click) {
        pendingClick.current = null;
        if (rings.length < MAX_RINGS) {
          const dpr = Math.min(devicePixelRatio || 1, 2);
          rings.push({
            cx: click.x * dpr, cy: click.y * dpr, radius: 0,
            maxRadius: Math.max(imgW, imgH) * 0.35,
            alpha: dark ? 0.25 : 0.18,
            startTime: now,
          });
        }
      }

      const dpr = Math.min(devicePixelRatio || 1, 2);
      const cursor = (!prefersStill && cursorRef.current)
        ? { x: cursorRef.current.x * dpr, y: cursorRef.current.y * dpr }
        : null;

      // Spawn + retire
      if (now - lastSpawn > SPAWN_INTERVAL + Math.random() * 2000) {
        lastSpawn = now;
        trySpawn(now);
        // Retire one
        if (activeNodes.length > 6 && Math.random() < 0.4) {
          const pick = Math.floor(Math.random() * activeNodes.length);
          activeNodes[pick].fading = true;
        }
      }

      // Periodic broadcast
      if (now - lastRing > RING_INTERVAL + Math.random() * 3000) {
        lastRing = now;
        const online = activeNodes.filter(n => !n.fading && n.energy > 0.2);
        if (online.length > 0) {
          const src = online[Math.floor(Math.random() * online.length)];
          src.energy = Math.min(1, src.energy + 0.3);
          emitRing(dotIndex(src.col, src.row));
        }
      }

      // Update active nodes
      for (let i = activeNodes.length - 1; i >= 0; i--) {
        const n = activeNodes[i];
        if (n.fading) {
          n.energy += (0 - n.energy) * 0.02;
          if (n.energy < 0.005) { activeNodes.splice(i, 1); continue; }
        } else {
          const age = now - n.born;
          const fadeIn = Math.min(age / 1500, 1);
          const target = n.targetEnergy * fadeIn;
          // Heartbeat micro-pulse
          const pulse = Math.sin(now * 0.0015 + n.col * 1.7 + n.row * 2.3) * 0.05;
          n.energy += (target + pulse - n.energy) * 0.02;
          // Auto-fade after time
          if (age > FADE_AFTER && Math.random() < 0.001) n.fading = true;
        }
      }

      // Update rings
      for (let i = rings.length - 1; i >= 0; i--) {
        const r = rings[i];
        r.radius = (now - r.startTime) * 0.06;
        r.alpha *= 0.997;
        if (r.radius > r.maxRadius || r.alpha < 0.003) { rings.splice(i, 1); }
      }

      // Ring hits: boost active nodes
      for (const r of rings) {
        for (const n of activeNodes) {
          if (n.fading) continue;
          const d = dots[dotIndex(n.col, n.row)];
          if (!d) continue;
          const dist = Math.hypot(d.x - r.cx, d.y - r.cy);
          if (Math.abs(dist - r.radius) < 6) {
            n.energy = Math.min(1, n.energy + r.alpha * 0.8);
          }
        }
      }

      // === Render ===
      const dotR = 1.2 * dpr;
      const activeR = 2.5 * dpr;
      const rgb = dark ? '255,255,255' : '0,0,0';

      ctx.clearRect(0, 0, imgW, imgH);
      // Fill background
      ctx.fillStyle = `rgb(${bgR},${bgG},${bgB})`;
      ctx.fillRect(0, 0, imgW, imgH);

      // Breathing wave
      const diag = imgW + imgH;
      const wavePos = (Math.sin(now * 0.000125) * 0.5 + 0.5) * diag;
      const waveW = diag * 0.18;

      // Build active node lookup
      const activeSet = new Set<number>();
      const activeMap = new Map<number, ActiveNode>();
      for (const n of activeNodes) {
        const idx = dotIndex(n.col, n.row);
        activeSet.add(idx);
        activeMap.set(idx, n);
      }

      // Draw dots
      for (let i = 0; i < dots.length; i++) {
        const d = dots[i];
        let a = dark ? 0.06 : 0.05;
        let r = dotR;

        // Wave
        const dd = Math.abs((d.x + d.y) - wavePos);
        if (dd < waveW) { const wI = 1 - dd / waveW; a += wI * wI * 0.09; }

        // Ring pass-through: dots glow when ring crosses them
        for (const ring of rings) {
          const dist = Math.hypot(d.x - ring.cx, d.y - ring.cy);
          const pd = Math.abs(dist - ring.radius);
          if (pd < 15 * dpr) a += (1 - pd / (15 * dpr)) * ring.alpha * 0.6;
        }

        // Cursor
        if (cursor) {
          const dx = d.x - cursor.x, dy = d.y - cursor.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const range = 70 * dpr;
          if (dist < range) a += (1 - dist / range) * 0.12;
        }

        // Active node override
        const active = activeMap.get(i);
        if (active) {
          a = Math.max(a, active.energy * (dark ? 0.5 : 0.35));
          r = dotR + (activeR - dotR) * active.energy;
        }

        a = Math.min(a, dark ? 0.55 : 0.35);
        ctx.fillStyle = `rgba(${rgb},${a})`;
        ctx.beginPath();
        ctx.arc(d.x, d.y, r, 0, 6.283);
        ctx.fill();
      }

      // Connection lines between nearby active nodes
      const maxDist = SPACE * dpr * 4;
      const maxDistSq = maxDist * maxDist;
      let connCount = 0;
      for (let i = 0; i < activeNodes.length && connCount < 20; i++) {
        const a = activeNodes[i];
        if (a.energy < 0.15) continue;
        const da = dots[dotIndex(a.col, a.row)];
        if (!da) continue;
        for (let j = i + 1; j < activeNodes.length && connCount < 20; j++) {
          const b = activeNodes[j];
          if (b.energy < 0.15) continue;
          const db = dots[dotIndex(b.col, b.row)];
          if (!db) continue;
          const dx = da.x - db.x, dy = da.y - db.y;
          const dSq = dx * dx + dy * dy;
          if (dSq > maxDistSq) continue;
          const dist = Math.sqrt(dSq);
          const al = (1 - dist / maxDist) * Math.min(a.energy, b.energy) * 0.15;
          if (al < 0.01) continue;
          ctx.beginPath();
          ctx.moveTo(da.x, da.y);
          ctx.lineTo(db.x, db.y);
          ctx.strokeStyle = `rgba(${rgb},${al})`;
          ctx.lineWidth = 1;
          ctx.stroke();
          connCount++;
        }
      }

      // Draw broadcast rings (clean stroked circles)
      for (const r of rings) {
        if (r.alpha < 0.005) continue;
        ctx.beginPath();
        ctx.arc(r.cx, r.cy, r.radius, 0, 6.283);
        ctx.strokeStyle = `rgba(${rgb},${r.alpha})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Cursor halo
      if (cursor) {
        const grad = ctx.createRadialGradient(cursor.x, cursor.y, 0, cursor.x, cursor.y, 50 * dpr);
        grad.addColorStop(0, `rgba(${rgb},0.06)`);
        grad.addColorStop(1, `rgba(${rgb},0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(cursor.x, cursor.y, 50 * dpr, 0, 6.283);
        ctx.fill();
      }

      rafRef.current = requestAnimationFrame(frame);
    }

    const start = () => { if (!rafRef.current) rafRef.current = requestAnimationFrame(frame); };
    const stop = () => { cancelAnimationFrame(rafRef.current); rafRef.current = 0; };

    const obs = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible) start(); else stop();
    }, { threshold: 0 });
    obs.observe(canvas);
    start();

    // Events
    const onClick = (e: MouseEvent) => {
      const rect = canvas!.getBoundingClientRect();
      pendingClick.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    const onMove = (e: MouseEvent) => {
      const rect = canvas!.getBoundingClientRect();
      cursorRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    const onLeave = () => { cursorRef.current = null; };
    canvas.addEventListener('click', onClick);
    canvas.addEventListener('mousemove', onMove);
    canvas.addEventListener('mouseleave', onLeave);

    let rt = 0;
    const onResize = () => { clearTimeout(rt); rt = window.setTimeout(init, 300); };
    window.addEventListener('resize', onResize);

    // Scroll-fade fallback
    let scrollCleanup: (() => void) | undefined;
    if (!prefersStill && !(typeof CSS !== 'undefined' && CSS.supports('animation-timeline', 'scroll()'))) {
      const wrap = canvas.parentElement;
      if (wrap) {
        const onScroll = () => {
          const t = Math.min(1, scrollY / 300);
          wrap.style.opacity = `${1 - t * 0.88}`;
        };
        addEventListener('scroll', onScroll, { passive: true });
        scrollCleanup = () => { removeEventListener('scroll', onScroll); wrap.style.opacity = ''; };
      }
    }

    return () => {
      stop();
      clearTimeout(rt);
      scrollCleanup?.();
      removeEventListener('resize', onResize);
      obs.disconnect();
      themeObs.disconnect();
      canvas.removeEventListener('click', onClick);
      canvas.removeEventListener('mousemove', onMove);
      canvas.removeEventListener('mouseleave', onLeave);
    };
  }, []);

  return <canvas ref={canvasRef} class="network-grid" aria-hidden="true" />;
}
