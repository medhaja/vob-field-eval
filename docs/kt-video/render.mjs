// Render composition.html to out/kt-video.mp4 with the narration, plus captions and chapters.
//
//   node render.mjs            render + mux + write outputs
//   node render.mjs --serve    serve this folder for preview: http://127.0.0.1:8123/composition.html?preview
//   node render.mjs --frames 0,12.5,100   save single PNG frames to out/frames/ (for checking)
//
// Frames are produced by calling window.renderAt(t) for t = i / fps and piping PNG screenshots
// straight into ffmpeg; nothing is written per frame.

import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "out");
const args = process.argv.slice(2);
const FFMPEG = process.env.FFMPEG || "ffmpeg";

// ---- static server (local only) ----
const TYPES = { ".html": "text/html", ".json": "application/json", ".js": "text/javascript", ".wav": "audio/wav", ".css": "text/css" };
function serve(port = 0) {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/^\/+/, "");
    const file = path.resolve(HERE, rel || "composition.html");
    if (!file.startsWith(HERE) || file.includes(`${path.sep}.venv`) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404); res.end(); return;
    }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream", "cache-control": "no-store" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((ok) => server.listen(port, "127.0.0.1", () => ok(server)));
}

// ---- browser: use Playwright's Chromium; fall back to any installed ms-playwright build ----
async function launch() {
  try {
    return await chromium.launch();
  } catch (err) {
    const base = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), process.platform === "win32" ? "AppData/Local/ms-playwright" : ".cache/ms-playwright");
    const dirs = fs.existsSync(base) ? fs.readdirSync(base).filter((d) => /^chromium-\d+$/.test(d)).sort((a, b) => +b.split("-")[1] - +a.split("-")[1]) : [];
    for (const d of dirs) {
      for (const exe of ["chrome-win64/chrome.exe", "chrome-win/chrome.exe", "chrome-linux64/chrome", "chrome-linux/chrome", "chrome-mac/Chromium.app/Contents/MacOS/Chromium"]) {
        const p = path.join(base, d, exe);
        if (fs.existsSync(p)) return chromium.launch({ executablePath: p });
      }
    }
    throw err;
  }
}

async function openPage(port) {
  const browser = await launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on("console", (m) => { if (m.type() === "error") console.error("[page]", m.text()); });
  page.on("pageerror", (e) => console.error("[page]", e.message));
  await page.goto(`http://127.0.0.1:${port}/composition.html`);
  const info = await page.evaluate(() => window.ready);
  return { browser, page, info };
}

