# Result

## 변경 파일

- `probe/diagnose.py`: hydration placeholder verdict downgrade gate 추가.
- `scripts/register.py`: 새 hydration prefix를 static insufficient prompt hint에 연결.
- `tests/probe_heuristics/test_verdict_hydration_downgrade.py`: PUBG-shaped placeholder fixture와 SSR counterexample 추가.
- `docs/cases/_generic_c-layer_verdict_hydration_2026-05-28.md`: generic C-layer case 추가.
- `docs/cases/host_pubg-com_news_17f4ebc1.md`: verdict hydration downgrade follow-up 추가.

## 요약

정적 HTML에 row selector가 반복되지만 article href가 없고, rendered payload에는 `first_article_url`이 있는 경우를 JS hydration placeholder로 판정한다. 이때 `static_ok`/`captured_ok`를 무효화해 verdict가 `정적 HTTP로 충분`으로 남지 않게 하고, register feedback은 기존 Playwright 유도 힌트 경로를 재사용한다.

## 검증

- RED: `python scripts/probe_smoke.py --stage 5 --verbose` -> exit 1. 새 hydration fixture 3건이 현재 `정적 HTTP로 충분`/`httpx (S1.H2)`로 실패.
- GREEN: `python scripts/probe_smoke.py --stage 5 --verbose` -> exit 0. `143 파일 · 1488 케이스 · 0 FAIL · coverage 49/49`.
- 최종 `python scripts/probe_smoke.py --stage 3 --stage 5` -> exit 0. `306 / 306 OK`, `143 파일 · 1488 케이스 · 0 FAIL · coverage 49/49`, summary `PASS 1795 FAIL 0 WARN 1 SKIP 0`.
- `python scripts/vocab_lint.py` -> exit 0. `[vocab_lint] OK: scanned 428 file(s), 23 high-confidence rule(s)`.

## pubg artifact verdict

`output/probe/host_pubg-com_news_17f4ebc1/` 가 이 worktree에 없어 real artifact replay는 수행하지 못했다. N100 pull/tar도 이번 hard-stop 범위 밖이라 하지 않았다.

## case 파일

- `docs/cases/_generic_c-layer_verdict_hydration_2026-05-28.md`
- `docs/cases/host_pubg-com_news_17f4ebc1.md`

## deferred

- Claude/main thread에서 pubg real artifact replay 가능.
- `docs/cases/INDEX.md` / `output/cases.sqlite3` backfill은 Claude/main thread 영역.
