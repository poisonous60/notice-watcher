"""engine.digest.compress_html_for_prompt — LLM 프롬프트 입력 전용 lossless 토큰 압축.

selector 신호(tag/class/id/href/구조) 보존하면서 토큰 줄이는지 검증:
  T1 반복형제 collapse — 동일구조 형제 keep_siblings 만 남기고 주석 + 나머지 제거.
  T2 긴 text 노드 cap — <a> 자손 text(제목/post_id 소스)는 제외.
  T3 data-*/aria-* 값 cap — class/id/href 불가침, 숫자-only 값 미절단.

핵심 안전 (codex 리뷰 B1): 핀/공지 row(다른 class 또는 data-* 키)는 정상 row 와 안 합쳐짐.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from engine.digest import compress_html_for_prompt


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, msg: str = "") -> None:
        cases.append((name, ok, msg))

    # T1 — 동일구조 li 50개 → 3개 + collapse 주석
    html = "<ul>" + "".join(
        f'<li class="item"><a href="/p/{i}">제목 {i}</a></li>' for i in range(50)
    ) + "</ul>"
    out = compress_html_for_prompt(html, keep_siblings=3)
    soup = BeautifulSoup(out, "lxml")
    n_li = len(soup.select("li.item"))
    has_marker = "collapsed 47 similar" in out
    check("t1_collapse_50_to_3", n_li == 3 and has_marker,
          f"li 수={n_li} (기대 3), marker={has_marker}")
    # class·href 보존 (첫 예시)
    first = soup.select_one("li.item a")
    check("t1_preserves_class_href",
          first is not None and first.get("href") == "/p/0",
          f"first a href={first.get('href') if first else None}")

    # T1 — 핀/공지 row(다른 class)는 안 합쳐짐
    html2 = ('<ul><li class="item notice"><a href="/n/1">공지</a></li>'
             + "".join(f'<li class="item"><a href="/p/{i}">글{i}</a></li>' for i in range(10))
             + "</ul>")
    out2 = compress_html_for_prompt(html2, keep_siblings=3)
    soup2 = BeautifulSoup(out2, "lxml")
    notice_kept = soup2.select_one("li.notice") is not None
    check("t1_pinned_row_not_merged", notice_kept,
          f"공지 row 보존={notice_kept}")

    # T1 — data-* 키로만 구분되는 핀 row 도 안 합쳐짐 (signature 에 data-* 키 포함)
    html3 = ('<ul><li class="item" data-pin="1"><a href="/n/1">고정</a></li>'
             + "".join(f'<li class="item"><a href="/p/{i}">글{i}</a></li>' for i in range(10))
             + "</ul>")
    out3 = compress_html_for_prompt(html3, keep_siblings=3)
    soup3 = BeautifulSoup(out3, "lxml")
    pin_kept = soup3.select_one("li[data-pin]") is not None
    check("t1_data_key_pin_not_merged", pin_kept,
          f"data-pin row 보존={pin_kept}")

    # T2 — 긴 text 노드 cap, 단 <a> 안 제목은 미절단
    long_title = "가" * 400
    long_body = "나" * 400
    html4 = f'<div><a href="/p/1">{long_title}</a><p>{long_body}</p></div>'
    out4 = compress_html_for_prompt(html4, text_cap=200)
    a_intact = long_title in out4
    p_capped = long_body not in out4 and ("나" * 200 + "…") in out4
    check("t2_anchor_text_not_capped", a_intact, "a 제목 절단됨" if not a_intact else "")
    check("t2_long_body_capped", p_capped, "p 본문 미절단" if not p_capped else "")

    # T3 — data-* 긴 값 cap, class/href 불가침, 숫자-only 미절단
    big = "x" * 200
    html5 = (f'<div class="keep" id="kid" data-blob="{big}" '
             f'data-id="123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890" '
             f'href="/keep">t</div>')
    out5 = compress_html_for_prompt(html5, attr_cap=80)
    soup5 = BeautifulSoup(out5, "lxml")
    el = soup5.select_one("div.keep")
    blob_capped = el is not None and len(el.get("data-blob", "")) <= 81 and el.get("data-blob", "").endswith("…")
    class_intact = el is not None and "keep" in (el.get("class") or [])
    id_intact = el is not None and el.get("id") == "kid"
    numeric_intact = el is not None and el.get("data-id", "").isdigit() and len(el.get("data-id", "")) == 90
    check("t3_data_value_capped", blob_capped, f"data-blob len={len(el.get('data-blob','')) if el else 0}")
    check("t3_class_id_intact", class_intact and id_intact, f"class/id 손상")
    check("t3_numeric_data_not_capped", numeric_intact,
          f"숫자 data-id 절단됨 len={len(el.get('data-id','')) if el else 0}")

    # 빈 입력 안전
    check("empty_input", compress_html_for_prompt("") == "", "빈 입력 처리")

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {name}  ({msg})")
        if not ok:
            fail += 1
    raise SystemExit(0 if fail == 0 else 1)
