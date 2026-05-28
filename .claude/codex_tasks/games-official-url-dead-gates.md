# Task: 3개 url_dead 일반화 게이트 — cross-host redirect / parked-domain Access Denied / probe-timeout-no-baseline

## 배경 (cross-site, 의무 — 같은 batch 14+ sites)

batch `2026-05-24-games-official` (100 entries) drain 분포:
```
done 16 / rc=1 gen_fail 11 / rc=3 gate_reject 32 / rc=4 url_dead 40 / rc=5 cap_blocked 5
```

`rc=3` 32건과 `rc=5` 5건과 `rc=1` 11건 중 **14+ sites 가 실제로는 dead URL** 인데 잘못 분류됨. 사용자 보고: "지금 cap_blocked은 다 404야".

### 패턴 1: cross-host redirect (eTLD+1 다른 host 로 302/301)

11+ sites — 입력 URL 이 *완전히 다른 host* 의 marketing landing page 로 redirect. 최종 응답 200 OK 라서 `Classification.NOT_FOUND` 안 받음 → `TARGET_NOT_FOUND` verdict 안 박힘 → rc=3 gate_reject.

| Input URL | Final URL (curl -L) | 현재 rc |
|---|---|---|
| `https://slaythespire.com/news/` | `https://megacrit.com/` | 3 |
| `https://slaythespire.com/` | `https://megacrit.com/` | 3 |
| `https://wolfenstein.com/` | `https://bethesda.net/ko/game/wolfenstein-youngblood` | 3 |
| `https://wolfenstein.com/news/` | `https://bethesda.net/ko/game/wolfenstein-youngblood` | 3 |
| `https://dontstarvegame.com/` | `https://www.klei.com/games/dont-starve/` | 3 |
| `https://fallout76.com/` | `https://fallout.bethesda.net/ko` | 3 |
| `https://fallout76.com/news/` | `https://fallout.bethesda.net/ko` | 1 (gen_fail — empty board) |
| `https://starfield.bethesda.net/` | `https://bethesda.net/ko/game/starfield` | 3 |
| `https://starfield.bethesda.net/news/` | `https://bethesda.net/ko/game/starfieldnews` | 3 |
| `https://gears5.com/` | `https://www.gearsofwar.com/games/gears-5/` | 3 |
| `https://gears5.com/news/` | `https://www.gearsofwar.com/games/gears-5/` | 3 |
| `https://vampire-survivors.com/` | `https://beacons.ai/poncle` | 3 |

**비-사례 (false-positive 피해야 함)**:
- `https://valheimgame.com/` → `https://www.valheimgame.com/` (www. 추가만, **같은 site**)
- `https://warthunder.com/` → `https://warthunder.com/en` (locale path 추가만, **같은 host**)
- `https://doom.bethesda.net/` → `https://doom.bethesda.net/ko-KR/the-dark-ages` (locale path, **같은 host**)
- `https://forza.net/` → `https://forza.net/` (redirect 없음)

### 패턴 2: JS-redirect 후 parked "Access Denied" 본문 (rc=5 false-positive)

2 sites (×2 paths = 4 entries) — JS `window.location.href="/lander"` redirect, `/lander` 가 `<TITLE>Access Denied</TITLE>` 반환 (Akamai EdgeAuth 류 parked domain).

| URL | curl 200 응답 본문 | 진짜 분류 |
|---|---|---|
| `https://lethalcompany.com/` | `<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href="/lander"}</script></head></html>` | url_dead |
| `https://contentwarning.com/` | (위와 동일) | url_dead |
| `https://lethalcompany.com/lander` | `<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY>...` | (parked) |

현재 rc=5 cap_blocked. fediverse API rescue probe 가 JSON 파싱 실패 → cap_blocked 분류. 실제는 *dead 도메인*.

### 패턴 3: probe timeout + baseline 미응답 (rc=1 false-positive)

2 sites (×2 paths) — DNS 또는 TCP 단계에서 응답 자체 없음. probe subprocess 가 120s timeout → `RegisterTimeoutError` → `scripts/register.py:3092-3097` 가 *무조건* rc=1 gen_fail 로 분류. *실제는 dead host*.

