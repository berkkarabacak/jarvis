/**
 * Copied from https://github.com/Ashish-Soni08/aura
 * Licensed under the Apache License, Version 2.0
 * http://www.apache.org/licenses/LICENSE-2.0
 */
import { OrbState, OrbStateConfig } from './types';

export const INITIAL_CONFIG: Record<OrbState, OrbStateConfig> = {
  idle: {
    colorA: '#0F172A',
    colorB: '#3B82F6',
    colorC: '#60A5FA',
    speed: 0.2,
    intensity: 0.4,
  },
  listening: {
    colorA: '#431407',
    colorB: '#F59E0B',
    colorC: '#FEF3C7',
    speed: 0.5,
    intensity: 0.7,
  },
  processing: {
    colorA: '#2E1065',
    colorB: '#8B5CF6',
    colorC: '#C084FC',
    speed: 1.5,
    intensity: 1.2,
  },
  speaking: {
    colorA: '#064E3B',
    colorB: '#10B981',
    colorC: '#6EE7B7',
    speed: 0.8,
    intensity: 0.6,
  },
  error: {
    colorA: '#450A0A',
    colorB: '#EF4444',
    colorC: '#FCA5A5',
    speed: 0.3,
    intensity: 1.5,
  },
};

export const STATE_ORDER: OrbState[] = [
  'idle',
  'listening',
  'processing',
  'speaking',
  'error',
];
