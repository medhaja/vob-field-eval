"""Command line entry point.

    python -m vobeval demo      generate data, run v1 + v2, start the UI on :8000
    python -m vobeval generate  regenerate data/cases.jsonl
    python -m vobeval run       reload cases into SQLite and run both prompt versions
    python -m vobeval serve     start the UI only
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter


def _generate() -> None:
    from .generator import SEED, generate, write_cases

    cases = generate(SEED)
    path = write_cases(cases)
    edge = sum(c.scenario != "standard" for c in cases)
    print(f"Generated {len(cases)} synthetic cases ({edge} edge cases) -> {path}")
    print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(Counter(c.scenario for c in cases).items())))


def _run() -> None:
    from .llm_extractor import llm_model
    from .pipeline import run
    from .store import DEFAULT_DB, Store

    counts = run(Store(DEFAULT_DB))
    for k, v in counts.items():
        print(f"Extracted {v} cases with {k}")
    if not llm_model():
        print("LITELLM_MODEL not set: using the deterministic mock extractor only.")


def _port_free(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0


def _serve(host: str, port: int) -> None:
    import uvicorn

    print(f"\nVOB Field Eval running at http://{host}:{port}  (Ctrl+C to stop)\n")
    uvicorn.run("vobeval.app:create_app", factory=True, host=host, port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(prog="vobeval")
    parser.add_argument("command", choices=["demo", "generate", "run", "serve"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command in ("demo", "serve") and not _port_free(args.host, args.port):
        sys.exit(f"Port {args.port} is already in use. Try: make demo PORT=8010"
                 f"  (or python -m vobeval {args.command} --port 8010)")
    if args.command in ("demo", "generate"):
        _generate()
    if args.command in ("demo", "run"):
        _run()
    if args.command in ("demo", "serve"):
        _serve(args.host, args.port)


if __name__ == "__main__":
    main()