| URL | curl -L --max-time 8 | 진짜 분류 |
|---|---|---|
| `https://hadesgame.com/` | `000` (TCP connect 실패) | url_dead |
| `https://hadesgame.com/news/` | `000` | url_dead |

## Root cause + 일반화 자리

### C-layer 1: `probe/types.py` Result 에 `final_url` 필드 추가

현재 `Result` dataclass (probe/types.py:20-36) 에 `final_url` 필드 **없음**. `probe/fetch_static.py:41-76` 와 `probe/fetch_headless.py:424-558,1020-1162` 는 redirect 추적해서 `final_url` 변수에 박지만 — `classify(final_url=final_url, ...)` 에만 넘기고 Result 에는 *저장 안 함*. diagnose.py 가 Result 의 final_url 을 볼 수 없음.

수정:
1. `probe/types.py:20-36` Result 에 `final_url: Optional[str] = None` 필드 추가
2. `probe/fetch_static.py:76` Result 생성 시 `final_url=final_url` 전달
3. `probe/fetch_headless.py:558` Result 생성 시 `final_url=final_url` 전달
4. `probe/fetch_headless.py:1162` `_make_clicked_result` 류 fix (final_url 보존)

### C-layer 2: `probe/diagnose.py` cross-host redirect verdict

`diagnose.py:307-349` 의 `baseline_ok and not verdict_parts` 분기 안에 새 분기 추가:

```python
# CROSS_HOST_REDIRECT — 모든 target 진입이 OK(200) 인데 final_url 의 eTLD+1 이 input URL 과 다르면
# (또는 input path != "/" 인데 final path == "/" 이고 host 도 변했으면) — 입력 path 가 실제로 없음.
# www. 추가 또는 locale path 추가는 *같은 site* — eTLD+1 비교로 자동 제외.
def _registrable_domain(host: str) -> str:
    # eTLD+1 추출 — public suffix list 없이 단순 휴리스틱 (com/net/co.kr/co.jp 등 흔한 케이스만)
    # 또는 publicsuffix2 라이브러리 사용 가능 (이미 deps 에 있나 확인). 없으면 단순 last-2-labels.
    parts = host.lower().split(".")
    if len(parts) <= 2:
        return host.lower()
    # co.kr / co.jp / co.uk 류 2단계 TLD
    multi = {"co.kr", "co.jp", "co.uk", "com.au", "com.br", "com.cn", "ne.jp", "or.kr"}
    last2 = ".".join(parts[-2:])
    if last2 in multi:
        return ".".join(parts[-3:])
    return last2

# input host vs final host eTLD+1 비교
input_host = urllib.parse.urlsplit(url).hostname or ""
input_etld = _registrable_domain(input_host)
final_hosts_changed: list[tuple[str, str]] = []
for r in primary_target_results:
    if r.classification != Classification.OK or not r.final_url:
        continue
    final_host = urllib.parse.urlsplit(r.final_url).hostname or ""
    final_etld = _registrable_domain(final_host)
    if final_etld and input_etld and final_etld != input_etld:
        final_hosts_changed.append((r.url, r.final_url))

if final_hosts_changed and len(final_hosts_changed) == len([r for r in primary_target_results if r.classification == Classification.OK]):
    # 모든 OK 응답이 cross-eTLD+1 redirect → 입력 host 의 board 가 실제로는 없음
    verdict_parts.append("CROSS_HOST_REDIRECT")
    sample = final_hosts_changed[0]
    notes.append(
        f"입력 URL 이 eTLD+1 다른 host 의 marketing/landing 페이지로 redirect: "
        f"{sample[0]} → {sample[1]} — 입력 host 의 해당 path 가 사실상 존재하지 않음 (cross-host fold)."
    )
```

배치 위치: `verdict_parts.append("STATIC_PATH_DEAD")` (line 345) 분기와 *병렬*. 같은 `baseline_ok and not verdict_parts` 블록 안. CROSS_HOST_REDIRECT 가 STATIC_PATH_DEAD 보다 *위* (200 OK 인데 host 바뀐 케이스가 더 명확).

### C-layer 3: `probe/signals.py` parked-domain "Access Denied" soft-404 마커

현재 `_looks_like_403_soft_not_found` (signals.py:93-125) 는 *status 403* 만 봄. lethalcompany / contentwarning 의 `/lander` 가 *어떤 status* 로 응답하는지 codex 가 직접 확인 (curl -i):

