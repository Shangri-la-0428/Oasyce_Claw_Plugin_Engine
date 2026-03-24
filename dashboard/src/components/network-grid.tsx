/**
 * NetworkGrid — protocol-accurate network fabric
 *
 * Lifecycle: discover → heartbeat → online → idle → fade → gone
 * Validators: stable, slightly larger center.
 * Gossip: ripple hits node → node may re-emit smaller ripple.
 * Pace: meditative, installation-art quality.
 */
import { useRef, useEffect } from 'preact/hooks';
import './network-grid.css';

const HEIGHT = 160;

type NodeState = 'discovering' | 'online' | 'idle' | 'fading';

interface Node {
  x: number; y: number;
  state: NodeState;
  energy: number;        // current visual intensity 0..1
  peakEnergy: number;    // what it reaches when fully online
  isValidator: boolean;
  born: number;
  lastHeartbeat: number; // timestamp of last heartbeat
  heartbeatPhase: number; // offset so nodes don't pulse in sync
  satellites: Array<{ dx: number; dy: number; dist: number }>;
  depth: number;         // 0.2–0.8, parallax depth layer
}

interface Ripple {
  cx: number; cy: number;
  radius: number;
  maxRadius: number;
  speed: number;
  strength: number;
  startTime: number;
  sourceIdx: number;
  generation: number;    // 0=primary, 1=secondary (gossip forward)
}

function isDark(): boolean {
  return document.documentElement.dataset.theme !== 'light';
}

function hash(x: number, y: number, s: number): number {
  let h = (x * 374761393 + y * 668265263 + s * 1274126177) | 0;
  h = ((h ^ (h >> 13)) * 1103515245) | 0;
  return ((h ^ (h >> 16)) & 0x7fffffff) / 0x7fffffff;
}

function makeSatellites(seed: number): Array<{ dx: number; dy: number; dist: number }> {
  const sats: Array<{ dx: number; dy: number; dist: number }> = [];
  const count = 4 + Math.floor(hash(seed, 0, 1) * 3); // 4-6 satellites
  for (let i = 0; i < count; i++) {
    const ring = i < 2 ? 1 : 2;
    const baseR = ring === 1 ? 10 : 20;
    const angle = (i / count) * Math.PI * 2 + hash(seed, i, 2) * 0.9;
    const r = baseR + (hash(seed, i, 3) - 0.5) * 6;
    sats.push({ dx: Math.round(Math.cos(angle) * r), dy: Math.round(Math.sin(angle) * r), dist: r });
  }
  return sats;
}

