---
slug: github-releases-recognizer
url: https://github.com/anthropics/claude-code/releases
status: ✅ recognizer 승급 (cluster 19건 → engine/recognizers/github_releases.py)
outcome: improved
date: 2026-05-20
failure_keys: []
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/github_releases.py]
---

## 무엇이 일어났나
batch-register (catalog 2026-05-20 / -b) 가 GitHub repo Releases 페이지 21건을 개별 LLM 생성 →
N100 `configs/host_github-com_*.json`. (dev 박스엔 없었음 — batch worker 가 N100 에서 등록, Rule C 비대칭.
승급 작업 위해 `scp` 로 21건 dev 박스에 내려받아 commit — 동시에 dev↔N100 config sync.)

21건 중 **19건이 `github.com/<owner>/<repo>/releases` 폼**. 나머지 2건은 *다른 종류 페이지*:
- `mattpocock/skills/tree/main` — 소스 트리 디렉터리 리스트 (`url_template=.../tree/main`)
- `openai/codex-plugin-cc` → board `dkundel-openai`, repo 홈 (`url_template=https://github.com/{board}`)

이 2건은 release 가 아니므로 cluster 에서 **제외** (releases recognizer 로 재현 불가 — 다른 DOM).

## 무엇을 바꿨나
recognizer-extension 스킬로 19건 cluster → `engine/recognizers/github_releases.py` (`NAME=github-releases`):
- 정규식 `//github\.com/([^/?#]+)/([^/?#]+)/releases/?(?:[?#].*)?$` — owner/repo 2 segment capture,
  **`/releases` literal + 끝 anchor** 가 유일한 false-match 방어:
  repo 홈·`/issues`·`/pulls`·`/wiki`·`/tree/...`·`/commits`·owner 프로필·`/releases/tag/<ver>`(개별 release) 전부 배제.
- builder: `board=owner/repo` 를 URL path 에서 추출 (저장된 `board` 필드는 신뢰 X — LLM 이 `godot`·`releases`
  처럼 버그 값 생성). `_slug_board=owner_repo`. list/article skeleton 은 repo 불문 동일한 robust selector 상수
  (행 `div[data-hpc] > section` + tag 링크 필수, post_id `/releases/tag/<ver>` href, title `h2.sr-only`,
  published_at `relative-time[datetime]`, 본문 `div.markdown-body[body-content]`).

### round-trip 모델 — byte-match 안 함 (hoyolab 와 다름)
hoyolab cluster 는 byte-identical 이라 "기존 config 기능 필드 재현"으로 검증했지만, github 19건은
LLM 이 repo 마다 다른(일부 버그난) selector·board·per-repo author hack(`a[href^='/bartlomieju']` 등)을 뽑아
**서로/canonical 과 다름**. release 리스트 DOM 은 repo 불문 동일 → 교정한 canonical selector 하나로 충분.
따라서 검증을 "기존 재현" 대신:
- 멤버 URL → `board=owner/repo`·`url_template` 결정적 추출 (release 멤버 19건 전수, anti-vacuous ≥15 강제)
- `/releases` 아닌 멤버(tree/main, repo 홈) → builder `None` (cluster 제외 확인)
- 같은-host 다른-종류 8종 negative (홈/issues/pulls/wiki/tree/commits/owner/개별release) → `recognize()` 미매칭
- reject 충돌: `recognize_reject(release URL)` == None

## 효과
- 이후 GitHub Releases(어느 repo든) 등록 → probe/Gemini 생략, builder 결정적 생성 = **토큰 0 + 실패 없음**.
- cluster_report 재실행 시 github 19건 후보 소멸 (live `recognize()` 억제). 남은 github cluster 2건은
  release 아닌 repo-home/tree — 향후 별도 recognizer 후보 (이번 범위 밖).
- 기존 config 19건 손 안 댐 (slug 마이그 X, Rule D 회피). recognizer 는 이후 등록부터.

## 회귀 검증
```
$ PYTHONPATH=. python tests/recognizers/test_github_releases.py
  PASS board_extract / slug_board / roundtrip_members (release 19 / 제외 2 · all ok) /
       recognize_integration / other_host_neg / same_host_neg[8종] / no_reject_conflict
  14 passed

$ PYTHONPATH=. python scripts/probe_smoke.py --stage 3 --stage 5
  [stage 3] 71/71 OK   [stage 5] 0 FAIL · coverage 29/29
  ==== summary ==== PASS 597  FAIL 0  → exit 0

$ PYTHONPATH=. python scripts/cluster_report.py   # 봉합 확인
  recognized 16→35 (github 19건 흡수) · [A] github cluster 19→2 (release 후보 소멸, 비-release 2건만 잔존)
```

## 비고
recognizer-extension 의 *non-identical cluster* 첫 케이스 — canonical 판단 + 일부 멤버 제외(다른 페이지 종류)가
필요했던 사례. hoyolab(byte-identical) 과 대비. SKILL §2(변수 슬롯 판단)·§4(같은-host 다른-종류 negative) 실증.
