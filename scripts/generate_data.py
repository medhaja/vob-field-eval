"""Generate the seeded synthetic case set and write it to data/cases.jsonl."""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vobeval.generator import SEED, generate, write_cases  # noqa: E402


def main() -> None:
    cases = generate(SEED)
    path = write_cases(cases)
    scenarios = Counter(c.scenario for c in cases)
    print(f"Wrote {len(cases)} synthetic cases to {path}")
    print("Scenarios:", dict(sorted(scenarios.items())))


if __name__ == "__main__":
    main()
