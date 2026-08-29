/**
 * Copied from https://github.com/Ashish-Soni08/aura
 * Licensed under the Apache License, Version 2.0
 * http://www.apache.org/licenses/LICENSE-2.0
 */
import React, { useRef, useEffect, useCallback } from 'react';
import * as THREE from 'three';
import { vertexShader, fragmentShader } from './OrbShaders';
import { OrbState, OrbStateConfig } from '../types';
import { Canvas2DOrb } from './Canvas2DOrb';

export interface VoiceOrbProps {
  currentState: OrbState;
  config: Record<OrbState, OrbStateConfig>;
  size: 'hero' | 'float' | 'mini';
}

const SCALE_MAP = {
  hero: 2.5,
  float: 1.8,
  mini: 1.0,
};

/** Check WebGL support without touching Three.js (avoids console errors) */
function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    const gl =
      canvas.getContext('webgl2') ||
      canvas.getContext('webgl') ||
      canvas.getContext('experimental-webgl');
    return gl != null;
  } catch {
    return false;
  }
}

const HAS_WEBGL = isWebGLAvailable();

export function VoiceOrb({ currentState, config, size }: VoiceOrbProps) {
  // If WebGL is not available, render Canvas 2D animated orb — never attempt Three.js
  if (!HAS_WEBGL) {
    return <Canvas2DOrb currentState={currentState} config={config} size={size} />;
  }

  return <WebGLOrb currentState={currentState} config={config} size={size} />;
}

