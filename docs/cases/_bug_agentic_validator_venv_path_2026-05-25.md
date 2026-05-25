---
slug: _bug_agentic_validator_venv_path_2026-05-25
url: internal://codex-agentic-validator-subprocess-venv
status: "✅ fixed (merged 74726d5, deployed to N100)"
outcome: improved
date: 2026-05-25
fix_layer: none
failure_keys: [agentic_validator_modulenotfound, venv_path_mismatch]
tags: [bug, codex, agentic, register, venv]
---

## 증상 (2026-05-25 substack batch 1차)

agentic mode 가 substack/newsletter 류 사이트에서 정확한 RSS config 까지 만들었으나,
agent 자체 validate cycle 에서 다음 error 만 받음:

```
validator import failed: ModuleNotFoundError: No module named 'httpx'
```

또는 같은 패턴의 variant (`ModuleNotFoundError`, `validator wrapper`, `validator environment`).

→ agent retry 2 회 다 같은 error → ok=false → register.py 가 gen_fail (rc=1) 박음.

### 영향 받은 slug (~12)

- host_annehelen-subst (annehelen.substack.com)
- host_bloodinthemachi (bloodinthemachine.com)
- host_garbageday-emai (garbageday.email)
- host_honest-broker-c (honest-broker.com)
- host_matthewball-co (matthewball.co)
- host_platformer-subs (platformer.substack.com)
- host_publicnotice-co (publicnotice.co)
- host_readmargins-com (readmargins.com)
- host_theconvivialsoc (theconvivialsociety.substack.com)
- host_thefp-com (thefp.com)
- host_understandingai (understandingai.org)
- host_worksinprogress (worksinprogress.news)

## Root cause

`scripts/validate_config.py` 가 `from generate.validate import validate_built_config` 호출.
`generate/validate.py` 는 `httpx`, `bs4` 등 transitively import.

prompt `register_agent_AGENTS.md` WORKFLOW step 6 (옛):

```
python ./validate_config.py ./candidate.json
```

agent 가 부르는 `python` 이 N100 의 venv (`~/notice-watcher/.venv/bin/python`) 가 아닌
**system python** → venv 안에만 있는 httpx/bs4 못 찾음 → ImportError.

`generate/codex_agentic.py:run_codex_agentic` 가 codex CLI subprocess 띄울 때 `child_env`
= `os.environ.copy()` + `REPO_ROOT` 만 추가. **PATH 손 안 댐** → codex CLI 가 자기 subprocess
띄울 때 PATH 의 첫 python (system) 잡음.

## Fix

### `generate/codex_agentic.py:_setup_workdir` (line ~445)

tmpdir 에 venv python 경로 박은 launcher 박음:

```python
py = sys.executable  # parent (= bot worker) 가 venv python 으로 실행 중
(workdir / "python_path.txt").write_text(py + "\n", encoding="utf-8")
if sys.platform == "win32":
    (workdir / "run_validator.bat").write_text(
        f'@echo off\r\n"{py}" "%~dp0validate_config.py" %*\r\n',
        encoding="utf-8",
    )
else:
    sh_path = workdir / "run_validator.sh"
    sh_path.write_text(
        f'#!/bin/sh\nexec "{py}" "$(dirname "$0")/validate_config.py" "$@"\n',
        encoding="utf-8",
    )
    sh_path.chmod(0o755)
```

### `generate/codex_agentic.py:run_codex_agentic` child_env (line ~618)

codex CLI subprocess PATH 에 venv bin prepend (보조):

```python
venv_bin = Path(sys.executable).parent
child_env["PATH"] = str(venv_bin) + os.pathsep + child_env.get("PATH", "")
```

### prompt 변경

`prompts/register_agent_AGENTS.md` WORKFLOW step 7 + `prompts/register_agent_user.txt`:

```
# 옛:
python ./validate_config.py ./candidate.json

# 새:
./run_validator.sh ./candidate.json     # Linux
.\run_validator.bat ./candidate.json    # Windows
```

launcher 가 venv python 으로 명시 호출 → httpx/bs4 import OK.

## 변경 파일

- `generate/codex_agentic.py` (16 lines)
- `prompts/register_agent_AGENTS.md` (9 lines — WORKFLOW step 6→7 + 입력 파일 목록에 launcher 추가)
- `prompts/register_agent_user.txt` (3 lines)
- `tests/llm/test_codex_agentic.py` (87 lines — launcher staging, python_path.txt, child PATH 회귀)

## 회귀 검증

- RED 먼저 확인 — launcher 누락 / child PATH 누락 시 pytest FAIL
- `python -m pytest tests/llm/test_codex_agentic.py -x` PASS
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS 1451

## 실측 회복 (1차 retry)

substack batch `batch-register --failed` 후 위 ~12 slug 중 11 회복 (job id 2444-2459 범위).
1 (`garbageday.email`) 은 별 케이스 (agent retry 한계, validator bug 무관).

## commit / 배포

- merge commit: `74726d5` (chunk-2 worktree)
- N100 HEAD: `74726d5` → `fecb54c` (그 후 chunk-3/4/5 누적)

## 보류/비채택

- `--ignore-user-config` 제거 — 사용자 ~/.codex/config.toml 의 다른 키 (model_reasoning_effort=high 등)
  도 같이 적용되어 의도 깨짐. 박지 않음.
- codex CLI `-c venv=/path` 류 옵션 — codex CLI 는 이런 키 모름. PATH override 가 표준 방식.
