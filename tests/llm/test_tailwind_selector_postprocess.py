"""register.py selector post-processing for Tailwind utility-heavy rows."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _load_register():
    rp = Path(__file__).resolve().parent.parent.parent / "scripts" / "register.py"
    spec = importlib.util.spec_from_file_location("reg_selector_under_test", rp)
    reg = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(reg)
    return reg


def run() -> list[tuple[str, bool, str]]:
    reg = _load_register()
    cases: list[tuple[str, bool, str]] = []

    noisy = "div.grid.w-full.relative.gap-6.md:grid-cols-2.xl:grid-cols-3.pt-5 > article.news-card.storyblok__outline"
    simplified = reg._simplify_tailwind_row_selector(noisy)
    cases.append((
        "tailwind_variant_classes_removed",
        simplified == "div.grid > article.news-card.storyblok__outline",
        f"got {simplified!r}",
    ))

    cfg = {
        "version": 1,
        "site": "wayforward.com",
        "board": "news",
        "strategy": "httpx_html",
        "list": {
            "url_template": "https://wayforward.com/news/",
            "row_selector": noisy,
            "fields": {
                "post_id": [{"from": "css", "selector": "a", "attr": "href"}],
                "title": [{"from": "css", "selector": "h2", "text": True}],
            },
        },
    }
    out = reg._make_cfg_post_processor({"url": "https://wayforward.com/news/"})(cfg)
    cases.append((
        "post_processor_rewrites_row_selector",
        out["list"]["row_selector"] == "div.grid > article.news-card.storyblok__outline",
        f"got {out['list']['row_selector']!r}",
    ))

    return cases


if __name__ == "__main__":
    failed = False
    for name, ok, msg in run():
        print(("PASS" if ok else "FAIL"), name, "-", msg)
        failed = failed or not ok
    raise SystemExit(1 if failed else 0)