/** Three.js powered orb — only mounted when WebGL is confirmed available */
function WebGLOrb({ currentState, config, size }: VoiceOrbProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    mesh: THREE.Mesh;
    material: THREE.ShaderMaterial;
    animationId: number;
    clock: THREE.Clock;
    currentValues: {
      colorA: THREE.Color;
      colorB: THREE.Color;
      colorC: THREE.Color;
      speed: number;
      intensity: number;
    };
    // OrbitControls state
    isDragging: boolean;
    previousMouse: { x: number; y: number };
    spherical: { theta: number; phi: number; radius: number };
    targetSpherical: { theta: number; phi: number; radius: number };
  } | null>(null);

  // Store latest props in refs so animation loop always sees current values
  const propsRef = useRef({ currentState, config, size });
  propsRef.current = { currentState, config, size };

  const initScene = useCallback((container: HTMLDivElement) => {
    const width = container.clientWidth;
    const height = container.clientHeight;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Scene
    const scene = new THREE.Scene();

    // Camera
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    const initialRadius = 6;
    camera.position.set(0, 0, initialRadius);
    camera.lookAt(0, 0, 0);

    // Geometry + Shader Material
    const geometry = new THREE.IcosahedronGeometry(1, 10);
    const stateConfig = config[currentState];

    const material = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uColorA: { value: new THREE.Color(stateConfig.colorA) },
        uColorB: { value: new THREE.Color(stateConfig.colorB) },
        uColorC: { value: new THREE.Color(stateConfig.colorC) },
        uSpeed: { value: stateConfig.speed },
        uIntensity: { value: stateConfig.intensity },
      },
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.DoubleSide,
    });

    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);

    const clock = new THREE.Clock();

    const currentValues = {
      colorA: new THREE.Color(stateConfig.colorA),
      colorB: new THREE.Color(stateConfig.colorB),
      colorC: new THREE.Color(stateConfig.colorC),
      speed: stateConfig.speed,
      intensity: stateConfig.intensity,
    };

    sceneRef.current = {
      renderer,
      scene,
      camera,
      mesh,
      material,
      animationId: 0,
      clock,
      currentValues,
      isDragging: false,
      previousMouse: { x: 0, y: 0 },
      spherical: { theta: 0, phi: Math.PI / 2, radius: initialRadius },
      targetSpherical: { theta: 0, phi: Math.PI / 2, radius: initialRadius },
    };
  }, []); // Only called once on mount

  // Animation loop
  const animate = useCallback(() => {
    const s = sceneRef.current;
    if (!s) return;

    const delta = s.clock.getDelta();
    const { currentState: state, config: cfg, size: sz } = propsRef.current;
    const targetConfig = cfg[state];

    // Compute target values
    const targetColorA = new THREE.Color(targetConfig.colorA);
    const targetColorB = new THREE.Color(targetConfig.colorB);
    const targetColorC = new THREE.Color(targetConfig.colorC);

    const lerpFactor = 5.0 * delta;

    // Lerp colors
    s.currentValues.colorA.lerp(targetColorA, lerpFactor);
    s.currentValues.colorB.lerp(targetColorB, lerpFactor);
    s.currentValues.colorC.lerp(targetColorC, lerpFactor);
    s.currentValues.speed = THREE.MathUtils.lerp(s.currentValues.speed, targetConfig.speed, lerpFactor);
    s.currentValues.intensity = THREE.MathUtils.lerp(s.currentValues.intensity, targetConfig.intensity, lerpFactor);

    // Update uniforms
    s.material.uniforms.uTime.value += delta;
    s.material.uniforms.uColorA.value.copy(s.currentValues.colorA);
    s.material.uniforms.uColorB.value.copy(s.currentValues.colorB);
    s.material.uniforms.uColorC.value.copy(s.currentValues.colorC);
    s.material.uniforms.uSpeed.value = s.currentValues.speed;
    s.material.uniforms.uIntensity.value = s.currentValues.intensity;

    // Rotate mesh
    s.mesh.rotation.y += delta * 0.2 * s.currentValues.speed;
    s.mesh.rotation.z += delta * 0.1 * s.currentValues.speed;

    // Auto rotate when processing
    if (state === 'processing') {
      s.targetSpherical.theta += delta * 2.0;
    }

    // Smooth camera orbit
    s.spherical.theta += (s.targetSpherical.theta - s.spherical.theta) * Math.min(1, delta * 5);
    s.spherical.phi += (s.targetSpherical.phi - s.spherical.phi) * Math.min(1, delta * 5);
    s.spherical.radius += (s.targetSpherical.radius - s.spherical.radius) * Math.min(1, delta * 5);

    // Clamp phi
    s.spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, s.spherical.phi));
    // Clamp radius
    s.spherical.radius = Math.max(3, Math.min(10, s.spherical.radius));

    // Update camera from spherical coords
    const r = s.spherical.radius;
    s.camera.position.x = r * Math.sin(s.spherical.phi) * Math.sin(s.spherical.theta);
    s.camera.position.y = r * Math.cos(s.spherical.phi);
    s.camera.position.z = r * Math.sin(s.spherical.phi) * Math.cos(s.spherical.theta);
    s.camera.lookAt(0, 0, 0);

    // Scale
    const targetScale = SCALE_MAP[sz];
    const currentScale = s.mesh.scale.x;
    const newScale = THREE.MathUtils.lerp(currentScale, targetScale, delta * 4);
    s.mesh.scale.set(newScale, newScale, newScale);

    s.renderer.render(s.scene, s.camera);
    s.animationId = requestAnimationFrame(animate);
  }, []);

  // Init + cleanup
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    initScene(container);

    if (!sceneRef.current) return; // WebGL failed

    animate();

    // Resize handler
    const handleResize = () => {
      const s = sceneRef.current;
      if (!s || !container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      s.renderer.setSize(w, h);
      s.camera.aspect = w / h;
      s.camera.updateProjectionMatrix();
    };

    // Mouse interaction (orbit controls)
    const handleMouseDown = (e: MouseEvent) => {
      const s = sceneRef.current;
      if (!s) return;
      s.isDragging = true;
      s.previousMouse = { x: e.clientX, y: e.clientY };
    };

    const handleMouseMove = (e: MouseEvent) => {
      const s = sceneRef.current;
      if (!s || !s.isDragging) return;
      const dx = e.clientX - s.previousMouse.x;
      const dy = e.clientY - s.previousMouse.y;
      s.targetSpherical.theta -= dx * 0.005;
      s.targetSpherical.phi += dy * 0.005;
      s.previousMouse = { x: e.clientX, y: e.clientY };
    };

    const handleMouseUp = () => {
      const s = sceneRef.current;
      if (s) s.isDragging = false;
    };

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const s = sceneRef.current;
      if (!s) return;
      s.targetSpherical.radius += e.deltaY * 0.005;
    };

    window.addEventListener('resize', handleResize);
    container.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    container.addEventListener('wheel', handleWheel, { passive: false });

    return () => {
      const s = sceneRef.current;
      if (s) {
        cancelAnimationFrame(s.animationId);
        s.renderer.dispose();
        s.material.dispose();
        s.mesh.geometry.dispose();
        if (container.contains(s.renderer.domElement)) {
          container.removeChild(s.renderer.domElement);
        }
      }
      window.removeEventListener('resize', handleResize);
      container.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      container.removeEventListener('wheel', handleWheel);
      sceneRef.current = null;
    };
  }, [initScene, animate]);

  return <div ref={containerRef} className="absolute inset-0" />;
}