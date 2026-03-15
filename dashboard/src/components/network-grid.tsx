/**
 * NetworkGrid — pixel-grid network visualization
 * Canvas-based cellular automaton aesthetic, pure grayscale
 */
import { useRef, useEffect, useCallback } from 'preact/hooks';
import './network-grid.css';

const CELL = 4;
const GAP = 1;
const STEP = CELL + GAP;
const HEIGHT = 120;
const FADE_MS = 800;
const PULSE_INTERVAL = 2000;
const CHURN_INTERVAL = 8000;

interface Cell {
  col: number;
  row: number;
  state: 'idle' | 'active' | 'transmit';
  brightness: number;   // 0..1 — current brightness level
  fadeFrom: number;      // brightness at fade start
  target: number;       // 0..1 — brightness to fade toward
  fadeStart: number;     // timestamp when fade began
}

function getColors(): { empty: string; idle: string; active: string; bright: string } {
  const s = getComputedStyle(document.documentElement);
  const theme = document.documentElement.dataset.theme;
  if (theme === 'light') {
    return {
      empty: s.getPropertyValue('--bg-1').trim() || '#f2f2f2',
      idle: s.getPropertyValue('--fg-3').trim() || '#cccccc',
      active: s.getPropertyValue('--fg-2').trim() || '#999999',
      bright: s.getPropertyValue('--fg-0').trim() || '#111111',
    };
  }
  return {
    empty: s.getPropertyValue('--bg-1').trim() || '#111111',
    idle: s.getPropertyValue('--fg-3').trim() || '#333333',
    active: s.getPropertyValue('--fg-2').trim() || '#5a5a5a',
    bright: s.getPropertyValue('--fg-0').trim() || '#e8e8e8',
  };
}

