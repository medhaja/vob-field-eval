// Whole pipeline: narration (Kokoro, local) -> timing.json/captions -> frames -> MP4.
//   npm run kt-video
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const py = [".venv/Scripts/python.exe", ".venv/bin/python"].map((p) => path.join(HERE, p)).find((p) => fs.existsSync(p));
if (!py) {
  console.error("No venv found. Create it first (Python 3.10-3.12):\n  python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt");
  process.exit(1);
}
const step = (cmd, args) => {
  console.log(`\n> ${path.basename(cmd)} ${args.join(" ")}`);
  const r = spawnSync(cmd, args, { cwd: HERE, stdio: "inherit", env: { ...process.env, PYTHONUTF8: "1" } });
  if (r.status !== 0) process.exit(r.status ?? 1);
};
step(py, ["tts.py"]);
step(process.execPath, ["render.mjs"]);