// ---- audio: concatenate scene WAVs, each followed by its padding ----
function readWav(file) {
  const b = fs.readFileSync(file);
  let off = 12, fmt = null, data = null;
  while (off < b.length) {
    const id = b.toString("ascii", off, off + 4), size = b.readUInt32LE(off + 4);
    if (id === "fmt ") fmt = { channels: b.readUInt16LE(off + 10), rate: b.readUInt32LE(off + 12), bits: b.readUInt16LE(off + 22) };
    if (id === "data") data = b.subarray(off + 8, off + 8 + size);
    off += 8 + size + (size % 2);
  }
  if (!fmt || fmt.bits !== 16 || fmt.channels !== 1) throw new Error(`${file}: expected 16-bit mono PCM`);
  return { ...fmt, data };
}
function writeNarration(timing, file) {
  const parts = [];
  let rate = timing.sample_rate;
  for (const sc of timing.scenes) {
    const w = readWav(path.join(HERE, "audio", `scene_${sc.id}.wav`));
    rate = w.rate;
    const want = Math.round(sc.duration * rate) * 2;  // scene length incl. padding, in bytes
    const buf = Buffer.alloc(want);
    w.data.copy(buf, 0, 0, Math.min(w.data.length, want));
    parts.push(buf);
  }
  const data = Buffer.concat(parts);
  const h = Buffer.alloc(44);
  h.write("RIFF", 0); h.writeUInt32LE(36 + data.length, 4); h.write("WAVE", 8); h.write("fmt ", 12);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(rate, 24);
  h.writeUInt32LE(rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write("data", 36); h.writeUInt32LE(data.length, 40);
  fs.writeFileSync(file, Buffer.concat([h, data]));
  return data.length / 2 / rate;
}

// ---- captions / chapters ----
const CHAPTERS = { "01": "Why it exists", "02": "Architecture", "03": "Trace: extraction", "04": "Trace: routing",
  "05": "Trace: review", "06": "Eval & A/B", "07": "Run it & gotchas", "08": "Recap", "09": "Thank you" };
function ytTime(s) { s = Math.floor(s); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; }
function writeChapters(timing, file) {
  const txt = timing.scenes.map((s) => `${ytTime(s.start)} ${CHAPTERS[s.id] || s.title}`).join("\n") + "\n";
  fs.writeFileSync(file, txt);
  return txt;
}
function srtToVtt(srt) {
  return "WEBVTT\n\n" + srt.replace(/\r/g, "").replace(/(\d\d:\d\d:\d\d),(\d\d\d)/g, "$1.$2").trim() + "\n";
}

function run(cmd, argv, opts = {}) {
  return new Promise((ok, bad) => {
    const p = spawn(cmd, argv, { stdio: ["ignore", "inherit", "inherit"], ...opts });
    p.on("exit", (c) => (c === 0 ? ok() : bad(new Error(`${cmd} exited ${c}`))));
  });
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  if (args[0] === "--serve") {
    const s = await serve(8123);
    console.log("Preview: http://127.0.0.1:8123/composition.html?preview   (Ctrl+C to stop)");
    const timing = JSON.parse(fs.readFileSync(path.join(HERE, "timing.json"), "utf8"));
    writeNarration(timing, path.join(OUT, "narration.wav"));
    return s;
  }
  const server = await serve(0);
  const port = server.address().port;
  const { browser, page, info } = await openPage(port);
  const cdp = await page.context().newCDPSession(page);
  const shot = async () => Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png", optimizeForSpeed: true })).data, "base64");

  try {
    if (args[0] === "--frames") {
      const dir = path.join(OUT, "frames");
      fs.mkdirSync(dir, { recursive: true });
      for (const t of args[1].split(",").map(Number)) {
        await page.evaluate((x) => window.renderAt(x), t);
        const f = path.join(dir, `frame_${t.toFixed(2).padStart(7, "0")}.png`);
        fs.writeFileSync(f, await shot());
        console.log(f);
      }
      return;
    }
    const timing = JSON.parse(fs.readFileSync(path.join(HERE, "timing.json"), "utf8"));
    const fps = timing.fps;
    const narration = path.join(OUT, "narration.wav");
    const audioDur = writeNarration(timing, narration);
    const frames = Math.round(timing.total * fps);
    const mp4 = path.join(OUT, "kt-video.mp4");
    console.log(`Rendering ${frames} frames (${(frames / fps).toFixed(2)} s video, ${audioDur.toFixed(2)} s audio)`);
    const ff = spawn(FFMPEG, ["-y", "-loglevel", "error",
      "-f", "image2pipe", "-framerate", String(fps), "-c:v", "png", "-i", "-",
      "-i", narration,
      "-map", "0:v", "-map", "1:a",
      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", process.env.CRF || "20", "-preset", "veryfast",
      "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", mp4], { stdio: ["pipe", "inherit", "inherit"] });
    const done = new Promise((ok, bad) => ff.on("exit", (c) => (c === 0 ? ok() : bad(new Error(`ffmpeg exited ${c}`)))));
    const t0 = Date.now();
    for (let i = 0; i < frames; i++) {
      await page.evaluate((x) => window.renderAt(x), i / fps);
      const png = await shot();
      if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once("drain", r));
      if (i % 300 === 0) console.log(`  frame ${i}/${frames}  (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
    }
    ff.stdin.end();
    await done;

    // Side outputs
    fs.copyFileSync(path.join(HERE, "captions.srt"), path.join(OUT, "captions.srt"));
    const chapters = writeChapters(timing, path.join(OUT, "chapters.txt"));
    // Committed copies
    fs.copyFileSync(mp4, path.join(HERE, "kt-video.mp4"));
    fs.copyFileSync(path.join(OUT, "chapters.txt"), path.join(HERE, "chapters.txt"));
    fs.writeFileSync(path.join(HERE, "captions.vtt"), srtToVtt(fs.readFileSync(path.join(HERE, "captions.srt"), "utf8")));
    await run(FFMPEG, ["-y", "-loglevel", "error", "-ss", "2.5", "-i", mp4, "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "3", path.join(HERE, "poster.jpg")]);
    const mb = fs.statSync(mp4).size / 1e6;
    console.log(`\nWrote ${mp4} (${mb.toFixed(1)} MB)\n${chapters}`);
    if (mb > 20) console.warn("Video is over 20 MB: re-run with a higher CRF, e.g. CRF=24 node render.mjs");
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
