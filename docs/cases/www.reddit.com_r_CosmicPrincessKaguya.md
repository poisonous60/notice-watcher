---
slug: www.reddit.com_r_CosmicPrincessKaguya
url: https://www.reddit.com/r/CosmicPrincessKaguya/
status: 🧩 손어댑터 (작동중, baseline 19, handwritten/RedditAdapter, flair="Fan Art")
outcome: handcrafted
date: 2026-05-12
requested_by: 사용자(직접 요청)
config_strategy: handwritten
adapters_changed: [RedditAdapter]
---

## 왜 손어댑터
자동 파이프라인을 돌리지 않고 바로 손작업으로 갔다 — Reddit 은 어떤 페이지든 URL 뒤 `.json` 으로 동일 데이터를 주는 공개 API 표면이 있어 손어댑터가 훨씬 안정적이고, "어떤 정렬/탭/플레어를 볼지"를 kwargs 로 받아야 했다(사용자: 디시 념글/창작탭 같은 거 없냐 → 정렬·플레어 필터로 대응). 본문 응답이 배열 `[postListing, commentListing]` 이고 링크/이미지/갤러리 글은 `selftext` 가 비어 본문 대신 미디어/링크를 합성해야 해서 선언적 config 로 표현하기엔 번잡.

## 해결
손어댑터 `adapters/reddit.py` `RedditAdapter`(`adapters/__init__.py` `__all__` 등록). 목록=`https://www.reddit.com/r/{sub}/{sort}.json?limit=&raw_json=1`(`sort`∈hot/new/top/rising, `top`은 `&t=hour|day|week|month|year|all`), 응답 `data.children[].data`(kind=="t3"). 본문=`https://www.reddit.com{permalink}/.json?raw_json=1` → 배열의 `[0].data.children[0].data`; `selftext_html`(raw_json=1 이라 이미 디코드된 HTML) 있으면 그걸, self 아니면 `url_overridden_by_dest`(이미지면 `<img>`, 아니면 `<a>`)·`is_gallery`+`media_metadata` 합성, 다 없으면 "Reddit 에서 보기" 링크. `cover_image`=`preview.images[0].source.url`→`thumbnail`→이미지 직링크. `published_at`=`created_utc`(UTC). kwargs: `subreddit`·`sort`(기본 new)·`time_filter`(top용)·`flair`(link_flair_text 가 이 값인 글만 — '창작탭' 효과)·`include_stickied`(기본 True). 차단 정책: UA 헤더 없으면 429 → 평범한 브라우저 UA + polite_sleep(4~8s) + 429 시 백오프 재시도만(로그인/우회 없음); 403/404/451 이면 빈 목록. **robots.txt 가 `User-agent:* / Disallow:/` 라 회색지대** — 저빈도 개인용으로만, `_note` 에 명시. 이 서브레딧은 사용자 선택대로 `kwargs.flair="Fan Art"`(서브 글의 절반 가량) — `configs/www.reddit.com_r_CosmicPrincessKaguya.json` 으로 `register.py --config` 등록. flair/sort 바꾸려면 kwargs 만 수정 후 재등록.

## 부수 — recognizer 인식기 추가
`engine/known_platforms.py` (현 `engine/recognizers/reddit.py`) 에 `reddit` 인식기 추가 — `//{www|old|new|np|m|i.}reddit.com/r/<sub>` 매칭, path 의 `/hot|/new|/top|/rising` 와 query 의 `t=`·`f=flair_name:"..."` 를 읽어 kwargs 구성(`/comments/...` 단일 글 URL 은 None → 폴백). 이제 다른 서브레딧은 `/watch https://www.reddit.com/r/<sub>/`(또는 `.../hot/`, `.../top/?t=week`, `.../?f=flair_name:"Fan Art"`)만으로 등록됨. URL 로 표현 안 되는 옵션(`include_stickied` 등)은 `configs/<slug>.json` kwargs 직접 수정 + `register.py --config`.
