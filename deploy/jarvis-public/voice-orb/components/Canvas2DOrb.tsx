/**
 * Copied from https://github.com/Ashish-Soni08/aura
 * Licensed under the Apache License, Version 2.0
 * http://www.apache.org/licenses/LICENSE-2.0
 */
import React, { useRef, useEffect } from 'react';
import { OrbState, OrbStateConfig } from '../types';

interface Canvas2DOrbProps {
  currentState: OrbState;
  config: Record<OrbState, OrbStateConfig>;
  size: 'hero' | 'float' | 'mini';
}

/* ── Simplex 2D/3D Noise (compact JS implementation) ── */
const F3 = 1 / 3;
const G3 = 1 / 6;
const grad3 = [
  [1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
  [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
  [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1],
];
const perm = new Uint8Array(512);
const p = [151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,140,36,103,30,69,142,8,99,37,240,21,10,23,190,6,148,247,120,234,75,0,26,197,62,94,252,219,203,117,35,11,32,57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,74,165,71,134,139,48,27,166,77,146,158,231,83,111,229,122,60,211,133,230,220,105,92,41,55,46,245,40,244,102,143,54,65,25,63,161,1,216,80,73,209,76,132,187,208,89,18,169,200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,52,217,226,250,124,123,5,202,38,147,118,126,255,82,85,212,207,206,59,227,47,16,58,17,182,189,28,42,223,183,170,213,119,248,152,2,44,154,163,70,221,153,101,155,167,43,172,9,129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,218,246,97,228,251,34,242,193,238,210,144,12,191,179,162,241,81,51,145,235,249,14,239,107,49,192,214,31,181,199,106,157,184,84,204,176,115,121,50,45,127,4,150,254,138,236,205,93,222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180];
for (let i = 0; i < 256; i++) { perm[i] = p[i]; perm[i + 256] = p[i]; }

function dot3(g: number[], x: number, y: number, z: number) {
  return g[0]*x + g[1]*y + g[2]*z;
}

function simplex3(xin: number, yin: number, zin: number): number {
  const s = (xin+yin+zin)*F3;
  const i = Math.floor(xin+s), j = Math.floor(yin+s), k = Math.floor(zin+s);
  const t = (i+j+k)*G3;
  const X0 = i-t, Y0 = j-t, Z0 = k-t;
  const x0 = xin-X0, y0 = yin-Y0, z0 = zin-Z0;

  let i1: number,j1: number,k1: number,i2: number,j2: number,k2: number;
  if (x0>=y0) {
    if (y0>=z0) { i1=1;j1=0;k1=0;i2=1;j2=1;k2=0; }
    else if (x0>=z0) { i1=1;j1=0;k1=0;i2=1;j2=0;k2=1; }
    else { i1=0;j1=0;k1=1;i2=1;j2=0;k2=1; }
  } else {
    if (y0<z0) { i1=0;j1=0;k1=1;i2=0;j2=1;k2=1; }
    else if (x0<z0) { i1=0;j1=1;k1=0;i2=0;j2=1;k2=1; }
    else { i1=0;j1=1;k1=0;i2=1;j2=1;k2=0; }
  }

  const x1=x0-i1+G3, y1=y0-j1+G3, z1=z0-k1+G3;
  const x2=x0-i2+2*G3, y2=y0-j2+2*G3, z2=z0-k2+2*G3;
  const x3=x0-1+3*G3, y3=y0-1+3*G3, z3=z0-1+3*G3;

  const ii=i&255, jj=j&255, kk=k&255;
  const gi0=perm[ii+perm[jj+perm[kk]]]%12;
  const gi1=perm[ii+i1+perm[jj+j1+perm[kk+k1]]]%12;
  const gi2=perm[ii+i2+perm[jj+j2+perm[kk+k2]]]%12;
  const gi3=perm[ii+1+perm[jj+1+perm[kk+1]]]%12;

  let t0=0.6-x0*x0-y0*y0-z0*z0;
  const n0 = t0<0 ? 0 : (t0*=t0, t0*t0*dot3(grad3[gi0],x0,y0,z0));
  let t1=0.6-x1*x1-y1*y1-z1*z1;
  const n1 = t1<0 ? 0 : (t1*=t1, t1*t1*dot3(grad3[gi1],x1,y1,z1));
  let t2=0.6-x2*x2-y2*y2-z2*z2;
  const n2 = t2<0 ? 0 : (t2*=t2, t2*t2*dot3(grad3[gi2],x2,y2,z2));
  let t3=0.6-x3*x3-y3*y3-z3*z3;
  const n3 = t3<0 ? 0 : (t3*=t3, t3*t3*dot3(grad3[gi3],x3,y3,z3));

  return 32*(n0+n1+n2+n3);
}

function fbm3(x: number, y: number, z: number): number {
  let v = 0, a = 0.5;
  for (let i = 0; i < 4; i++) {
    v += a * simplex3(x, y, z);
    x = x * 2 + 100;
    y = y * 2 + 100;
    z = z * 2 + 100;
    a *= 0.5;
  }
  return v;
}

/* ── Color helpers ── */
function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [
    parseInt(h.substring(0, 2), 16) / 255,
    parseInt(h.substring(2, 4), 16) / 255,
    parseInt(h.substring(4, 6), 16) / 255,
  ];
}

function lerpColor(
  a: [number, number, number],
  b: [number, number, number],
  t: number,
): [number, number, number] {
  return [a[0] + (b[0]-a[0])*t, a[1] + (b[1]-a[1])*t, a[2] + (b[2]-a[2])*t];
}

function lerpN(a: number, b: number, t: number) { return a + (b - a) * t; }

const SIZE_MAP = { hero: 300, float: 210, mini: 130 };

export function Canvas2DOrb({ currentState, config, size }: Canvas2DOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef(0);

  // Keep mutable current values for smooth lerping
  const valuesRef = useRef({
    colorA: hexToRgb(config[currentState].colorA),
    colorB: hexToRgb(config[currentState].colorB),
    colorC: hexToRgb(config[currentState].colorC),
    speed: config[currentState].speed,
    intensity: config[currentState].intensity,
    orbSize: SIZE_MAP[size],
  });

  const propsRef = useRef({ currentState, config, size });
  propsRef.current = { currentState, config, size };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let time = 0;
    let lastTime = performance.now();

    const draw = (now: number) => {
      const dt = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;
      time += dt;

      const { currentState: state, config: cfg, size: sz } = propsRef.current;
      const target = cfg[state];
      const v = valuesRef.current;

      // Smooth lerp all values
      const lf = Math.min(1, dt * 4);
      v.colorA = lerpColor(v.colorA, hexToRgb(target.colorA), lf);
      v.colorB = lerpColor(v.colorB, hexToRgb(target.colorB), lf);
      v.colorC = lerpColor(v.colorC, hexToRgb(target.colorC), lf);
      v.speed = lerpN(v.speed, target.speed, lf);
      v.intensity = lerpN(v.intensity, target.intensity, lf);
      v.orbSize = lerpN(v.orbSize, SIZE_MAP[sz], lf);

      const dpr = Math.min(window.devicePixelRatio, 2);
      const cw = canvas.clientWidth;
      const ch = canvas.clientHeight;
      if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
        canvas.width = cw * dpr;
        canvas.height = ch * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);

      const cx = cw / 2;
      const cy = ch / 2;
      const radius = v.orbSize / 2;

      // === Draw the orb using imageData for noise-based coloring ===
      // For performance, use a lower-res offscreen approach
      const orbDiam = Math.ceil(radius * 2);
      const step = 2; // sample every 2px for performance
      const tSpeed = time * v.speed;

      // Outer ambient glow
      const glowRadius = radius * 1.6;
      const glowGrad = ctx.createRadialGradient(cx, cy, radius * 0.3, cx, cy, glowRadius);
      const gR = Math.round(v.colorB[0] * 255);
      const gG = Math.round(v.colorB[1] * 255);
      const gB = Math.round(v.colorB[2] * 255);
      glowGrad.addColorStop(0, `rgba(${gR},${gG},${gB},0.15)`);
      glowGrad.addColorStop(0.5, `rgba(${gR},${gG},${gB},0.06)`);
      glowGrad.addColorStop(1, `rgba(${gR},${gG},${gB},0)`);
      ctx.beginPath();
      ctx.arc(cx, cy, glowRadius, 0, Math.PI * 2);
      ctx.fillStyle = glowGrad;
      ctx.fill();

      // Noise-painted sphere
      for (let py = -orbDiam / 2; py < orbDiam / 2; py += step) {
        for (let px = -orbDiam / 2; px < orbDiam / 2; px += step) {
          const dist = Math.sqrt(px * px + py * py);
          if (dist > radius) continue;

          // Map to sphere surface (fake Z from sphere equation)
          const nx = px / radius;
          const ny = py / radius;
          const nz = Math.sqrt(Math.max(0, 1 - nx*nx - ny*ny));

          // fBm noise on sphere surface
          const noise = fbm3(
            nx * v.intensity * 1.5 + tSpeed * 0.3,
            ny * v.intensity * 1.5 + tSpeed * 0.2,
            nz * v.intensity + tSpeed * 0.4,
          );
          const n = noise * 0.5 + 0.5; // remap to [0,1]

          // Color mix: A -> B by noise, then blend in C for highlights
          let color = lerpColor(v.colorA, v.colorB, n);
          const glow = Math.max(0, Math.min(1, (n - 0.4) / 0.5));
          color = lerpColor(color, v.colorC, glow);

          // Fresnel rim light
          const fresnel = Math.pow(1 - nz, 2.5);
          color = [
            Math.min(1, color[0] + v.colorC[0] * fresnel * 1.2),
            Math.min(1, color[1] + v.colorC[1] * fresnel * 1.2),
            Math.min(1, color[2] + v.colorC[2] * fresnel * 1.2),
          ];

          // Subtle specular highlight (top-left)
          const specular = Math.pow(Math.max(0, nx * -0.4 + ny * -0.5 + nz * 0.7), 8);
          color = [
            Math.min(1, color[0] + specular * 0.6),
            Math.min(1, color[1] + specular * 0.6),
            Math.min(1, color[2] + specular * 0.6),
          ];

          const r = Math.round(color[0] * 255);
          const g = Math.round(color[1] * 255);
          const b = Math.round(color[2] * 255);

          // Edge softness
          const edgeFade = Math.min(1, (radius - dist) / 2);
          const alpha = edgeFade;

          ctx.fillStyle = `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
          ctx.fillRect(cx + px, cy + py, step, step);
        }
      }

      // Inner core glow overlay
      const coreGrad = ctx.createRadialGradient(
        cx - radius * 0.15,
        cy - radius * 0.15,
        0,
        cx,
        cy,
        radius * 0.7,
      );
      const cR = Math.round(v.colorC[0] * 255);
      const cG = Math.round(v.colorC[1] * 255);
      const cB = Math.round(v.colorC[2] * 255);
      coreGrad.addColorStop(0, `rgba(${cR},${cG},${cB},0.25)`);
      coreGrad.addColorStop(1, `rgba(${cR},${cG},${cB},0)`);
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 0.7, 0, Math.PI * 2);
      ctx.fillStyle = coreGrad;
      ctx.fill();

      // Rim glow ring
      const rimGrad = ctx.createRadialGradient(cx, cy, radius * 0.85, cx, cy, radius * 1.15);
      rimGrad.addColorStop(0, `rgba(${cR},${cG},${cB},0)`);
      rimGrad.addColorStop(0.5, `rgba(${cR},${cG},${cB},0.12)`);
      rimGrad.addColorStop(1, `rgba(${cR},${cG},${cB},0)`);
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 1.15, 0, Math.PI * 2);
      ctx.fillStyle = rimGrad;
      ctx.fill();

      animRef.current = requestAnimationFrame(draw);
    };

    animRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animRef.current);
  }, []);

  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ imageRendering: 'auto' }}
      />
    </div>
  );
}
