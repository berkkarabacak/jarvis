/**
 * Copied from https://github.com/Ashish-Soni08/aura
 * Licensed under the Apache License, Version 2.0
 * http://www.apache.org/licenses/LICENSE-2.0
 */
export type OrbState = 'idle' | 'listening' | 'processing' | 'speaking' | 'error';

export interface OrbStateConfig {
  colorA: string;
  colorB: string;
  colorC: string;
  speed: number;
  intensity: number;
}
