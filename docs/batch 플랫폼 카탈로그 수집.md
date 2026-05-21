# batch 플랫폼 카탈로그 수집

batch 등록 기능(`scripts/register_batch.py`) 테스트용 사이트 링크 카탈로그 수집 기록.
링크는 `output/candidates/<name>.yaml` (schema 2: `name` + `url`) 에 저장 — git-ignored 데이터.
N100 동기는 `scripts/remote.py batch-register` 의 atomic scp.

## 1. 수집 기준 (link collection criteria)

배치 테스트 목적 = **config 자동 생성 파이프라인을 다양한 사이트 구조로 자극**. 따라서:

1. **"플랫폼" = 구별되는 도메인(host)**. (예: `github.com` 의 repo 100개는 1 플랫폼. `mastodon.social` 과 `fosstodon.org` 는 같은 SW지만 다른 도메인 → 다른 플랫폼.)
2. **한 플랫폼(host)당 ≤2 링크**. 한 사이트 안 게시판 여러 개로 수를 채우지 않음.
3. **이전 batch 와 무중복** — URL 뿐 아니라 *host 통째*로 제외. 같은 도메인 두 번 안 씀.
4. **카탈로그끼리 무중복** (URL/host).
5. **카테고리(테마)별로 묶음** — 한 카탈로그 = 한 테마. 테마 안에서 도메인 다양성 최대화.

수집 출처: 도메인 지식 + 큐레이션 리스트 웹 검색(포럼 SW 비교글, fediverse instance 리스트, 패키지 매니저 OPML, 정부 RSS 디렉터리 등).

자동 생성물이라 일부 URL 은 redirect/404 가능 — batch *분류* 테스트엔 다양한 실패(rc) 케이스로 오히려 유용. 실등록 전 `--dry-run` 으로 분포 확인 권장.

## 2. 카탈로그 인벤토리 (지금까지 만든 것)

| 카탈로그 | 링크 | host | 테마 | 비고 |
|---|---|---|---|---|
| `legacy-2026-05-19` | 42 | 31 | 게임 공지·게임 커뮤니티 (넥슨/넥슨포럼/온스토브/하요랩/루리웹/클리앙/인벤/디시/아카/네이버/다음/레딧/스팀/닌텐도) | 1차 손-수집 |
| `2026-05-20` | 110 | 67 | 인벤보드·디시·아카·온스토브·KR커뮤(뽐뿌/더쿠/82쿡)·KR대학·Discourse포럼·Wikipedia/Fandom·GitHub releases·RSS뉴스·레딧·게임매체 | 2차 손-수집 |
| `2026-05-20-b` | 100 | 57 | Discourse 15·Reddit 10·GitHub releases 15·Steam앱RSS 10·DCinside·Arca·Wikipedia(타언어)·Fandom·뉴스RSS·Google News | 3차 (1차 대화) |
| `2026-05-21-forums` | 100 | 100 | **비-Discourse 포럼/커뮤니티** — phpBB·vBulletin·XenForo·MyBB·SMF·Invision·Vanilla·WoltLab·Discuz·bbPress·FluxBB·PunBB·NodeBB·Flarum·그누보드·Rhymix·XEtown + xda·tomshardware·resetera·nexusmods·보배드림·하드웨어/오디오/취미 포럼 | 4차 (플랫폼 다양화) |
| `2026-05-21-blogcms` | 100 | 99 | **블로그/CMS/뉴스레터** — WordPress·Ghost·Substack·Medium·Tistory·Velog·Brunch + 기업 eng블로그 30+·개인블로그·비-사용 매체 | 4차 |
| `2026-05-21-code` | 100 | 98 | **코드호스팅·패키지레지스트리·배포판** — GitLab·Gitea·Forgejo·SourceForge·Launchpad·PyPI·crates·npm·distros 25+·언어/툴 news | 4차 |
| `2026-05-21-fedi` | 100 | 100 | **연합 SNS + Q&A + 상태페이지** — Mastodon 40+·Lemmy 20+·PeerTube·Pixelfed·Misskey·mbin·StackExchange·statuspage/Instatus·Tildes/ProductHunt/Slashdot | 4차 |
| `2026-05-21-govedu` | 100 | 100 | **정부/표준기구/재단/해외대학** — GOV.UK·US연방기관·각국정부·W3C/IETF/ISO·재단(Mozilla/FSF/EFF/Apache)·해외대학 40+ | 4차 |

**4차(05-21) 합계: 500 링크 / 497 distinct host.** 1~3차에서 소진한 플랫폼(Discourse·GitHub·Arca·DCinside·Reddit·Steam·Wikipedia·Fandom·Inven·클리앙류)은 host 통째 배제.

## 3. 생성/확장 방법

4차 5개 카탈로그는 손-YAML 대신 빌더로 생성:

- `output/candidates/_build_2026-05-21.py` — 테마별 URL 후보 리스트 보유. 실행 시:
  - 이전 3개 카탈로그(legacy/05-20/05-20-b) 의 host 전부 제외
  - 카탈로그끼리 URL/host 무중복
  - host당 ≤2
  - 각 카탈로그 정확히 100 slice (후보 부족 시 stderr 경고 + rc=1)
  - `name` = host(+마지막 path seg) 자동
- 확장: 빌더 안 테마 리스트에 URL 추가 → `python output/candidates/_build_2026-05-21.py` 재실행. idempotent.

후보에 `EXCLUDED` 문자열 박힌 URL 은 sentinel(제외 확인용) — 빌더가 걸러냄.

## 4. 실행

```
# 분포 먼저 (enqueue 안 함)
python scripts/register_batch.py \
  --catalog=2026-05-21-forums --catalog=2026-05-21-blogcms \
  --catalog=2026-05-21-code --catalog=2026-05-21-fedi \
  --catalog=2026-05-21-govedu --dry-run

# 실제 enqueue (N100 bot.sqlite3 jobs, kind=register via=batch — worker 가 처리)
python scripts/register_batch.py --catalog=2026-05-21-forums [...나머지]
```

`register_batch.py` 의 cross-catalog dedup 은 *동시에 넘긴 카탈로그*끼리만 검사 — 이전 batch 와의 무중복은 위 빌더가 보장.

설계: `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` (rev5 multi-file).
