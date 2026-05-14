"""콘솔 매트릭스 + summary.txt 출력."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ._contract import validate_payload
from .types import Diagnosis, Result


def matrix_lines(results: list[Result]) -> list[str]:
    lines = []
    for r in results:
        notable = "  ".join(r.notable[:3])
        status = r.status if r.status is not None else "-"
        lines.append(f"  {r.strategy:<22} {str(status):<5} {r.classification.value:<22} {notable}")
    return lines


def write_summary(
    *,
    out_dir: Path,
    slug: str,
    url: str,
    baseline: dict[str, Result],
    all_results: list[Result],
    diagnosis: Diagnosis,
    environment: Optional[dict] = None,
) -> None:
    parts: list[str] = []
    parts.append(f"[{slug}]")
    parts.append(f"URL: {url}")
    if environment is not None:
        parts.append(
            f"환경: {environment.get('platform', '?')}  "
            f"outbound={environment.get('outbound_ip_local', '?')}  "
            f"GoodbyeDPI={'ON' if environment.get('goodbyedpi_running') else 'OFF'}"
        )
    parts.append("")
    parts.append("베이스라인:")
    parts.extend(matrix_lines(list(baseline.values())))
    parts.append("")
    parts.append("진입 매트릭스:")
    parts.extend(matrix_lines(all_results))
    parts.append("")
    parts.append(f"Verdict: {diagnosis.verdict}")
    parts.append(f"권장 진입: {diagnosis.recommended_strategy} (헤더: {diagnosis.recommended_headers_summary})")
    parts.append(f"권장 폴링 간격: {diagnosis.recommended_polling_interval_sec}초+")
    parts.append(f"글 목록 후보: {diagnosis.list_candidates_summary}")
    parts.append(f"본문 진입 OK: {diagnosis.article_entry_ok}")
    if diagnosis.notes:
        parts.append("")
        parts.append("Notes:")
        for n in diagnosis.notes:
            parts.append(f"  - {n}")

    text = "\n".join(parts) + "\n"
    (out_dir / "summary.txt").write_text(text, encoding="utf-8")
    print("\n" + text)

    # diagnosis.json
    payload = {
        "slug": slug,
        "url": url,
        "verdict": diagnosis.verdict,
        "recommended_strategy": diagnosis.recommended_strategy,
        "recommended_headers": diagnosis.recommended_headers_summary,
        "recommended_polling_interval_sec": diagnosis.recommended_polling_interval_sec,
        "list_candidates_summary": diagnosis.list_candidates_summary,
        "article_entry_ok": diagnosis.article_entry_ok,
        "notes": diagnosis.notes,
        "results": [r.to_dict() for r in all_results],
        "baseline": {k: v.to_dict() for k, v in baseline.items()},
    }
    validate_payload("diagnosis.json", payload, allow_extra=False)
    (out_dir / "diagnosis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
