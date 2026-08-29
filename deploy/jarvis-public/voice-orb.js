/**
 * Vanilla Voice Orb for Jarvis public Talk.
 *
 * Port of VoiceOrb, Canvas2DOrb, OrbShaders, types, and constants from
 * https://github.com/Ashish-Soni08/aura (Apache License 2.0).
 * Visual only. Not a third-party conversation widget.
 *
 * Licensed under the Apache License, Version 2.0
 * http://www.apache.org/licenses/LICENSE-2.0
 */
(function (global) {
  "use strict";

  var CONFIG = {
    idle: { colorA: "#0F172A", colorB: "#3B82F6", colorC: "#60A5FA", speed: 0.2, intensity: 0.4 },
    listening: { colorA: "#431407", colorB: "#F59E0B", colorC: "#FEF3C7", speed: 0.5, intensity: 0.7 },
    processing: { colorA: "#2E1065", colorB: "#8B5CF6", colorC: "#C084FC", speed: 1.5, intensity: 1.2 },
    speaking: { colorA: "#064E3B", colorB: "#10B981", colorC: "#6EE7B7", speed: 0.8, intensity: 0.6 },
    error: { colorA: "#450A0A", colorB: "#EF4444", colorC: "#FCA5A5", speed: 0.3, intensity: 1.5 }
  };
  var SCALE_MAP = { hero: 2.5, float: 1.8, mini: 1.0 };
  var FILL_MAP = { hero: 0.92, float: 0.88, mini: 0.78 };

  var VERTEX_SHADER =
    "attribute vec3 position;\n" +
    "attribute vec3 normal;\n" +
    "uniform mat4 modelViewMatrix;\n" +
    "uniform mat4 projectionMatrix;\n" +
    "uniform mat3 normalMatrix;\n" +
    "varying vec3 vNormal;\n" +
    "varying vec3 vPosition;\n" +
    "varying vec3 vViewPosition;\n" +
    "void main() {\n" +
    "  vPosition = position;\n" +
    "  vec4 viewPos = modelViewMatrix * vec4(position, 1.0);\n" +
    "  vViewPosition = viewPos.xyz;\n" +
    "  vNormal = normalize(normalMatrix * normal);\n" +
    "  gl_Position = projectionMatrix * viewPos;\n" +
    "}";

  var FRAGMENT_SHADER =
    "precision mediump float;\n" +
    "varying vec3 vNormal;\n" +
    "varying vec3 vPosition;\n" +
    "varying vec3 vViewPosition;\n" +
    "uniform float uTime;\n" +
    "uniform vec3 uColorA;\n" +
    "uniform vec3 uColorB;\n" +
    "uniform vec3 uColorC;\n" +
    "uniform float uSpeed;\n" +
    "uniform float uIntensity;\n" +
    "vec4 permute(vec4 x){return mod(((x*34.0)+1.0)*x, 289.0);}\n" +
    "vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314 * r;}\n" +
    "float snoise(vec3 v){\n" +
    "  const vec2 C = vec2(1.0/6.0, 1.0/3.0);\n" +
    "  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);\n" +
    "  vec3 i = floor(v + dot(v, C.yyy));\n" +
    "  vec3 x0 = v - i + dot(i, C.xxx);\n" +
    "  vec3 g = step(x0.yzx, x0.xyz);\n" +
    "  vec3 l = 1.0 - g;\n" +
    "  vec3 i1 = min(g.xyz, l.zxy);\n" +
    "  vec3 i2 = max(g.xyz, l.zxy);\n" +
    "  vec3 x1 = x0 - i1 + 1.0 * C.xxx;\n" +
    "  vec3 x2 = x0 - i2 + 2.0 * C.xxx;\n" +
    "  vec3 x3 = x0 - 1.0 + 3.0 * C.xxx;\n" +
    "  i = mod(i, 289.0);\n" +
    "  vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));\n" +
    "  float n_ = 1.0/7.0;\n" +
    "  vec3 ns = n_ * D.wyz - D.xzx;\n" +
    "  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);\n" +
    "  vec4 x_ = floor(j * ns.z);\n" +
    "  vec4 y_ = floor(j - 7.0 * x_);\n" +
    "  vec4 x = x_ * ns.x + ns.yyyy;\n" +
    "  vec4 y = y_ * ns.x + ns.yyyy;\n" +
    "  vec4 h = 1.0 - abs(x) - abs(y);\n" +
    "  vec4 b0 = vec4(x.xy, y.xy);\n" +
    "  vec4 b1 = vec4(x.zw, y.zw);\n" +
    "  vec4 s0 = floor(b0)*2.0 + 1.0;\n" +
    "  vec4 s1 = floor(b1)*2.0 + 1.0;\n" +
    "  vec4 sh = -step(h, vec4(0.0));\n" +
    "  vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;\n" +
    "  vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;\n" +
    "  vec3 p0 = vec3(a0.xy,h.x);\n" +
    "  vec3 p1 = vec3(a0.zw,h.y);\n" +
    "  vec3 p2 = vec3(a1.xy,h.z);\n" +
    "  vec3 p3 = vec3(a1.zw,h.w);\n" +
    "  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));\n" +
    "  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;\n" +
    "  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);\n" +
    "  m = m * m;\n" +
    "  return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));\n" +
    "}\n" +
    "float fbm(vec3 x) {\n" +
    "  float v = 0.0;\n" +
    "  float a = 0.5;\n" +
    "  vec3 shift = vec3(100.0);\n" +
    "  for (int i = 0; i < 3; ++i) { v += a * snoise(x); x = x * 2.0 + shift; a *= 0.5; }\n" +
    "  return v;\n" +
    "}\n" +
    "void main() {\n" +
    "  float noise = fbm(vPosition * uIntensity + vec3(uTime * uSpeed));\n" +
    "  float n = noise * 0.5 + 0.5;\n" +
    "  vec3 color = mix(uColorA, uColorB, n);\n" +
    "  float glow = smoothstep(0.4, 0.9, n);\n" +
    "  color = mix(color, uColorC, glow);\n" +
    "  vec3 viewDir = normalize(-vViewPosition);\n" +
    "  float fresnelTerm = clamp(1.0 - dot(viewDir, vNormal), 0.0, 1.0);\n" +
    "  fresnelTerm = pow(fresnelTerm, 2.5);\n" +
    "  color += uColorC * fresnelTerm * 1.5;\n" +
    "  gl_FragColor = vec4(color, 1.0);\n" +
    "}";

  var F3 = 1 / 3;
  var G3 = 1 / 6;
  var grad3 = [
    [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
    [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
    [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1]
  ];
  var perm = new Uint8Array(512);
  var p = [151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225, 140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148, 247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32, 57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175, 74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122, 60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54, 65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169, 200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64, 52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212, 207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213, 119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9, 129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104, 218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241, 81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157, 184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93, 222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180];
  var i;
  for (i = 0; i < 256; i++) {
    perm[i] = p[i];
    perm[i + 256] = p[i];
  }

  function hexToRgb(hex) {
    var h = String(hex || "").replace("#", "");
    return [
      parseInt(h.substring(0, 2), 16) / 255,
      parseInt(h.substring(2, 4), 16) / 255,
      parseInt(h.substring(4, 6), 16) / 255
    ];
  }

  function lerpColor(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }

  function lerpN(a, b, t) {
    return a + (b - a) * t;
  }

  function dot3(g, x, y, z) {
    return g[0] * x + g[1] * y + g[2] * z;
  }

  function simplex3(xin, yin, zin) {
    var s = (xin + yin + zin) * F3;
    var ii = Math.floor(xin + s);
    var jj = Math.floor(yin + s);
    var kk = Math.floor(zin + s);
    var t = (ii + jj + kk) * G3;
    var x0 = xin - (ii - t);
    var y0 = yin - (jj - t);
    var z0 = zin - (kk - t);
    var i1, j1, k1, i2, j2, k2;
    if (x0 >= y0) {
      if (y0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
      else if (x0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1; }
      else { i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1; }
    } else if (y0 < z0) { i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1; }
    else if (x0 < z0) { i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1; }
    else { i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
    var x1 = x0 - i1 + G3, y1 = y0 - j1 + G3, z1 = z0 - k1 + G3;
    var x2 = x0 - i2 + 2 * G3, y2 = y0 - j2 + 2 * G3, z2 = z0 - k2 + 2 * G3;
    var x3 = x0 - 1 + 3 * G3, y3 = y0 - 1 + 3 * G3, z3 = z0 - 1 + 3 * G3;
    var gi0 = perm[(ii & 255) + perm[(jj & 255) + perm[kk & 255]]] % 12;
    var gi1 = perm[(ii + i1 & 255) + perm[(jj + j1 & 255) + perm[kk + k1 & 255]]] % 12;
    var gi2 = perm[(ii + i2 & 255) + perm[(jj + j2 & 255) + perm[kk + k2 & 255]]] % 12;
    var gi3 = perm[(ii + 1 & 255) + perm[(jj + 1 & 255) + perm[kk + 1 & 255]]] % 12;
    var t0 = 0.6 - x0 * x0 - y0 * y0 - z0 * z0;
    var n0 = t0 < 0 ? 0 : (t0 *= t0, t0 * t0 * dot3(grad3[gi0], x0, y0, z0));
    var t1 = 0.6 - x1 * x1 - y1 * y1 - z1 * z1;
    var n1 = t1 < 0 ? 0 : (t1 *= t1, t1 * t1 * dot3(grad3[gi1], x1, y1, z1));
    var t2 = 0.6 - x2 * x2 - y2 * y2 - z2 * z2;
    var n2 = t2 < 0 ? 0 : (t2 *= t2, t2 * t2 * dot3(grad3[gi2], x2, y2, z2));
    var t3 = 0.6 - x3 * x3 - y3 * y3 - z3 * z3;
    var n3 = t3 < 0 ? 0 : (t3 *= t3, t3 * t3 * dot3(grad3[gi3], x3, y3, z3));
    return 32 * (n0 + n1 + n2 + n3);
  }

  function fbm3(x, y, z) {
    var v = 0, a = 0.5, n;
    for (n = 0; n < 4; n++) {
      v += a * simplex3(x, y, z);
      x = x * 2 + 100;
      y = y * 2 + 100;
      z = z * 2 + 100;
      a *= 0.5;
    }
    return v;
  }

  function isWebGLAvailable() {
    try {
      var c = document.createElement("canvas");
      return !!(c.getContext("webgl") || c.getContext("experimental-webgl"));
    } catch (e) {
      return false;
    }
  }

  function makeCanvas(host) {
    var canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;pointer-events:none;display:block;";
    host.appendChild(canvas);
    return canvas;
  }

  function compile(gl, type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      gl.deleteShader(sh);
      return null;
    }
    return sh;
  }

  function identity() {
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  }

  function multiply(a, b) {
    var o = new Array(16);
    var i, j, k;
    for (i = 0; i < 4; i++) {
      for (j = 0; j < 4; j++) {
        o[j * 4 + i] = 0;
        for (k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k];
      }
    }
    return o;
  }

  function perspective(fov, aspect, near, far) {
    var f = 1 / Math.tan((fov * Math.PI) / 360);
    var nf = 1 / (near - far);
    return [
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0
    ];
  }

  function lookAt(ex, ey, ez) {
    var zx = ex, zy = ey, zz = ez;
    var len = Math.hypot(zx, zy, zz) || 1;
    zx /= len; zy /= len; zz /= len;
    var xx = -zz, xy = 0, xz = zx;
    len = Math.hypot(xx, xy, xz) || 1;
    xx /= len; xy /= len; xz /= len;
    var yx = zy * xz - zz * xy;
    var yy = zz * xx - zx * xz;
    var yz = zx * xy - zy * xx;
    return [
      xx, yx, zx, 0,
      xy, yy, zy, 0,
      xz, yz, zz, 0,
      -(xx * ex + xy * ey + xz * ez),
      -(yx * ex + yy * ey + yz * ez),
      -(zx * ex + zy * ey + zz * ez),
      1
    ];
  }

  function normalFromMv(m) {
    return [
      m[0], m[1], m[2],
      m[4], m[5], m[6],
      m[8], m[9], m[10]
    ];
  }

  function makeSphere(segW, segH) {
    var pos = [];
    var nor = [];
    var idx = [];
    var y, x, v, u, phi, th, px, py, pz, i1, i2;
    for (y = 0; y <= segH; y++) {
      v = y / segH;
      phi = v * Math.PI;
      for (x = 0; x <= segW; x++) {
        u = x / segW;
        th = u * Math.PI * 2;
        px = Math.sin(phi) * Math.cos(th);
        py = Math.cos(phi);
        pz = Math.sin(phi) * Math.sin(th);
        pos.push(px, py, pz);
        nor.push(px, py, pz);
      }
    }
    for (y = 0; y < segH; y++) {
      for (x = 0; x < segW; x++) {
        i1 = y * (segW + 1) + x;
        i2 = i1 + segW + 1;
        idx.push(i1, i2, i1 + 1, i2, i2 + 1, i1 + 1);
      }
    }
    return {
      position: new Float32Array(pos),
      normal: new Float32Array(nor),
      index: new Uint16Array(idx)
    };
  }

  function startWebGL(canvas, getState, getSize) {
    var gl = canvas.getContext("webgl", { alpha: true, antialias: true, premultipliedAlpha: true }) ||
      canvas.getContext("experimental-webgl", { alpha: true, antialias: true });
    if (!gl) return null;
    var vs = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    var fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    if (!vs || !fs) return null;
    var prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
    gl.useProgram(prog);
    var mesh = makeSphere(32, 24);
    var posBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.position, gl.STATIC_DRAW);
    var locPos = gl.getAttribLocation(prog, "position");
    gl.enableVertexAttribArray(locPos);
    gl.vertexAttribPointer(locPos, 3, gl.FLOAT, false, 0, 0);
    var norBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, norBuf);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.normal, gl.STATIC_DRAW);
    var locNor = gl.getAttribLocation(prog, "normal");
    gl.enableVertexAttribArray(locNor);
    gl.vertexAttribPointer(locNor, 3, gl.FLOAT, false, 0, 0);
    var idxBuf = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.index, gl.STATIC_DRAW);
    var u = {
      mv: gl.getUniformLocation(prog, "modelViewMatrix"),
      proj: gl.getUniformLocation(prog, "projectionMatrix"),
      nrm: gl.getUniformLocation(prog, "normalMatrix"),
      time: gl.getUniformLocation(prog, "uTime"),
      colorA: gl.getUniformLocation(prog, "uColorA"),
      colorB: gl.getUniformLocation(prog, "uColorB"),
      colorC: gl.getUniformLocation(prog, "uColorC"),
      speed: gl.getUniformLocation(prog, "uSpeed"),
      intensity: gl.getUniformLocation(prog, "uIntensity")
    };
    var state = getState();
    var cur = {
      colorA: hexToRgb(CONFIG[state].colorA),
      colorB: hexToRgb(CONFIG[state].colorB),
      colorC: hexToRgb(CONFIG[state].colorC),
      speed: CONFIG[state].speed,
      intensity: CONFIG[state].intensity
    };
    var rotY = 0;
    var rotZ = 0;
    var last = performance.now();
    var time = 0;
    var raf = 0;
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    gl.clearColor(0, 0, 0, 0);

    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var w = canvas.clientWidth || 72;
      var h = canvas.clientHeight || 72;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function frame(now) {
      var dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      time += dt;
      var st = getState();
      var target = CONFIG[st] || CONFIG.idle;
      var lf = Math.min(1, dt * 5);
      cur.colorA = lerpColor(cur.colorA, hexToRgb(target.colorA), lf);
      cur.colorB = lerpColor(cur.colorB, hexToRgb(target.colorB), lf);
      cur.colorC = lerpColor(cur.colorC, hexToRgb(target.colorC), lf);
      cur.speed = lerpN(cur.speed, target.speed, lf);
      cur.intensity = lerpN(cur.intensity, target.intensity, lf);
      rotY += dt * 0.2 * cur.speed;
      rotZ += dt * 0.1 * cur.speed;
      resize();
      var aspect = (canvas.width / canvas.height) || 1;
      var proj = perspective(45, aspect, 0.1, 100);
      var scale = SCALE_MAP[getSize()] || SCALE_MAP.float;
      var cy = Math.cos(rotY), sy = Math.sin(rotY);
      var cz = Math.cos(rotZ), sz = Math.sin(rotZ);
      var model = [
        cy * scale, sz * sy * scale, cz * sy * scale, 0,
        0, cz * scale, -sz * scale, 0,
        -sy * scale, sz * cy * scale, cz * cy * scale, 0,
        0, 0, 0, 1
      ];
      var view = lookAt(0, 0, 6);
      var mv = multiply(view, model);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(prog);
      gl.uniformMatrix4fv(u.mv, false, mv);
      gl.uniformMatrix4fv(u.proj, false, proj);
      gl.uniformMatrix3fv(u.nrm, false, normalFromMv(mv));
      gl.uniform1f(u.time, time);
      gl.uniform3fv(u.colorA, cur.colorA);
      gl.uniform3fv(u.colorB, cur.colorB);
      gl.uniform3fv(u.colorC, cur.colorC);
      gl.uniform1f(u.speed, cur.speed);
      gl.uniform1f(u.intensity, cur.intensity);
      gl.drawElements(gl.TRIANGLES, mesh.index.length, gl.UNSIGNED_SHORT, 0);
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return function stop() {
      cancelAnimationFrame(raf);
    };
  }

  function startCanvas2D(canvas, getState, getSize) {
    var ctx = canvas.getContext("2d");
    if (!ctx) return null;
    var state = getState();
    var cur = {
      colorA: hexToRgb(CONFIG[state].colorA),
      colorB: hexToRgb(CONFIG[state].colorB),
      colorC: hexToRgb(CONFIG[state].colorC),
      speed: CONFIG[state].speed,
      intensity: CONFIG[state].intensity
    };
    var last = performance.now();
    var time = 0;
    var raf = 0;

    function frame(now) {
      var dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      time += dt;
      var st = getState();
      var target = CONFIG[st] || CONFIG.idle;
      var lf = Math.min(1, dt * 4);
      cur.colorA = lerpColor(cur.colorA, hexToRgb(target.colorA), lf);
      cur.colorB = lerpColor(cur.colorB, hexToRgb(target.colorB), lf);
      cur.colorC = lerpColor(cur.colorC, hexToRgb(target.colorC), lf);
      cur.speed = lerpN(cur.speed, target.speed, lf);
      cur.intensity = lerpN(cur.intensity, target.intensity, lf);
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var cw = canvas.clientWidth || 72;
      var ch = canvas.clientHeight || 72;
      if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
        canvas.width = cw * dpr;
        canvas.height = ch * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      var cx = cw / 2;
      var cy = ch / 2;
      var fill = FILL_MAP[getSize()] || FILL_MAP.float;
      var radius = Math.min(cw, ch) * fill / 2;
      var tSpeed = time * cur.speed;
      var glowRadius = radius * 1.6;
      var gR = Math.round(cur.colorB[0] * 255);
      var gG = Math.round(cur.colorB[1] * 255);
      var gB = Math.round(cur.colorB[2] * 255);
      var glowGrad = ctx.createRadialGradient(cx, cy, radius * 0.3, cx, cy, glowRadius);
      glowGrad.addColorStop(0, "rgba(" + gR + "," + gG + "," + gB + ",0.15)");
      glowGrad.addColorStop(0.5, "rgba(" + gR + "," + gG + "," + gB + ",0.06)");
      glowGrad.addColorStop(1, "rgba(" + gR + "," + gG + "," + gB + ",0)");
      ctx.beginPath();
      ctx.arc(cx, cy, glowRadius, 0, Math.PI * 2);
      ctx.fillStyle = glowGrad;
      ctx.fill();
      var orbDiam = Math.ceil(radius * 2);
      var step = orbDiam > 90 ? 2 : 1;
      var py, px, dist, nx, ny, nz, noise, n, color, glow, fresnel, specular, r, g, b, edgeFade;
      for (py = -orbDiam / 2; py < orbDiam / 2; py += step) {
        for (px = -orbDiam / 2; px < orbDiam / 2; px += step) {
          dist = Math.sqrt(px * px + py * py);
          if (dist > radius) continue;
          nx = px / radius;
          ny = py / radius;
          nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
          noise = fbm3(
            nx * cur.intensity * 1.5 + tSpeed * 0.3,
            ny * cur.intensity * 1.5 + tSpeed * 0.2,
            nz * cur.intensity + tSpeed * 0.4
          );
          n = noise * 0.5 + 0.5;
          color = lerpColor(cur.colorA, cur.colorB, n);
          glow = Math.max(0, Math.min(1, (n - 0.4) / 0.5));
          color = lerpColor(color, cur.colorC, glow);
          fresnel = Math.pow(1 - nz, 2.5);
          color = [
            Math.min(1, color[0] + cur.colorC[0] * fresnel * 1.2),
            Math.min(1, color[1] + cur.colorC[1] * fresnel * 1.2),
            Math.min(1, color[2] + cur.colorC[2] * fresnel * 1.2)
          ];
          specular = Math.pow(Math.max(0, nx * -0.4 + ny * -0.5 + nz * 0.7), 8);
          color = [
            Math.min(1, color[0] + specular * 0.6),
            Math.min(1, color[1] + specular * 0.6),
            Math.min(1, color[2] + specular * 0.6)
          ];
          r = Math.round(color[0] * 255);
          g = Math.round(color[1] * 255);
          b = Math.round(color[2] * 255);
          edgeFade = Math.min(1, (radius - dist) / 2);
          ctx.fillStyle = "rgba(" + r + "," + g + "," + b + "," + edgeFade.toFixed(3) + ")";
          ctx.fillRect(cx + px, cy + py, step, step);
        }
      }
      var cR = Math.round(cur.colorC[0] * 255);
      var cG = Math.round(cur.colorC[1] * 255);
      var cB = Math.round(cur.colorC[2] * 255);
      var coreGrad = ctx.createRadialGradient(cx - radius * 0.15, cy - radius * 0.15, 0, cx, cy, radius * 0.7);
      coreGrad.addColorStop(0, "rgba(" + cR + "," + cG + "," + cB + ",0.25)");
      coreGrad.addColorStop(1, "rgba(" + cR + "," + cG + "," + cB + ",0)");
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 0.7, 0, Math.PI * 2);
      ctx.fillStyle = coreGrad;
      ctx.fill();
      var rimGrad = ctx.createRadialGradient(cx, cy, radius * 0.85, cx, cy, radius * 1.15);
      rimGrad.addColorStop(0, "rgba(" + cR + "," + cG + "," + cB + ",0)");
      rimGrad.addColorStop(0.5, "rgba(" + cR + "," + cG + "," + cB + ",0.12)");
      rimGrad.addColorStop(1, "rgba(" + cR + "," + cG + "," + cB + ",0)");
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 1.15, 0, Math.PI * 2);
      ctx.fillStyle = rimGrad;
      ctx.fill();
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return function stop() {
      cancelAnimationFrame(raf);
    };
  }

  function mount(host, opts) {
    if (!host) return { setState: function () {}, destroy: function () {} };
    opts = opts || {};
    var state = opts.state || "listening";
    var size = opts.size === "hero" || opts.size === "mini" ? opts.size : "float";
    host.style.position = host.style.position || "relative";
    var canvas = host.querySelector("canvas") || makeCanvas(host);
    canvas.className = "orb-canvas";
    function getState() { return state; }
    function getSize() { return size; }
    var stop = null;
    if (isWebGLAvailable()) stop = startWebGL(canvas, getState, getSize);
    if (!stop) {
      canvas.dataset.fallback = "canvas2d";
      stop = startCanvas2D(canvas, getState, getSize);
    } else {
      canvas.dataset.renderer = "webgl";
    }
    return {
      setState: function (next) {
        if (CONFIG[next]) state = next;
      },
      setSize: function (next) {
        if (SCALE_MAP[next]) size = next;
      },
      destroy: function () {
        if (stop) stop();
        stop = null;
      }
    };
  }

  global.JarvisVoiceOrb = {
    mount: mount,
    CONFIG: CONFIG
  };
})(window);