```bash
curl -ski "https://lethalcompany.com/lander" --max-time 8 | head -20
```

response status 와 본문 marker 보고 새 함수 `_looks_like_parked_access_denied` 추가:

```python
_PARKED_ACCESS_DENIED_RE = re.compile(r"<title[^>]*>\s*Access\s+Denied\s*</title>", re.IGNORECASE)
_PARKED_BODY_MARKERS = ("You don't have permission", "Reference #18.")  # Akamai EdgeAuth 표시

def _looks_like_parked_access_denied(*, status, body_text, visible_text, headers_lower) -> Optional[str]:
    # parked domain (Akamai EdgeAuth 류) — body 가 Access Denied 만 표시
    if not body_text:
        return None
    if not _PARKED_ACCESS_DENIED_RE.search(body_text[:5000]):
        return None
    if len(visible_text.strip()) > 500:
        return None  # 진짜 401/403 페이지가 안내문 길게 박는 경우와 구분
    return "parked Access Denied"
```

`classify()` (signals.py:128~) 안의 NOT_FOUND 판별에 호출 추가:
```python
parked = _looks_like_parked_access_denied(
    status=status, body_text=body_text, visible_text=visible_text, headers_lower=headers_lower,
)
if parked:
    notable.append(f"parked-domain marker: {parked}")
    return Classification.NOT_FOUND, notable
```

JS-redirect 1-line shell 자체도 marker — 본문이 매우 짧고 (114 bytes) `window.location.href="/lander"` 형태:
```python
_JS_REDIRECT_LANDER_RE = re.compile(
    r"window\.location\.href\s*=\s*[\"']\s*/?(lander|parked|expired)[\"']",
    re.IGNORECASE,
)
# 본문 ~200 bytes 이내 + JS-redirect 만 있으면 parked
if status == 200 and len(body_text.strip()) < 400 and _JS_REDIRECT_LANDER_RE.search(body_text):
    notable.append("JS-redirect to parked path")
    return Classification.NOT_FOUND, notable
```

### F-layer 1: `scripts/register.py:3168` is_url_dead 조건 확장

```python
is_url_dead = (
    ("target_not_found" in verdict)
    or ("cert_or_dns_broken" in verdict)
    or ("static_path_dead" in verdict)
    or ("cross_host_redirect" in verdict)   # 추가
)
```

### F-layer 2: `scripts/register.py:3092-3097` probe timeout 후 baseline 확인

현재:
```python
try:
    _run_probe(url, lite=..., timeout_s=...)
except RegisterTimeoutError as e:
    fp = _save_failed(slug, url, f"register probe timeout: {e}",
                      last_config=None,
                      last_feedback=f"[FAIL] probe_timeout: {e}")
    print(f"[register] ❌ 자동 처리 불가 — probe timeout. → {fp}")
    return 1
```

수정: timeout 캐치 시 **빠른 baseline check (httpx HEAD, 8s timeout)** 후 host 응답 없으면 cert_or_dns_broken 으로 rc=4 분류:

```python
except RegisterTimeoutError as e:
    # probe subprocess timeout — host 가 응답 자체 안 하면 dead URL (정책 거부) 로 분류.
    # httpx HEAD baseline 8s 시도. ConnectError/ConnectTimeout → cert_or_dns_broken.
    host_dead = False
    dead_sample = ""
    try:
        import httpx as _httpx
        parsed = urllib.parse.urlsplit(url)
        base = f"{parsed.scheme}://{parsed.netloc}/"
        try:
            with _httpx.Client(timeout=8.0, follow_redirects=True) as _c:
                _c.head(base)
        except (_httpx.ConnectError, _httpx.ConnectTimeout, _httpx.ReadTimeout,
                _httpx.RemoteProtocolError, OSError) as he:
            host_dead = True
            dead_sample = str(he)[:120]
    except Exception:
        pass

    if host_dead:
        # url_dead 경로 (rc=4) — _save_rejected (REJECTED 마커 + sibling cleanup)
        try:
            _save_rejected(slug, url,
                           reason=f"cert_or_dns_broken (probe timeout + baseline 8s 무응답): {dead_sample}",
                           note="probe-timeout-host-dead",
                           learn=False)
        except Exception as se:
            print(f"[register] ⚠ REJECTED 마커 저장 실패 (rc=4): {se}", file=sys.stderr)
        print(f"[register] ❌ host 응답 없음 → url_dead (rc=4). probe timeout 후 HEAD 도 실패.")
        return 4

    fp = _save_failed(slug, url, f"register probe timeout: {e}",
                      last_config=None,
                      last_feedback=f"[FAIL] probe_timeout: {e}")
    print(f"[register] ❌ 자동 처리 불가 — probe timeout. → {fp}")
    return 1
```

