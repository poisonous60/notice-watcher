"""CSS component class extract — engine/digest.py:_extract_css_component_classes.

raw HTML 의 inline `<style>` rule 에서 component class 추출. SPA hydration row 단서.
utility/chrome/generic class reject. 2026-05-25 Radiolab plan.
"""
from __future__ import annotations


covers: list[str] = []


_RADIOLAB_SAMPLE = """
<html>
  <head>
    <style>
      .radiolab-card.v-card .card-title-link .h2 { font-size: 16px; }
      .radiolab-card.v-card .card-title-link .h2:after { background: #fff; }
      .radiolab-card.v-card .card-blurb { line-height: 20px; }
      .radiolab-card.v-card .card-blurb h1 { color: black; }
      .radiolab-card.v-card .card-blurb a { color: blue; }
      .radiolab-card.v-card .card-blurb p { margin: 1em; }
      .radiolab-card.v-card .card-podcasts { display: flex; }
      .radiolab-card.v-card { padding: 1rem; }
      .card-title-link { text-decoration: none; }
      .v-card { border-radius: 8px; }
      .v-card .mb-6 { margin-bottom: 1rem; }
      .nav .menu-item { color: gray; }
      .p-skeleton { background: gray; }
      .container .col-12 { width: 100%; }
      .mb-6 { margin-bottom: 1.5rem; }
      .lg\\:col-4 { width: 33%; }
    </style>
  </head>
  <body><div id="__nuxt"><div class="container">empty</div></div></body>
</html>
"""


def run() -> list[tuple[str, bool, str]]:
    from engine.digest import (
        _extract_css_component_classes,
        _is_blocked_css_class,
    )

    cases: list[tuple[str, bool, str]] = []

    # blocklist
    blocked = ["mb-6", "col-12", "p-skeleton", "p-component", "p-button",
               "nav", "header", "footer", "skeleton", "loading", "placeholder",
               "container", "wrapper", "main", "content", "btn", "btn-primary",
               "text-center", "bg-white", "flex", "grid",
               "sm:col-6", "lg:col-4", "rounded", "shadow", "truncate"]
    for cls in blocked:
        cases.append((f"blocklist_{cls.replace(':', '_').replace('-', '_')}",
                      _is_blocked_css_class(cls),
                      f"{cls!r} should be blocked"))

    # allow (real component class)
    allowed = ["radiolab-card", "card-title-link", "card-blurb", "episode-card",
               "podcast-item", "v-card", "card-podcasts", "post-card-title"]
    for cls in allowed:
        cases.append((f"allow_{cls.replace('-', '_')}",
                      not _is_blocked_css_class(cls),
                      f"{cls!r} should be allowed"))

    # extract from Radiolab-like sample
    classes = _extract_css_component_classes(_RADIOLAB_SAMPLE)
    cases.append(("radiolab_extracts_some", len(classes) > 0, f"got {classes!r}"))

    # top should include radiolab-card (highest frequency)
    class_names = [c["class"] for c in classes]
    cases.append(("radiolab_card_top", "radiolab-card" in class_names,
                  f"got {class_names!r}"))

    # utility/chrome must be filtered out
    for bad in ["mb-6", "col-12", "p-skeleton", "container", "lg:col-4", "nav"]:
        cases.append((f"radiolab_excludes_{bad.replace(':', '_').replace('-', '_')}",
                      bad not in class_names,
                      f"unwanted {bad!r} in {class_names!r}"))

    # output schema
    first = classes[0] if classes else {}
    cases.append(("schema_has_class", "class" in first, f"got {first!r}"))
    cases.append(("schema_has_rule_count", "rule_count" in first and first.get("rule_count", 0) >= 2,
                  f"got {first!r}"))
    cases.append(("schema_has_co_classes", isinstance(first.get("co_classes"), list),
                  f"got {first!r}"))
    cases.append(("co_classes_cap_3", len(first.get("co_classes") or []) <= 3,
                  f"got {first!r}"))

    # frequency threshold — class appearing only once should be excluded
    only_once_html = "<html><head><style>.unique-name { color: red; }</style></head></html>"
    cases.append(("min_freq_excludes_singleton",
                  _extract_css_component_classes(only_once_html) == [],
                  ""))

    # empty/null safe
    cases.append(("empty_html_returns_empty",
                  _extract_css_component_classes("") == [], ""))
    cases.append(("none_html_returns_empty",
                  _extract_css_component_classes(None) == [], ""))
    cases.append(("no_style_returns_empty",
                  _extract_css_component_classes("<html><body>no style</body></html>") == [], ""))

    # top_n cap
    big_html = "<html><head><style>" + "".join(
        f".comp-{i} {{ color: red; }} .comp-{i} a {{ color: blue; }}" for i in range(20)
    ) + "</style></head></html>"
    big_out = _extract_css_component_classes(big_html, top_n=5)
    cases.append(("top_n_cap_5", len(big_out) <= 5, f"got {len(big_out)} items"))

    return cases
