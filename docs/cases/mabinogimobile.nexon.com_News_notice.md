---
slug: mabinogimobile.nexon.com_News_notice
url: https://mabinogimobile.nexon.com/News/notice
status: 🔧 손작성 config (작동중, baseline 10)
date: 2026-05-11
failure_keys: [article_body_len]
config_strategy: httpx_html
---

## 무엇이 일어났나
`[FAIL] article_body_len: 0자` 반복. 목록은 정적 HTML 로 잘 추출됨(제목·날짜·분류·URL). 문제는 글 본문 — 목록의 `<a href>` 가 `…/News/notice/View?threadId=3440249` 인데 그 URL 을 **직접 GET 하면 `/Main?aspxerrorpath=…` 으로 302 튕김**(= 클라이언트 사이드 라우트, 브라우저에서 목록 띄우고 클릭해야만 작동). 실제로 클릭하면 가는 주소는 `…/News/Notice/3440249` (경로형) — 이건 직접 GET 시 200 + 본문이 정적 HTML(`div.content_area`)에 들어있음. 자동 파이프라인은 페이지 HTML 어디에도 안 보이는 그 경로형 URL 을 추측할 방법이 없어서 실패 (글페이지 render+HAR re-probe 도 잘못된 `?threadId=` URL 을 열어서 `/Main` 만 렌더, 본문 없음). → `config 자동생성 실패 케이스.md` §2b(iii).

## 무엇을 바꿨나
손작성 `configs/mabinogimobile.nexon.com_News_notice.json` — `list` 는 자동 생성된 것과 거의 동일, `url` 필드만 `{from:"template", value:"https://mabinogimobile.nexon.com/News/Notice/{post_id}"}` (`post_id`=`data-threadid` attr 에서), `article.url_template` 도 경로형, `article.content`=`[div.content_area, section.view_body_wrap]`. `register.py --config configs/mabinogimobile.nexon.com_News_notice.json` 로 등록. 본문 fetch 1500자 확인됨.