## 검증 의무 (모든 layer 변경 후)

1. `python scripts/probe_smoke.py` 통과
2. **실제 artifact 로 검증**:
   - `output/probe/host_fallout76-com_news_8edbb92f/` (cross-host redirect, dev 박스 있음) — diagnose 재실행 시 `CROSS_HOST_REDIRECT` verdict 박혀야 함.
     ```python
     # cross-host redirect 검증
     from probe.diagnose import build_diagnosis  # 또는 entrypoint
     # 또는 register.py --reuse-probe https://fallout76.com/news/ 실행해 rc=4 나오는지
     ```
   - `output/probe/host_hadesgame-com_root_2a95ed45/` — probe artifact 없음 (timeout). register.py 의 baseline check 만 검증 가능 — host 가 죽었는지 확인 (curl https://hadesgame.com/ --max-time 8 → 000).
3. **false-positive 회귀 방지** unit test:
   - `www.` redirect: input=`example.com`, final=`www.example.com` → `CROSS_HOST_REDIRECT` 박히면 안 됨 (eTLD+1 같음).
   - locale path: input=`warthunder.com`, final=`warthunder.com/en` → 박히면 안 됨 (host 같음).
   - subdomain to parent: input=`starfield.bethesda.net`, final=`bethesda.net/game/starfield` — **이건 박혀야 함** (eTLD+1 같지만 *입력 host* 가 *없어진* 케이스). 단 이 경우 starfield.bethesda.net 의 eTLD+1 도 `bethesda.net` 이라 같음. → 별도 게이트 (host 가 *subdomain → parent root* 로 fold 된 케이스) 가 필요한데 cross-eTLD 만으론 못 잡음. **현재 task scope 에서는 eTLD+1 다른 케이스만 박고, subdomain-to-parent fold 는 별도 TODO** (case body 에 명시).
4. `git diff main...HEAD` 직접 검토 — over-edit 없는지 확인 (위 5 자리 외 파일 X).

## 작업 범위

| 파일 | 변경 |
|---|---|
| `probe/types.py` | Result 에 `final_url` 필드 추가 |
| `probe/fetch_static.py` | Result 생성 시 `final_url` 전달 |
| `probe/fetch_headless.py` | 같음 (2 자리) |
| `probe/diagnose.py` | CROSS_HOST_REDIRECT verdict 추가 |
| `probe/signals.py` | parked Access Denied / JS-redirect-to-lander 마커 추가 |
| `scripts/register.py` | is_url_dead 조건 확장 + probe timeout 시 baseline-dead 분류 |
| `tests/probe_heuristics/test_*.py` | 새 unit fixture (false-positive 회귀 방지) |

## case body 의무

`docs/cases/_generic_url_dead_gates_2026-05-27.md` 작성. frontmatter:
```yaml
---
slug: _generic_url_dead_gates_2026-05-27
date: 2026-05-27
outcome: improved
fix_layer: C+F
status: ✅ 일반화 게이트 3종 — cross-host redirect / parked Access Denied / probe-timeout-host-dead
failure_keys:
  - cross_host_redirect
  - parked_access_denied
  - probe_timeout_host_dead
tags: [url_dead, gate, generalization, batch-2026-05-24-games-official]
---
```

body 에 패턴 1/2/3 각각 매핑 + 14+ sites 일반화 후보 명시 (배경 표 인용).

## 게이트 (HARD-STOP)

- 위 7개 파일 외 *건드리지 X*.
- known-host-list 형태로 박지 X (slaythespire.com 같은 host 이름 hardcode 금지) — *구조 신호* (eTLD+1 비교, body marker) 만.
- `git push` / `git commit` X — Claude 가 review 후 직렬 merge.
- `probe_smoke.py` exit≠0 면 self-stop.
