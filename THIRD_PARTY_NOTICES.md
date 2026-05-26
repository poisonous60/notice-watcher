# Third-party notices

이 프로젝트는 아래 third-party 소스의 *factual data* (CSS selector 문자열) 를 발췌해
사용합니다. 라이선스 의무 (attribution + license link) 충족용 notice 파일.

## duckduckgo/autoconsent (MPL-2.0)

- repository: https://github.com/duckduckgo/autoconsent
- license: Mozilla Public License 2.0 (MPL-2.0) — full text: https://www.mozilla.org/en-US/MPL/2.0/
- 발췌 범위: `lib/cmps/{onetrust,cookiebot,trustarc,quantcast,didomi,sourcepoint}.ts` 의
  CMP accept / reject button CSS selector 문자열 (예: `#onetrust-accept-btn-handler`,
  `#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll` 등).
- 사용 위치: `probe/fetch_headless.py` 의 `_CONSENT_DISMISS_JS` 안 `KNOWN_CMP_REJECT` /
  `KNOWN_CMP_ACCEPT` 배열, `_FRAME_REJECT_SELECTORS` / `_FRAME_ACCEPT_SELECTORS` 상수.
- 발췌 시점: 2026-05 (autoconsent v14.84.2 기준).
- MPL-2.0 §3.3 source notice 의무 충족: 본 파일 (`THIRD_PARTY_NOTICES.md`) + 코드 안
  주석 reference. autoconsent 의 *코드* (TypeScript 구현 / message bridge / rule loader)
  는 사용하지 않으며 — selector 문자열 (factual data) 만 발췌.
- 변경 없음. 단순 발췌·인용.
