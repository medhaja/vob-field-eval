# Walkthrough video

A narrated, animated walkthrough of this codebase (about 4 minutes). Everything is built locally: the
narration uses [Kokoro](https://github.com/hexgrad/kokoro) text-to-speech on this machine, and the frames are
rendered from an HTML page with Playwright and encoded with ffmpeg.

| File | What it is |
|---|---|
| `kt-video.mp4` | The rendered video (H.264 + AAC) |
| `captions.vtt`, `chapters.txt`, `poster.jpg` | Captions, YouTube-style chapters, preview frame |
| `outline.md`, `script.md` | Scene plan, narration, on-screen beats, and a source reference for every claim |
| `tts.py` | Narration → `audio/scene_XX.wav`, `timing.json` (scene timing + word timestamps), `captions.srt` |
| `scene_data.py` → `scene_data.json` | Real numbers and one real synthetic case pulled from the prototype |
| `composition.html` | All scenes at 1920×1080; `window.renderAt(t)` draws the exact frame for time `t` |
| `render.mjs` | Renders every frame at 30 fps, pipes PNGs into ffmpeg, muxes the narration, writes `out/` |
| `build.mjs` | Runs the whole pipeline (`npm run kt-video`) |

## Requirements

- Python 3.10–3.12 with a venv in `.venv` (`pip install -r requirements.txt`), and `espeak-ng` on the PATH
- Node 18+ (`npm install`) with a Playwright Chromium (`npx playwright install chromium` if none is installed)
- ffmpeg on the PATH

## Build

```bash
cd docs/kt-video
npm install
npm run kt-video      # narration -> timing -> frames -> out/kt-video.mp4, then copies the committed outputs
```

Outputs land in `out/` (`kt-video.mp4`, `captions.srt`, `chapters.txt`, `narration.wav`). The build then copies
the video, chapters, WebVTT captions and a poster frame next to this README. If the video is over 20 MB, re-run
the render with a higher CRF: `CRF=24 node render.mjs`.

## Edit a scene

1. **Change the words:** edit the scene's **Narration** in `script.md`. Spell out anything hard to pronounce
   ("S-Q-Lite", "C-P-T"). Then regenerate only that scene's audio and the timing:
   `.venv/Scripts/python.exe tts.py 04` (use `.venv/bin/python` on macOS/Linux).
2. **Change the visuals:** each scene is one builder function in `composition.html` (search for `// 04 ·`).
   Beats are tied to phrases in the narration with `S("phrase")`, which looks up Kokoro's word timestamps, so
   the animation follows the audio when the wording changes. A phrase that no longer exists shows a red error
   on the page and stops the render.
3. **Preview:** `npm run preview`, then open http://127.0.0.1:8123/composition.html?preview to play or scrub.
   Single frames for a quick look: `node render.mjs --frames 12.5,100` (written to `out/frames/`).
4. **Render:** `node render.mjs` (or `npm run kt-video` to also regenerate all the audio).

If the prototype's data or logic changes, refresh the numbers with `python docs/kt-video/scene_data.py` from
the repo root (it uses the project's own dependencies), then re-check the claims in `script.md`.

Rendering is deterministic: no CSS transitions, no timers and no randomness affect a frame, so the same inputs
give the same video.
