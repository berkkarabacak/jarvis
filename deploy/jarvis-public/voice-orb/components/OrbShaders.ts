/**
 * Copied from https://github.com/Ashish-Soni08/aura
 * Licensed under the Apache License, Version 2.0
 * http://www.apache.org/licenses/LICENSE-2.0
 */
export const vertexShader = `
varying vec2 vUv;
varying vec3 vNormal;
varying vec3 vPosition;
varying vec3 vViewPosition;

uniform float uTime;
uniform float uSpeed;
uniform float uIntensity;

void main() {
  vUv = uv;
  vPosition = position;
  
  // Calculate view space normal and position for Fresnel
  vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
  vViewPosition = viewPos.xyz;
  vNormal = normalize(normalMatrix * normal);
  
  // Vertex displacement placeholder (uncomment + add noise function for "boiling" shape)
  // float noise = sin(position.x * 5.0 + uTime) * sin(position.y * 5.0 + uTime);
  // vec3 displaced = position + normal * noise * uIntensity * 0.05;
  
  gl_Position = projectionMatrix * viewPos;
}
`;

export const fragmentShader = `
varying vec2 vUv;
varying vec3 vNormal;
varying vec3 vPosition;
varying vec3 vViewPosition;

uniform float uTime;
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform vec3 uColorC;
uniform float uSpeed;
uniform float uIntensity;

// Simplex 3D Noise 
// by Ian McEwan, Ashima Arts
vec4 permute(vec4 x){return mod(((x*34.0)+1.0)*x, 289.0);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314 * r;}

float snoise(vec3 v){ 
  const vec2  C = vec2(1.0/6.0, 1.0/3.0) ;
  const vec4  D = vec4(0.0, 0.5, 1.0, 2.0);

  vec3 i  = floor(v + dot(v, C.yyy) );
  vec3 x0 = v - i + dot(i, C.xxx) ;

  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min( g.xyz, l.zxy );
  vec3 i2 = max( g.xyz, l.zxy );

  vec3 x1 = x0 - i1 + 1.0 * C.xxx;
  vec3 x2 = x0 - i2 + 2.0 * C.xxx;
  vec3 x3 = x0 - 1.0 + 3.0 * C.xxx;

  i = mod(i, 289.0 ); 
  vec4 p = permute( permute( permute( 
             i.z + vec4(0.0, i1.z, i2.z, 1.0 ))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0 )) 
           + i.x + vec4(0.0, i1.x, i2.x, 1.0 ));

  float n_ = 1.0/7.0;
  vec3  ns = n_ * D.wyz - D.xzx;

  vec4 j = p - 49.0 * floor(p * ns.z * ns.z); 

  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_ ); 

  vec4 x = x_ *ns.x + ns.yyyy;
  vec4 y = y_ *ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);

  vec4 b0 = vec4( x.xy, y.xy );
  vec4 b1 = vec4( x.zw, y.zw );

  vec4 s0 = floor(b0)*2.0 + 1.0;
  vec4 s1 = floor(b1)*2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));

  vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy ;
  vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww ;

  vec3 p0 = vec3(a0.xy,h.x);
  vec3 p1 = vec3(a0.zw,h.y);
  vec3 p2 = vec3(a1.xy,h.z);
  vec3 p3 = vec3(a1.zw,h.w);

  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2, p2), dot(p3,p3)));
  p0 *= norm.x;
  p1 *= norm.y;
  p2 *= norm.z;
  p3 *= norm.w;

  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 42.0 * dot( m*m, vec4( dot(p0,x0), dot(p1,x1), 
                                dot(p2,x2), dot(p3,x3) ) );
}

float fbm(vec3 x) {
  float v = 0.0;
  float a = 0.5;
  vec3 shift = vec3(100.0);
  for (int i = 0; i < 3; ++i) {
    v += a * snoise(x);
    x = x * 2.0 + shift;
    a *= 0.5;
  }
  return v;
}

void main() {
  // Use fBm for detailed organic noise
  float noise = fbm(vPosition * uIntensity + vec3(uTime * uSpeed));
  
  // Remap noise from [-1, 1] (approx) to [0, 1]
  float n = noise * 0.5 + 0.5;
  
  // Color Mixing
  // Base gradient
  vec3 color = mix(uColorA, uColorB, n);
  
  // Highlights (hot spots)
  float glow = smoothstep(0.4, 0.9, n);
  color = mix(color, uColorC, glow);
  
  // Fresnel Effect (Rim Light)
  vec3 viewDir = normalize(-vViewPosition);
  float fresnelTerm = dot(viewDir, vNormal);
  fresnelTerm = clamp(1.0 - fresnelTerm, 0.0, 1.0);
  fresnelTerm = pow(fresnelTerm, 2.5);
  
  // Add fresnel glow
  color += uColorC * fresnelTerm * 1.5;
  
  // Output
  gl_FragColor = vec4(color, 1.0);
}
`;