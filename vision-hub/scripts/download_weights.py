#!/usr/bin/env python3
"""Download model weights ahead of time (for offline use) and record their SHA-256.

Run from the project root with the backend virtual environment:

    backend/.venv/bin/python scripts/download_weights.py              # everything (~820 MB)
    backend/.venv/bin/python scripts/download_weights.py --skip-large # YOLO pose only (~26 MB)
    backend/.venv/bin/python scripts/download_weights.py human_pose   # one model

Weights go to backend/model_weights/. Each file's SHA-256 is computed after the
download and stored next to it (<file>.sha256); analysis jobs record these hashes.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
os.environ["ALLOW_MODEL_DOWNLOAD"] = "true"

from app.vision import weights  # noqa: E402
from app.vision.model_registry import registry  # noqa: E402

LARGE_MB = 100


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="*", help="model ids (default: all registered models)")
    parser.add_argument("--skip-large", action="store_true", help=f"skip weights larger than {LARGE_MB} MB")
    args = parser.parse_args()

    specs = registry.specs()
    if args.models:
        unknown = set(args.models) - {s.model_id for s in specs}
        if unknown:
            print(f"Unknown model(s): {', '.join(sorted(unknown))}. Available: {', '.join(registry.ids())}")
            return 2
        specs = [s for s in specs if s.model_id in args.models]

    failed = 0
    for spec in specs:
        if not spec.weights:
            print(f"- {spec.model_id}: no weights needed")
            continue
        for w in spec.weights:
            if args.skip_large and (w.size_mb or 0) > LARGE_MB and not weights.is_present(w):
                print(f"- {spec.model_id}: skipped {w.name} (~{w.size_mb:.0f} MB)")
                continue
            try:
                path = weights.ensure_weights(w)
                print(f"✓ {spec.model_id}: {w.name}  sha256={weights.sha256_of(w)}  ({path})")
            except Exception as exc:  # keep going with the others
                failed += 1
                print(f"✗ {spec.model_id}: {w.name} failed: {getattr(exc, 'message', exc)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
