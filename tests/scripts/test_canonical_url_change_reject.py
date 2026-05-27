from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path


def _load_register():
    rp = Path(__file__).resolve().parent.parent.parent / "scripts" / "register.py"
    spec = importlib.util.spec_from_file_location("reg_canonical_under_test", rp)
    reg = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(reg)
    return reg


def test_preflight_article_404_with_list_canonical_saves_rejected_hint(monkeypatch, tmp_path):
    reg = _load_register()
    ok, detail = _exercise_canonical_reject(reg, tmp_path, monkeypatch=monkeypatch)
    assert ok, detail


def _exercise_canonical_reject(reg, tmp_path: Path, *, monkeypatch=None) -> tuple[bool, str]:
    slug = "host_blog-filecoin-i_root_4ab2d2a3"
    list_url = "https://blog.filecoin.io/"
    canonical_url = "https://filecoin.io/blog/"
    article_url = "https://blog.filecoin.io/blog/Announcing-Filecoin-ProPGF-Batch-3-General-Track"

    state_dir = tmp_path / "poll_state"
    probe_dir = tmp_path / "probe" / slug
    state_dir.mkdir(parents=True)
    probe_dir.mkdir(parents=True)
    originals = {
        "STATE_DIR": reg.STATE_DIR,
        "output_dir": reg.output_dir,
        "_prune_triage_queue": reg._prune_triage_queue,
        "_append_register_signal_log": reg._append_register_signal_log,
        "_learn_pattern": reg._learn_pattern,
    }
    setters = {
        "STATE_DIR": state_dir,
        "output_dir": lambda s: probe_dir,
        "_prune_triage_queue": lambda *a, **k: None,
        "_append_register_signal_log": lambda *a, **k: None,
        "_learn_pattern": lambda *a, **k: None,
    }
    for name, value in setters.items():
        if monkeypatch is not None:
            monkeypatch.setattr(reg, name, value)
        else:
            setattr(reg, name, value)

    try:
        (probe_dir / "diagnosis.json").write_text(
            json.dumps({
                "url": list_url,
                "results": [
                    {"target": "list", "strategy": "S1.H1", "status": 200, "classification": "OK"}
                ],
            }),
            encoding="utf-8",
        )
        (probe_dir / "list.html").write_text(
            f'<html><head><link rel="canonical" href="{canonical_url}"></head></html>',
            encoding="utf-8",
        )
        (probe_dir / "article.reprobe.json").write_text(
            json.dumps({"url": article_url, "status": 404, "classification": "NOT_FOUND"}),
            encoding="utf-8",
        )

        rc = reg._canonical_url_change_preflight_reject(slug, list_url, {"url": list_url})

        marker = json.loads((state_dir / f"{slug}.REJECTED.json").read_text(encoding="utf-8"))
        ok = (
            rc == 3
            and marker["reason"] == "canonical_url_change"
            and marker["hint"] == canonical_url
            and marker["url"] == list_url
        )
        return ok, f"rc={rc} marker={marker!r}"
    finally:
        if monkeypatch is None:
            for name, value in originals.items():
                setattr(reg, name, value)


def run() -> list[tuple[str, bool, str]]:
    tmp = Path(tempfile.mkdtemp(prefix="canonical_reject_test_"))
    try:
        reg = _load_register()
        ok, detail = _exercise_canonical_reject(reg, tmp)
        return [("canonical_url_change_rejected_with_hint", ok, detail)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    raise SystemExit(0 if not failed else 1)
