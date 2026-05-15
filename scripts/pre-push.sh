#!/bin/sh
# git pre-push hook — probe_smoke 의 코드 회귀 stage 만 강제.
# stage 3 = configs/*.json validate + make_adapter (21 configs)
# stage 5 = heuristic unit fixtures (probe/_heuristic.py @heuristic 데코레이터)
#
# stage 1/2 는 probe artifact freshness — 운영/사이트 등록과 무관, 가끔 stale → hook 에서 제외.
# stage 1/2 점검은 `python scripts/probe_smoke.py` 통째로 손-실행.
#
# `.git/hooks/pre-push` 는 git 추적 X — `scripts/setup-hooks.{sh,ps1}` 가 이 파일을 그 위치로 복사.
echo "[pre-push] probe_smoke --stage 3 --stage 5"
python scripts/probe_smoke.py --stage 3 --stage 5
status=$?
if [ $status -ne 0 ]; then
  echo "[pre-push] FAIL — push 차단."
  echo "[pre-push] --no-verify 금지. 픽스 먼저."
  exit $status
fi
