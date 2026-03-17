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
    const baseR = ring === 1 ? 7 : 15;
    const angle = (i / count) * Math.PI * 2 + hash(seed, i, 2) * 0.9;
    const r = baseR + (hash(seed, i, 3) - 0.5) * 5;
    sats.push({ dx: Math.round(Math.cos(angle) * r), dy: Math.round(Math.sin(angle) * r), dist: r });
  }
  return sats;
}

export default function NetworkGrid() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let imgW = 0, imgH = 0;
    const nodes: Node[] = [];
    const ripples: Ripple[] = [];
    let lastSpawn = 0;
    let lastRipple = 0;

    const HEARTBEAT_MS = 4000;
    const IDLE_AFTER = 8000;
    const FADE_AFTER = 14000;
    // const GONE_AFTER = 22000;
    const SPAWN_INTERVAL = 3000;
    const RIPPLE_INTERVAL = 3500;
    const MAX_NODES = 28;

    function init() {
      const W = canvas!.parentElement?.clientWidth ?? canvas!.clientWidth;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      imgW = Math.floor(W * dpr);
      imgH = Math.floor(HEIGHT * dpr);
      canvas!.width = imgW;
      canvas!.height = imgH;
      canvas!.style.width = `${W}px`;
      canvas!.style.height = `${HEIGHT}px`;

      nodes.length = 0;
      ripples.length = 0;

      // Start with a handful of already-online nodes
      const initial = 10 + Math.floor(Math.random() * 5);
      const minDist = Math.min(imgW, imgH) * 0.18;
      const now = performance.now();

      for (let i = 0; i < initial; i++) {
        let x: number, y: number, ok: boolean, tries = 0;
        do {
          x = 30 + Math.floor(Math.random() * (imgW - 60));
          y = 20 + Math.floor(Math.random() * (imgH - 40));
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
        });
      }
      lastSpawn = lastRipple = now;
    }

    init();

    function spawnNode(now: number) {
      if (nodes.length >= MAX_NODES) return;
      const minDist = Math.min(imgW, imgH) * 0.15;
      let x: number, y: number, ok: boolean, tries = 0;
      do {
        x = 30 + Math.floor(Math.random() * (imgW - 60));
        y = 20 + Math.floor(Math.random() * (imgH - 40));
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
      });
    }

    function emitRipple(idx: number, generation: number) {
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

    function drawBlock(px: Uint8ClampedArray, bx: number, by: number, size: number, shade: number) {
      const dark = isDark();
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
      const ctx = canvas!.getContext('2d');
      if (!ctx) { rafRef.current = requestAnimationFrame(frame); return; }

      // --- Spawn new nodes ---
      if (now - lastSpawn > SPAWN_INTERVAL + Math.random() * 2000) {
        lastSpawn = now;
        spawnNode(now);
        // Also randomly retire a non-validator node to keep turnover visible
        const mortals = nodes.map((n, i) => ({ n, i })).filter(o => !o.n.isValidator && o.n.state === 'online');
        if (mortals.length > 8 && Math.random() < 0.5) {
          const victim = mortals[Math.floor(Math.random() * mortals.length)];
          victim.n.state = 'fading';
        }
      }

      // --- Primary broadcast ---
      if (now - lastRipple > RIPPLE_INTERVAL + Math.random() * 3000) {
        lastRipple = now;
        const onlineNodes = nodes.map((n, i) => ({ n, i })).filter(o => o.n.state === 'online');
        if (onlineNodes.length > 0) {
          const pick = onlineNodes[Math.floor(Math.random() * onlineNodes.length)];
          emitRipple(pick.i, 0);
        }
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

            // Gossip forward: ~30% chance for online nodes, only from primary ripples
            if (r.generation === 0 && n.state === 'online' && Math.random() < 0.25) {
              setTimeout(() => emitRipple(j, 1), 300 + Math.random() * 500);
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
      const dark = isDark();
      // Read actual bg color from design system CSS variable
      const rootStyle = getComputedStyle(document.documentElement);
      const bgHex = rootStyle.getPropertyValue('--bg-0').trim();
      const bgR = parseInt(bgHex.slice(1, 3), 16) || (dark ? 10 : 250);
      const bgG = parseInt(bgHex.slice(3, 5), 16) || (dark ? 10 : 249);
      const bgB = parseInt(bgHex.slice(5, 7), 16) || (dark ? 10 : 246);
      const sDim = dark ? 60 : 200;
      const sMid = dark ? 140 : 110;
      const sBright = dark ? 220 : 35;

      const imgData = ctx.createImageData(imgW, imgH);
      const px = imgData.data;
      for (let i = 0; i < px.length; i += 4) {
        px[i] = bgR; px[i + 1] = bgG; px[i + 2] = bgB; px[i + 3] = 255;
      }

      const slowSeed = Math.floor(now / 220);

      // Draw nodes
      for (const n of nodes) {
        if (n.energy < 0.005) continue;

        const cx = Math.round(n.x);
        const cy = Math.round(n.y);

        // Center dot
        const centerSize = n.isValidator
          ? (n.energy > 0.3 ? 4 : 3)
          : (n.energy > 0.4 ? 3 : 2);
        const centerShade = n.energy > 0.5 ? sBright : (n.energy > 0.25 ? sMid : sDim);

        drawBlock(px, cx, cy, centerSize, centerShade);

        // Satellites: only show when energy is high enough
        if (n.energy > 0.15) {
          const visibleDist = 5 + n.energy * 14;

          for (let s = 0; s < n.satellites.length; s++) {
            const sat = n.satellites[s];
            if (sat.dist > visibleDist) continue;

            // Flicker: satellites shimmer in/out
            const flicker = hash(cx, s, slowSeed);
            if (flicker > n.energy * 0.75) continue;

            const sx = cx + sat.dx;
            const sy = cy + sat.dy;
            if (sx < 0 || sx >= imgW || sy < 0 || sy >= imgH) continue;

            const shade = sat.dist < 10 ? sMid : sDim;
            drawBlock(px, sx, sy, 1, shade);
          }
        }
      }

      // Draw ripple arcs with trailing scatter
      for (const r of ripples) {
        if (r.strength < 0.015) continue;

        const ringR = r.radius;
        const circumPx = Math.max(1, Math.floor(2 * Math.PI * ringR));
        const density = r.generation === 0 ? 0.18 : 0.1;
        const count = Math.max(4, Math.floor(circumPx * density));

        for (let a = 0; a < count; a++) {
          const h1 = hash(a, Math.round(ringR), slowSeed);
          if (h1 > r.strength) continue;

          const angle = (a / count) * Math.PI * 2;
          const bx = Math.round(r.cx + Math.cos(angle) * ringR);
          const by = Math.round(r.cy + Math.sin(angle) * ringR);
          if (bx < 0 || bx >= imgW || by < 0 || by >= imgH) continue;

          // Wavefront: 2px bright particles
          const frontSize = r.strength > 0.35 ? 2 : 1;
          drawBlock(px, bx, by, frontSize, r.strength > 0.3 ? sBright : sMid);

          // Trailing scatter: 1px dim particles behind the wavefront
          if (r.strength > 0.2) {
            const trailR = ringR - 3 - hash(a, Math.round(ringR), 88) * 5;
            if (trailR > 0) {
              const tx = Math.round(r.cx + Math.cos(angle) * trailR);
              const ty = Math.round(r.cy + Math.sin(angle) * trailR);
              if (tx >= 0 && tx < imgW && ty >= 0 && ty < imgH) {
                drawBlock(px, tx, ty, 1, sDim);
              }
            }
          }
        }
      }

      ctx.putImageData(imgData, 0, 0);
      rafRef.current = requestAnimationFrame(frame);
    }

    rafRef.current = requestAnimationFrame(frame);

    let rt = 0;
    const onResize = () => { clearTimeout(rt); rt = window.setTimeout(init, 300); };
    window.addEventListener('resize', onResize);
    return () => { cancelAnimationFrame(rafRef.current); clearTimeout(rt); window.removeEventListener('resize', onResize); };
  }, []);

  return <canvas ref={canvasRef} class="network-grid" />;
}
