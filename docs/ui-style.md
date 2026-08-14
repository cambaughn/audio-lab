# Approved UI direction — vintage industrial IMAX console

Inherited from Identity Lab v0.1.0 (`docs/ui-style.md`, recorded 2026-07-30);
adopted unchanged for Audio Lab with voice-panel additions. Reference: an
IMAX projection console — an old but highly reliable industrial control
panel with amber-on-black display.

## Desired qualities

- Predominantly black background
- Monochrome amber/yellow foreground
- Thin amber borders, separators, and outlined controls
- Dense but orderly instrument-panel composition
- Mostly square corners or very small corner radii
- Blocky terminal / industrial display typography (Menlo-family monospace)
- Uppercase operational labels where appropriate
- Compact status readouts and grouped control regions
- Clear operational states, e.g.:
  - `MIC OFFLINE` / `MIC ARMED` / `RECORDING`
  - `MODEL LOADING` / `SYSTEM READY`
  - `SPEAKER: CAMERON 0.61`
  - `SPEAKER: PROBABLY CAMERON — PRIVATE ACCESS DENIED`
  - `SPEAKER: UNKNOWN`
  - `SCOPE: PRIVATE / CAMERON`
  - `LLM: THINKING` / `TTS: SPEAKING`
  - `ENROLLMENT 3 / 6`

## Avoid (this is not generic neon cyberpunk)

- Blue or purple neon; glassmorphism; large rounded modern cards
- Gradients as decoration; excessive animation
- Fake malfunction effects; strong scanlines, distortion, flicker, noise
- Sacrificing usability to imitate an old display

The result should feel like an old professional machine that remains
dependable and legible — modern interaction behavior and accessibility
underneath the visual treatment.

## Implementation notes

Visual tokens are centralized in `audio_lab/ui/theme.py`, ported verbatim
from Identity Lab: `BG #0b0a07`, `BG_PANEL #0f0d09`, `AMBER #ffb000`,
`AMBER_DIM #9c7420`, `AMBER_FAINT #4a3a14`, `ERROR #ff4f30`, 1 px borders,
2 px radius, Menlo/SF Mono stack. Appearance is adjusted only in the theme
module, never in individual widgets.

Voice-specific additions (Batch 1+): a level meter + rolling waveform
widget drawn in the same idiom (thin amber strokes on black, dim amber for
history), and a large square `HOLD TO TALK (SPACE)` push-to-talk control.
The consent banner, mic errors, and destructive confirmations must remain
clearly legible with sufficient contrast.
