"""engine.strategies.httpx_html._decode — cfg.encoding 명시 시 raw bytes 를 그 charset 으로 디코드.

euc-kr/cp949 한국 사이트(humoruniv 등): httpx 의 charset 자동검출이 meta-only euc-kr 을 utf-8 로
오판해 mojibake → cfg.encoding 으로 강제 디코드. 미명시면 r.text (기존 동작).
"""
from __future__ import annotations


class _FakeResp:
    def __init__(self, content: bytes, text: str):
        self.content = content
        self.text = text


class _FakeAdapter:
    def __init__(self, cfg: dict):
        self.cfg = cfg


def run() -> list[tuple[str, bool, str]]:
    from engine.strategies.httpx_html import _decode
    cases: list[tuple[str, bool, str]] = []

    ko = "친오빠 결혼식에서"
    euckr_bytes = ko.encode("euc-kr")
    # httpx 가 utf-8 로 잘못 디코드한 mojibake (encoding 미명시 시 r.text 가 이렇게 됨)
    mojibake = euckr_bytes.decode("utf-8", errors="replace")

    # 1. encoding=euc-kr → raw bytes 를 euc-kr 로 디코드 → 정상 한글.
    out = _decode(_FakeAdapter({"encoding": "euc-kr"}), _FakeResp(euckr_bytes, mojibake))
    cases.append(("euckr_decodes_correctly", ko in out, f"got {out[:20]!r}"))

    # 2. encoding 미명시 → r.text 그대로 (기존 동작 보존).
    out2 = _decode(_FakeAdapter({}), _FakeResp(euckr_bytes, mojibake))
    cases.append(("no_encoding_uses_rtext", out2 == mojibake, f"got {out2[:20]!r}"))

    # 3. cp949 도 동작.
    cp = "한글테스트"
    out3 = _decode(_FakeAdapter({"encoding": "cp949"}), _FakeResp(cp.encode("cp949"), ""))
    cases.append(("cp949_decodes", cp in out3, f"got {out3[:20]!r}"))

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({msg})")
        fail += 0 if ok else 1
    raise SystemExit(0 if fail == 0 else 1)