function hexToRgb(hex: string): [number, number, number] {
  const v = parseInt(hex.replace('#', ''), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

function lerpColor(a: string, b: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const bl = Math.round(ab + (bb - ab) * t);
  return `rgb(${r},${g},${bl})`;
}

export default function NetworkGrid() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<Cell[]>([]);
  const colsRef = useRef(0);
  const rowsRef = useRef(0);
  const rafRef = useRef(0);
  const pulseTimerRef = useRef(0);
  const churnTimerRef = useRef(0);
  const occupiedRef = useRef<Set<string>>(new Set());

  const key = (c: number, r: number) => `${c},${r}`;

  const initGrid = useCallback((canvas: HTMLCanvasElement, nodeCount: number) => {
    const w = canvas.parentElement?.clientWidth ?? canvas.clientWidth;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(HEIGHT * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${HEIGHT}px`;

    const cols = Math.floor(w / STEP);
    const rows = Math.floor(HEIGHT / STEP);
    colsRef.current = cols;
    rowsRef.current = rows;

    const totalSlots = cols * rows;
    const count = Math.min(nodeCount, Math.floor(totalSlots * 0.25));
    const nodes: Cell[] = [];
    const occupied = new Set<string>();

    for (let i = 0; i < count; i++) {
      let col: number, row: number, k: string;
      do {
        col = Math.floor(Math.random() * cols);
        row = Math.floor(Math.random() * rows);
        k = key(col, row);
      } while (occupied.has(k));
      occupied.add(k);
      const isActive = Math.random() < 0.3;
      nodes.push({
        col, row,
        state: isActive ? 'active' : 'idle',
        brightness: isActive ? 0.5 : 0.2,
        fadeFrom: isActive ? 0.5 : 0.2,
        target: isActive ? 0.5 : 0.2,
        fadeStart: 0,
      });
    }

    nodesRef.current = nodes;
    occupiedRef.current = occupied;
  }, []);

  const draw = useCallback((now: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const cols = colsRef.current;
    const rows = rowsRef.current;
    const colors = getColors();

    ctx.imageSmoothingEnabled = false;

    // clear with empty color
    ctx.fillStyle = colors.empty;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // draw empty grid cells
    const emptyRgb = colors.empty;
    ctx.fillStyle = emptyRgb;
    for (let c = 0; c < cols; c++) {
      for (let r = 0; r < rows; r++) {
        ctx.fillRect(
          Math.floor(c * STEP * dpr),
          Math.floor(r * STEP * dpr),
          Math.floor(CELL * dpr),
          Math.floor(CELL * dpr)
        );
      }
    }

    // draw occupied nodes
    const nodes = nodesRef.current;
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];

      // update brightness via fade
      if (n.fadeStart > 0 && n.brightness !== n.target) {
        const elapsed = now - n.fadeStart;
        const t = Math.min(elapsed / FADE_MS, 1);
        n.brightness = n.fadeFrom + (n.target - n.fadeFrom) * t;
        if (t >= 1) {
          n.brightness = n.target;
          n.fadeStart = 0;
          if (n.state === 'transmit') {
            n.state = Math.random() < 0.3 ? 'active' : 'idle';
          }
        }
      }

      // map brightness to color
      let color: string;
      if (n.brightness > 0.8) {
        color = lerpColor(colors.active, colors.bright, (n.brightness - 0.8) / 0.2);
      } else if (n.brightness > 0.4) {
        color = lerpColor(colors.idle, colors.active, (n.brightness - 0.4) / 0.4);
      } else {
        color = lerpColor(colors.empty, colors.idle, n.brightness / 0.4);
      }

      ctx.fillStyle = color;
      ctx.fillRect(
        Math.floor(n.col * STEP * dpr),
        Math.floor(n.row * STEP * dpr),
        Math.floor(CELL * dpr),
        Math.floor(CELL * dpr)
      );
    }
  }, []);

  const flash = useCallback((node: Cell, now: number) => {
    node.state = 'transmit';
    node.brightness = 1.0;
    node.fadeFrom = 1.0;
    node.target = Math.random() < 0.3 ? 0.5 : 0.2;
    node.fadeStart = now;
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let nodeCount = 30;

    // try fetching real node count
    fetch('/api/status')
      .then(r => r.json())
      .then(d => {
        if (d?.total_assets && d.total_assets > 0) {
          nodeCount = Math.max(15, Math.min(d.total_assets * 3, 80));
          initGrid(canvas, nodeCount);
        }
      })
      .catch(() => {});

    initGrid(canvas, nodeCount);

    // animation loop
    const loop = (now: number) => {
      draw(now);
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);

    // pulse: pick 2 nodes, flash sequentially
    pulseTimerRef.current = window.setInterval(() => {
      const nodes = nodesRef.current;
      if (nodes.length < 2) return;
      const i = Math.floor(Math.random() * nodes.length);
      let j: number;
      do { j = Math.floor(Math.random() * nodes.length); } while (j === i);

      const now = performance.now();
      flash(nodes[i], now);
      setTimeout(() => {
        flash(nodes[j], performance.now());
      }, 200);
    }, PULSE_INTERVAL);

    // churn: add or remove a node
    churnTimerRef.current = window.setInterval(() => {
      const nodes = nodesRef.current;
      const occupied = occupiedRef.current;
      const cols = colsRef.current;
      const rows = rowsRef.current;

      if (Math.random() < 0.5 && nodes.length > 10) {
        // remove a random node
        const idx = Math.floor(Math.random() * nodes.length);
        const removed = nodes[idx];
        occupied.delete(key(removed.col, removed.row));
        nodes.splice(idx, 1);
      } else if (cols > 0 && rows > 0) {
        // add a new node
        let col: number, row: number, k: string;
        let tries = 0;
        do {
          col = Math.floor(Math.random() * cols);
          row = Math.floor(Math.random() * rows);
          k = key(col, row);
          tries++;
        } while (occupied.has(k) && tries < 50);
        if (!occupied.has(k)) {
          occupied.add(k);
          nodes.push({
            col, row,
            state: 'idle',
            brightness: 0,
            fadeFrom: 0,
            target: 0.2,
            fadeStart: performance.now(),
          });
        }
      }
    }, CHURN_INTERVAL);

    // resize handler
    let resizeTimer = 0;
    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        const count = nodesRef.current.length;
        initGrid(canvas, count);
      }, 200);
    };
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(rafRef.current);
      clearInterval(pulseTimerRef.current);
      clearInterval(churnTimerRef.current);
      clearTimeout(resizeTimer);
      window.removeEventListener('resize', onResize);
    };
  }, [initGrid, draw, flash]);

  return <canvas ref={canvasRef} class="network-grid" />;
}
