"""validate_config.py loads only the digest beside the candidate."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import scripts.validate_config as vc


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="vc_digest_") as td:
        d = Path(td)
        candidate = d / "candidate.json"
        candidate.write_text("{}", encoding="utf-8")
        (d / "digest.json").write_text(json.dumps({"source": "compressed"}), encoding="utf-8")
        got = vc._load_digest_for_candidate(candidate)
        cases.append((
            "loads_neighbor_digest",
            got == {"source": "compressed"},
            f"got={got!r}",
        ))

        (d / "validator_digest.json").write_text(json.dumps({"source": "full"}), encoding="utf-8")
        got = vc._load_digest_for_candidate(candidate)
        cases.append((
            "prefers_validator_digest",
            got == {"source": "full"},
            f"got={got!r}",
        ))

    with tempfile.TemporaryDirectory(prefix="vc_digest_bad_") as td:
        d = Path(td)
        candidate = d / "candidate.json"
        candidate.write_text("{}", encoding="utf-8")
        (d / "digest.json").write_text("{not-json", encoding="utf-8")
        got = vc._load_digest_for_candidate(candidate)
        cases.append((
            "malformed_digest_fails_open",
            got is None,
            f"got={got!r}",
        ))

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({msg})")
        fail += 0 if ok else 1
    raise SystemExit(0 if fail == 0 else 1)
