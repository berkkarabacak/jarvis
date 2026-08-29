# Voice Orb Integration Guide

Use this guide to add the Aura Voice Orb to your own React app and connect it to
voice AI/agent state transitions.

## 1. Install dependency

```bash
npm install three
```

## 2. Copy the required files

Copy these files from this repository into your project:

- `src/app/components/VoiceOrb.tsx`
- `src/app/components/Canvas2DOrb.tsx`
- `src/app/components/OrbShaders.ts`
- `src/app/types.ts`
- `src/app/constants.ts` (optional starter theme)

## 3. Keep the relative file structure

You can use any folder name, but keep these relative imports intact unless you
update import paths in `VoiceOrb.tsx`.

```text
src/
  voice-orb/
    components/
      VoiceOrb.tsx
      Canvas2DOrb.tsx
      OrbShaders.ts
    types.ts
    constants.ts
```

## 4. Render the orb in a sized container

`VoiceOrb` uses absolute positioning, so the parent must define dimensions and
use `position: relative`.

```tsx
import { useState } from 'react';
import { VoiceOrb } from './voice-orb/components/VoiceOrb';
import { INITIAL_CONFIG } from './voice-orb/constants';
import type { OrbState } from './voice-orb/types';

export default function AssistantView() {
  const [state, setState] = useState<OrbState>('idle');

  return (
    <section style={{ position: 'relative', width: '100%', height: 420 }}>
      <VoiceOrb currentState={state} config={INITIAL_CONFIG} size="hero" />
    </section>
  );
}
```

## 5. Map voice lifecycle to orb states

Recommended mapping:

- `idle`: waiting for user input
- `listening`: microphone is active
- `processing`: STT/LLM/tooling is running
- `speaking`: TTS/playback is active
- `error`: mic/network/model/tool failure

## 6. Update the state from your voice pipeline

```tsx
setState('listening');  // mic started
setState('processing'); // request in-flight
setState('speaking');   // tts started
setState('idle');       // playback done
// setState('error');   // on failure
```

## 7. Customize look and behavior

Each state in config controls:

- `colorA`, `colorB`, `colorC`: orb palette and glow
- `speed`: animation speed
- `intensity`: shader/noise intensity

Example override:

```tsx
const customConfig = {
  ...INITIAL_CONFIG,
  listening: {
    ...INITIAL_CONFIG.listening,
    colorB: '#22D3EE',
    speed: 0.65,
  },
};
```

## 8. Choose a size preset

- `hero`: main assistant surface
- `float`: side panel or compact widget
- `mini`: small status indicator

## 9. Fallback behavior

- WebGL-capable devices use the Three.js shader orb.
- Non-WebGL devices automatically use the Canvas 2D fallback.

No extra code is needed for fallback handling.

## 10. Production checklist

- Keep orb mounted in a sized parent (`relative` + width/height).
- Debounce very noisy backend state updates.
- Surface failures with `error` for clear UX feedback.
- Test on at least one mobile browser and one low-end device.

## Starter Kit Zip

For fastest setup, download the starter package from this repo:

- `starter-kit/voice-orb-starter-kit.zip`

It contains a copy-ready `src/voice-orb` folder and quick-start notes.
