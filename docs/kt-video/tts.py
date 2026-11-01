"""Generate the narration audio, timing.json and captions.srt from script.md.

Runs Kokoro locally (voice af_heart, 24 kHz). Each scene's narration is split into
sentences, each sentence is synthesized on its own, and the sentences are joined with a
short pause. That gives exact sentence timestamps; Kokoro's word timestamps are kept
too, so visual beats can sync to specific phrases.

    .venv/Scripts/python.exe tts.py              # all scenes
    .venv/Scripts/python.exe tts.py 03 07        # only these scenes, then rebuild timing
    .venv/Scripts/python.exe tts.py --timing     # rebuild timing.json/captions only
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
SR = 24000
VOICE = "af_heart"
SPEED = 1.06          # slightly brisker than default to keep the video under 4 minutes
SENTENCE_GAP = 0.22   # seconds of silence between sentences
LEAD_IN = 0.15        # silence before the first sentence of a scene
PAD = 0.6             # padding after each scene's audio
CLOSING_HOLD = 3.0    # the closing card stays up this long after its narration

# Spoken spellings in script.md -> how captions should read.
CAPTION_TEXT = [
    ("A-B-A", "ABA"), ("C-P-T", "CPT"), ("V-O-B Result", "VOBResult"), ("S-Q-Lite", "SQLite"),
    ("Lite L-L-M", "LiteLLM"), ("A-P-I", "API"), ("I-D", "ID"), ("extract mock", "extract_mock"),
    ("make demo", "make demo"), ("zero point eight", "0.8"),
]


def parse_script(path: Path = HERE / "script.md") -> list[dict]:
    text = path.read_text(encoding="utf-8")
    scenes = []
    for block in re.split(r"\n## ", text)[1:]:
        head = block.splitlines()[0]
        m = re.match(r"(\d\d)\s*\S\s*(.+)", head)
        narr = re.search(r"\*\*Narration\*\*\s*\n\n(.*?)\n\n\*\*On screen", block, re.S)
        if not m or not narr:
            continue
        scenes.append({"id": m.group(1), "title": m.group(2).strip(),
                       "narration": " ".join(narr.group(1).split())})
    return scenes


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s]


def caption(text: str) -> str:
    for a, b in CAPTION_TEXT:
        text = text.replace(a, b)
    return text


def synthesize(scenes: list[dict]) -> None:
    from kokoro import KPipeline

    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    AUDIO.mkdir(exist_ok=True)
    for sc in scenes:
        chunks = [np.zeros(int(LEAD_IN * SR), dtype=np.float32)]
        t = LEAD_IN
        sents, words, phonemes = [], [], []
        for s in sentences(sc["narration"]):
            start = t
            for res in pipe(s, voice=VOICE, speed=SPEED, split_pattern=None):
                audio = res.audio.numpy() if hasattr(res.audio, "numpy") else np.asarray(res.audio)
                for tok in res.tokens or []:
                    if tok.start_ts is not None and tok.end_ts is not None and tok.text.strip():
                        words.append({"text": tok.text, "start": round(t + tok.start_ts, 3),
                                      "end": round(t + tok.end_ts, 3)})
                phonemes.append(res.phonemes)
                chunks.append(audio.astype(np.float32))
                t += len(audio) / SR
            sents.append({"text": s, "start": round(start, 3), "end": round(t, 3)})
            chunks.append(np.zeros(int(SENTENCE_GAP * SR), dtype=np.float32))
            t += SENTENCE_GAP
        wav = np.concatenate(chunks[:-1])  # drop the trailing gap
        sf.write(AUDIO / f"scene_{sc['id']}.wav", wav, SR, subtype="PCM_16")
        meta = {"id": sc["id"], "sentences": sents, "words": words, "phonemes": phonemes}
        (AUDIO / f"scene_{sc['id']}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        print(f"scene {sc['id']}: {len(wav) / SR:.2f}s")


def srt_time(x: float) -> str:
    ms = int(round(x * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_timing(scenes: list[dict]) -> None:
    out, cues, t = [], [], 0.0
    for i, sc in enumerate(scenes):
        info = sf.info(str(AUDIO / f"scene_{sc['id']}.wav"))
        meta = json.loads((AUDIO / f"scene_{sc['id']}.json").read_text(encoding="utf-8"))
        audio_dur = info.frames / info.samplerate
        last = i == len(scenes) - 1
        dur = audio_dur + (CLOSING_HOLD if last else PAD)
        out.append({
            "id": sc["id"], "title": sc["title"], "start": round(t, 3), "duration": round(dur, 3),
            "audio_duration": round(audio_dur, 3), "pad": round(dur - audio_dur, 3),
            "sentences": meta["sentences"], "words": meta["words"],
        })
        for s in meta["sentences"]:
            cues.append((t + s["start"], t + s["end"], caption(s["text"])))
        t += dur
    timing = {"fps": 30, "width": 1920, "height": 1080, "sample_rate": SR, "voice": VOICE,
              "total": round(t, 3), "scenes": out}
    (HERE / "timing.json").write_text(json.dumps(timing, indent=1), encoding="utf-8")
    srt = "\n".join(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n" for n, (a, b, txt) in enumerate(cues, 1))
    (HERE / "captions.srt").write_text(srt, encoding="utf-8")
    print(f"timing.json: {len(out)} scenes, total {t:.2f}s")


def main(argv: list[str]) -> None:
    scenes = parse_script()
    if "--timing" not in argv:
        only = [a for a in argv if re.fullmatch(r"\d\d", a)]
        synthesize([s for s in scenes if not only or s["id"] in only])
    build_timing(scenes)


if __name__ == "__main__":
    main(sys.argv[1:])