export default function NetworkGrid() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef(0);
  // Delight: click/touch canvas to emit a ripple from cursor — "you are a node"
  const pendingClick = useRef<{ x: number; y: number } | null>(null);
  const cursorRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let imgW = 0, imgH = 0;
    let imgBuf: ImageData | null = null;
    let imgU32: Uint32Array | null = null;  // 32-bit view for fast bg fill
    let visible = true;
    const ctx2d = canvas.getContext('2d');
    const prefersStill = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const nodes: Node[] = [];
    const ripples: Ripple[] = [];
    let lastSpawn = 0;
    let lastRipple = 0;
    const gossipTimers = new Set<ReturnType<typeof setTimeout>>();

    // Cache computed CSS colors — only recalculate on theme change
    let cachedDark = isDark();
    let cachedBgR = 0, cachedBgG = 0, cachedBgB = 0;
    function refreshCachedColors() {
      cachedDark = isDark();
      const dark = cachedDark;
      const rootStyle = getComputedStyle(document.documentElement);
      const bgHex = rootStyle.getPropertyValue('--bg-0').trim();
      cachedBgR = parseInt(bgHex.slice(1, 3), 16) || (dark ? 10 : 250);
      cachedBgG = parseInt(bgHex.slice(3, 5), 16) || (dark ? 10 : 249);
      cachedBgB = parseInt(bgHex.slice(5, 7), 16) || (dark ? 10 : 246);
    }
    refreshCachedColors();

    const themeObserver = new MutationObserver(() => { refreshCachedColors(); });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    const HEARTBEAT_MS = 4000;
    const IDLE_AFTER = 8000;
    const FADE_AFTER = 14000;
    const SPAWN_INTERVAL = 3000;
    const RIPPLE_INTERVAL = 3500;
    const MAX_NODES = 28;
    const MAX_RIPPLES = 12;

    // Delight: process user-triggered ripple
    function drainClick(now: number) {
      const click = pendingClick.current;
      if (!click) return;
      pendingClick.current = null;
      if (ripples.length >= MAX_RIPPLES) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cx = Math.round(click.x * dpr);
      const cy = Math.round(click.y * dpr);
      ripples.push({
        cx, cy,
        radius: 0,
        maxRadius: Math.max(imgW, imgH) * 0.35,
        speed: 0.03,
        strength: 0.8,
        startTime: now,
        sourceIdx: -1,
        generation: 0,
      });
    }

    function init() {
      const W = canvas!.parentElement?.clientWidth ?? canvas!.clientWidth;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      imgW = Math.max(1, Math.floor(W * dpr));
      imgH = Math.max(1, Math.floor(HEIGHT * dpr));
      canvas!.width = imgW;
      canvas!.height = imgH;
      canvas!.style.width = `${W}px`;
      canvas!.style.height = `${HEIGHT}px`;

      // Persistent pixel buffer — avoids ~1MB allocation per frame
      imgBuf = ctx2d!.createImageData(imgW, imgH);
      imgU32 = new Uint32Array(imgBuf.data.buffer);

      nodes.length = 0;
      ripples.length = 0;

      // Start with a handful of already-online nodes
      const initial = 10 + Math.floor(Math.random() * 5);
      const minDist = Math.min(imgW, imgH) * 0.18;
      const now = performance.now();
      const padX = Math.min(30, imgW >> 2);
      const padY = Math.min(20, imgH >> 2);
      const spanX = Math.max(1, imgW - padX * 2);
      const spanY = Math.max(1, imgH - padY * 2);

      for (let i = 0; i < initial; i++) {
        let x: number, y: number, ok: boolean, tries = 0;
        do {
          x = padX + Math.floor(Math.random() * spanX);
          y = padY + Math.floor(Math.random() * spanY);
          ok = true;
          for (const n of nodes) { if (Math.hypot(n.x - x, n.y - y) < minDist) { ok = false; break; } }
          tries++;
        } while (!ok && tries < 80);

        const isVal = i < 3; // first 3 are validators
        nodes.push({
          x, y,
          state: 'online',
          energy: 0.3 + Math.random() * 0.2,
          peakEnergy: isVal ? 0.55 : 0.35 + Math.random() * 0.15,
          isValidator: isVal,
          born: now - 10000, // already existed
          lastHeartbeat: now - Math.random() * HEARTBEAT_MS,
          heartbeatPhase: Math.random() * Math.PI * 2,
          satellites: makeSatellites(i * 137 + x),
          depth: isVal ? 0.25 : 0.4 + Math.random() * 0.35,
        });
      }
      lastSpawn = lastRipple = now;
    }

    init();

    function spawnNode(now: number) {
      if (nodes.length >= MAX_NODES) return;
      const minDist = Math.min(imgW, imgH) * 0.15;
      const padX = Math.min(30, imgW >> 2);
      const padY = Math.min(20, imgH >> 2);
      const spanX = Math.max(1, imgW - padX * 2);
      const spanY = Math.max(1, imgH - padY * 2);
      let x: number, y: number, ok: boolean, tries = 0;
      do {
        x = padX + Math.floor(Math.random() * spanX);
        y = padY + Math.floor(Math.random() * spanY);
        ok = true;
        for (const n of nodes) { if (Math.hypot(n.x - x, n.y - y) < minDist) { ok = false; break; } }
        tries++;
      } while (!ok && tries < 50);
      if (!ok) return;

      nodes.push({
        x, y,
        state: 'discovering',
        energy: 0,
        peakEnergy: 0.3 + Math.random() * 0.2,
        isValidator: false,
        born: now,
        lastHeartbeat: now,
        heartbeatPhase: Math.random() * Math.PI * 2,
        satellites: makeSatellites(nodes.length * 137 + x),
        depth: 0.4 + Math.random() * 0.35,
      });
    }

    function emitRipple(idx: number, generation: number) {
      if (ripples.length >= MAX_RIPPLES) return;
      const n = nodes[idx];
      if (!n) return;
      n.energy = Math.min(1, n.energy + 0.4);
      n.lastHeartbeat = performance.now();

      const maxR = generation === 0
        ? Math.max(imgW, imgH) * (0.25 + Math.random() * 0.2)
        : Math.max(imgW, imgH) * (0.1 + Math.random() * 0.1); // secondary = smaller

      ripples.push({
        cx: n.x, cy: n.y,
        radius: 0,
        maxRadius: maxR,
        speed: 0.025 + Math.random() * 0.01,
        strength: generation === 0 ? 0.7 : 0.35,
        startTime: performance.now(),
        sourceIdx: idx,
        generation,
      });
    }

    function drawBlock(px: Uint8ClampedArray, bx: number, by: number, size: number, shade: number, dark: boolean) {
      const half = (size - 1) >> 1;
      for (let py = 0; py < size; py++) {
        for (let ppx = 0; ppx < size; ppx++) {
          const fx = bx - half + ppx, fy = by - half + py;
          if (fx >= 0 && fx < imgW && fy >= 0 && fy < imgH) {
            const off = (fy * imgW + fx) * 4;
            if (dark ? shade > px[off] : shade < px[off]) {
              px[off] = shade; px[off + 1] = shade; px[off + 2] = shade;
            }
          }
        }
      }
    }

    // Track which nodes got hit by ripple this frame (for gossip forwarding)
    const hitNodes = new Set<number>();

    function frame(now: number) {
      if (!ctx2d) { if (visible) rafRef.current = requestAnimationFrame(frame); return; }
      const ctx = ctx2d;

      // --- User-triggered ripple ---
      drainClick(now);

      // --- Cursor state (shared across update + render) ---
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cursor = cursorRef.current;
      // Reduced motion: disable cursor-driven effects (parallax, halos, proximity glow)
      const cursorPx = (!prefersStill && cursor) ? { x: cursor.x * dpr, y: cursor.y * dpr } : null;

      // --- Spawn new nodes ---
      if (now - lastSpawn > SPAWN_INTERVAL + Math.random() * 2000) {
        lastSpawn = now;
        spawnNode(now);
        // Also randomly retire a non-validator node to keep turnover visible
        let mortalCount = 0, mortalPick = -1;
        for (let i = 0; i < nodes.length; i++) {
          if (!nodes[i].isValidator && nodes[i].state === 'online') {
            mortalCount++;
            if (Math.random() * mortalCount < 1) mortalPick = i;
          }
        }
        if (mortalCount > 8 && Math.random() < 0.5 && mortalPick >= 0) {
          nodes[mortalPick].state = 'fading';
        }
      }

      // --- Primary broadcast ---
      if (now - lastRipple > RIPPLE_INTERVAL + Math.random() * 3000) {
        lastRipple = now;
        let onlineCount = 0, onlinePick = -1;
        for (let i = 0; i < nodes.length; i++) {
          if (nodes[i].state === 'online') {
            onlineCount++;
            if (Math.random() * onlineCount < 1) onlinePick = i;
          }
        }
        if (onlinePick >= 0) emitRipple(onlinePick, 0);
      }

      // --- Update node states ---
      for (const n of nodes) {
        const sinceHeartbeat = now - n.lastHeartbeat;
        const sinceBorn = now - n.born;

        // State transitions
        if (n.state === 'discovering' && sinceBorn > 2000) {
          n.state = 'online';
          n.lastHeartbeat = now;
        }
        if (n.state === 'online' && sinceHeartbeat > IDLE_AFTER && !n.isValidator) {
          n.state = 'idle';
        }
        if (n.state === 'idle' && sinceHeartbeat > FADE_AFTER) {
          n.state = 'fading';
        }

        // Energy targets by state
        let targetEnergy: number;
        switch (n.state) {
          case 'discovering': targetEnergy = 0.35; break; // visible flash on discovery
          case 'online': targetEnergy = n.peakEnergy; break;
          case 'idle': targetEnergy = n.peakEnergy * 0.3; break;
          case 'fading': targetEnergy = 0; break;
        }

        // Heartbeat micro-pulse for online nodes
        if (n.state === 'online') {
          const hbCycle = Math.sin((now / (HEARTBEAT_MS / 2)) * Math.PI + n.heartbeatPhase);
          targetEnergy += hbCycle * 0.06; // subtle ±6% pulse
        }

        // Validators get self-heartbeat (they stay online)
        if (n.isValidator && n.state === 'online') {
          n.lastHeartbeat = now; // always "alive"
        }

        // Smooth toward target
        n.energy += (targetEnergy - n.energy) * 0.015;
        n.energy = Math.max(0, Math.min(1, n.energy));

        // Fade-in for discovering
        if (n.state === 'discovering') {
          n.energy *= Math.min(sinceBorn / 2000, 1);
        }
      }

      // Cursor proximity: awaken nearby idle nodes
      if (cursorPx) {
        for (const n of nodes) {
          const dx = n.x - cursorPx.x, dy = n.y - cursorPx.y;
          if (dx * dx + dy * dy < 3600 && n.state === 'idle') {  // 60²
            n.state = 'online';
            n.lastHeartbeat = now;
          }
        }
      }

      // --- Update ripples ---
      hitNodes.clear();
      for (let i = ripples.length - 1; i >= 0; i--) {
        const r = ripples[i];
        r.radius = (now - r.startTime) * r.speed;
        r.strength = Math.max(0, (r.generation === 0 ? 0.7 : 0.35) * (1 - r.radius / r.maxRadius));

        // Wave hits nodes
        for (let j = 0; j < nodes.length; j++) {
          if (j === r.sourceIdx) continue;
          const n = nodes[j];
          if (n.state === 'fading') continue;

          const dist = Math.hypot(n.x - r.cx, n.y - r.cy);
          if (Math.abs(dist - r.radius) < 4 && !hitNodes.has(j)) {
            n.energy = Math.min(1, n.energy + r.strength * 0.25);
            n.lastHeartbeat = now; // receiving a message counts as activity
            if (n.state === 'idle') n.state = 'online'; // wake up on message

            hitNodes.add(j);

            // Gossip forward: ~25% chance for online nodes, only from primary ripples
            // Capture node ref (not index) — index shifts when dead nodes are spliced
            if (r.generation === 0 && n.state === 'online' && Math.random() < 0.25) {
              const gossipNode = n;
              const tid = setTimeout(() => {
                gossipTimers.delete(tid);
                const idx = nodes.indexOf(gossipNode);
                if (idx >= 0) emitRipple(idx, 1);
              }, 300 + Math.random() * 500);
              gossipTimers.add(tid);
            }
          }
        }

        if (r.radius > r.maxRadius) ripples.splice(i, 1);
      }

      // --- Remove dead nodes ---
      for (let i = nodes.length - 1; i >= 0; i--) {
        if (nodes[i].state === 'fading' && nodes[i].energy < 0.003) {
          nodes.splice(i, 1);
        }
      }

      // --- Render ---
      const dark = cachedDark;
      // Use cached CSS color values (refreshed on theme change via MutationObserver)
      const bgR = cachedBgR;
      const bgG = cachedBgG;
      const bgB = cachedBgB;
      const sDim = dark ? 60 : 200;
      const sMid = dark ? 140 : 110;
      const sBright = dark ? 220 : 35;

      if (!imgBuf || !imgU32) { if (visible) rafRef.current = requestAnimationFrame(frame); return; }
      const px = imgBuf.data;
      // 32-bit ABGR fill (little-endian): ~4× faster than per-channel loop
      const bgWord = (255 << 24) | (bgB << 16) | (bgG << 8) | bgR;
      imgU32.fill(bgWord);

      const slowSeed = Math.floor(now / 220);

      // Parallax offset (cursor-driven depth)
      const prlxX = cursorPx ? (cursorPx.x - imgW / 2) / (imgW / 2) : 0;
      const prlxY = cursorPx ? (cursorPx.y - imgH / 2) / (imgH / 2) : 0;

      // Draw nodes
      for (const n of nodes) {
        if (n.energy < 0.005) continue;

        // Parallax-adjusted display position
        const cx = Math.round(n.x + prlxX * n.depth * 6);
        const cy = Math.round(n.y + prlxY * n.depth * 6);

        // Proximity glow: cursor-near nodes appear brighter
        let e = n.energy;
        if (cursorPx) {
          const dx = n.x - cursorPx.x, dy = n.y - cursorPx.y;
          const dSq = dx * dx + dy * dy;
          if (dSq < 6400) e = Math.min(1, e + (1 - Math.sqrt(dSq) / 80) * 0.3);  // 80²
        }

        // Center dot
        const centerSize = n.isValidator
          ? (e > 0.3 ? 6 : 5)
          : (e > 0.4 ? 5 : 3);
        const centerShade = e > 0.5 ? sBright : (e > 0.25 ? sMid : sDim);

        drawBlock(px, cx, cy, centerSize, centerShade, dark);

        // Satellites: only show when energy is high enough
        if (e > 0.15) {
          const visibleDist = 5 + e * 14;

          for (let s = 0; s < n.satellites.length; s++) {
            const sat = n.satellites[s];
            if (sat.dist > visibleDist) continue;

            // Flicker: satellites shimmer in/out
            const flicker = hash(cx, s, slowSeed);
            if (flicker > e * 0.75) continue;

            const sx = cx + sat.dx;
            const sy = cy + sat.dy;
            if (sx < 0 || sx >= imgW || sy < 0 || sy >= imgH) continue;

            const shade = sat.dist < 12 ? sMid : sDim;
            drawBlock(px, sx, sy, 2, shade, dark);
          }
        }
      }

      // Draw ripples with wave interference
      // Each wavefront particle sums wave contributions from ALL active ripples,
      // producing constructive/destructive interference where rings overlap.
      const waveLen = 18; // pixels per wave cycle
      for (const r of ripples) {
        if (r.strength < 0.015) continue;

        const ringR = r.radius;
        const circumPx = Math.max(1, Math.floor(2 * Math.PI * ringR));
        const density = r.generation === 0 ? 0.18 : 0.1;
        const count = Math.max(4, Math.floor(circumPx * density));

        for (let a = 0; a < count; a++) {
          const h1 = hash(a, Math.round(ringR), slowSeed);
          if (h1 > r.strength * 1.1) continue;

          const angle = (a / count) * Math.PI * 2;
          const wx = r.cx + Math.cos(angle) * ringR;
          const wy = r.cy + Math.sin(angle) * ringR;
          const bx = Math.round(wx);
          const by = Math.round(wy);
          if (bx < 0 || bx >= imgW || by < 0 || by >= imgH) continue;

          // Sum wave contributions from all active ripples at this point
          let totalWave = 0;
          for (const r2 of ripples) {
            if (r2.strength < 0.01) continue;
            const d = Math.hypot(wx - r2.cx, wy - r2.cy);
            const delta = d - r2.radius;
            if (delta > 6 || delta < -6) continue; // outside Gaussian envelope
            const envelope = Math.exp(-(delta * delta) / 18); // σ ≈ 3px
            const phase = Math.sin((d / waveLen) * Math.PI * 2);
            totalWave += r2.strength * envelope * phase;
          }

          const intensity = Math.abs(totalWave);
          if (intensity < 0.03) continue; // destructive interference → invisible

          const shade = intensity > 0.35 ? sBright : (intensity > 0.15 ? sMid : sDim);
          const size = intensity > 0.35 ? 3 : 2;
          drawBlock(px, bx, by, size, shade, dark);

          // Trailing scatter (modulated by interference)
          if (intensity > 0.2) {
            const trailR = ringR - 3 - hash(a, Math.round(ringR), 88) * 5;
            if (trailR > 0) {
              const tx = Math.round(r.cx + Math.cos(angle) * trailR);
              const ty = Math.round(r.cy + Math.sin(angle) * trailR);
              if (tx >= 0 && tx < imgW && ty >= 0 && ty < imgH) {
                drawBlock(px, tx, ty, 2, sDim, dark);
              }
            }
          }
        }
      }

      ctx.putImageData(imgBuf, 0, 0);

      // --- Connection lines (ctx API overlay) ---
      const maxConn = 40;
      const maxConnDist = imgW * 0.22;
      const maxConnDistSq = maxConnDist * maxConnDist;
      let connCount = 0;
      for (let i = 0; i < nodes.length && connCount < maxConn; i++) {
        const a = nodes[i];
        if (a.energy < 0.12) continue;
        const ax = a.x + prlxX * a.depth * 6;
        const ay = a.y + prlxY * a.depth * 6;

        for (let j = i + 1; j < nodes.length && connCount < maxConn; j++) {
          const b = nodes[j];
          if (b.energy < 0.12) continue;
          const bx = b.x + prlxX * b.depth * 6;
          const by = b.y + prlxY * b.depth * 6;

          const dxC = ax - bx, dyC = ay - by;
          const dSqC = dxC * dxC + dyC * dyC;
          if (dSqC > maxConnDistSq) continue;
          const dist = Math.sqrt(dSqC);
          const alpha = (1 - dist / maxConnDist) * Math.min(a.energy, b.energy) * 0.18;
          if (alpha < 0.01) continue;

          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          ctx.strokeStyle = dark
            ? `rgba(255,255,255,${alpha})`
            : `rgba(0,0,0,${alpha})`;
          ctx.lineWidth = 1;
          ctx.stroke();
          connCount++;
        }
      }

      // --- Node halos (proximity glow, ctx API) ---
      if (cursorPx) {
        for (const n of nodes) {
          if (n.energy < 0.2) continue;
          const dxH = n.x - cursorPx.x, dyH = n.y - cursorPx.y;
          const dSqH = dxH * dxH + dyH * dyH;
          if (dSqH > 3600) continue;  // 60²
          const dist = Math.sqrt(dSqH);

          const nx = n.x + prlxX * n.depth * 6;
          const ny = n.y + prlxY * n.depth * 6;
          const haloR = Math.min(20, 8 + n.energy * 12);
          const proximity = 1 - dist / 60;
          const alpha = proximity * n.energy * 0.12;

          const grad = ctx.createRadialGradient(nx, ny, 0, nx, ny, haloR);
          const rgb = dark ? '255,255,255' : '0,0,0';
          grad.addColorStop(0, `rgba(${rgb},${alpha})`);
          grad.addColorStop(1, `rgba(${rgb},0)`);
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(nx, ny, haloR, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      if (visible) rafRef.current = requestAnimationFrame(frame);
      else rafRef.current = 0;
    }

    const startLoop = () => { if (!rafRef.current) rafRef.current = requestAnimationFrame(frame); };
    const stopLoop = () => { cancelAnimationFrame(rafRef.current); rafRef.current = 0; };

    // Only animate when visible
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) startLoop(); else stopLoop();
    }, { threshold: 0 });
    observer.observe(canvas);

    startLoop();

    // Delight: click/touch to broadcast
    const onClick = (e: MouseEvent) => {
      const rect = canvas!.getBoundingClientRect();
      pendingClick.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    canvas.addEventListener('click', onClick);
    const onMouseMove = (e: MouseEvent) => {
      const rect = canvas!.getBoundingClientRect();
      cursorRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    const onMouseLeave = () => { cursorRef.current = null; };
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseleave', onMouseLeave);

    let rt = 0;
    const onResize = () => { clearTimeout(rt); rt = window.setTimeout(init, 300); };
    window.addEventListener('resize', onResize);

    // Scroll-fade fallback for browsers without scroll-driven animations
    let scrollCleanup: (() => void) | undefined;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reducedMotion && !(typeof CSS !== 'undefined' && CSS.supports('animation-timeline', 'scroll()'))) {
      const wrap = canvas.parentElement;
      if (wrap) {
        const onScroll = () => {
          const t = Math.min(1, window.scrollY / 300);
          wrap.style.opacity = `${1 - t * 0.88}`;
        };
        window.addEventListener('scroll', onScroll, { passive: true });
        scrollCleanup = () => { window.removeEventListener('scroll', onScroll); wrap.style.opacity = ''; };
      }
    }

    return () => {
      stopLoop();
      clearTimeout(rt);
      gossipTimers.forEach(clearTimeout);
      gossipTimers.clear();
      scrollCleanup?.();
      window.removeEventListener('resize', onResize);
      observer.disconnect();
      themeObserver.disconnect();
      canvas.removeEventListener('click', onClick);
      canvas.removeEventListener('mousemove', onMouseMove);
      canvas.removeEventListener('mouseleave', onMouseLeave);
    };
  }, []);

  return <canvas ref={canvasRef} class="network-grid" aria-hidden="true" />;
}
