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
| `2026-05-24-games-kr` | 100 | 50 | **한국 게임 회사·서비스** — NCsoft(plaync sub)·Krafton·Pearl Abyss·Webzen·Com2uS·Gravity·Neowiz·Kakao Games·Wemade·Devsisters·Netmarble·Smilegate·Shift Up·Haegin·NHN·Line Games 등 | 5차 |
| `2026-05-24-games-jp` | 100 | 50 | **일본 게임 회사·콘솔·모바일** — Square Enix·Bandai Namco·Konami·Capcom·Koei Tecmo·Sega·Atlus·Cygames·MIXI·DeNA·GREE·Aniplex·GungHo·FromSoftware·Level-5·Falcom·SNK·Yostar JP·NEXON JP·Marvelous 등 | 5차 |
| `2026-05-24-games-cn` | 100 | 50 | **중국 게임 회사·플랫폼** — Tencent(qq.com sub)·NetEase(163.com sub)·miHoYo/HoYoverse·Perfect World·Lilith·4399·XD/TapTap·bilibili games·IGG·FunPlus·37 Games·Yoozoo·Century·Kuro Games·Hypergryph 등 | 5차 |
| `2026-05-24-games-us` | 100 | 50 | **미국/서양 게임** — Blizzard·Riot·Epic·EA·Activision·Bungie·Bethesda·Ubisoft·2K·Rockstar·CD Projekt·Larian·Paradox·Wargaming·Roblox·Mojang·WotC·Innersloth·Hello Games·Devolver·Annapurna·343 Industries 등 | 5차 |
| `2026-05-24-games-mobile` | 100 | 50 | **모바일 cross-region** — Supercell·King·Zynga·Scopely·Playrix·Plarium·Habby·Garena·Krafton mobile·COM2US Hive·Yostar global·Aniplex·Pokémon·GungHo·Niantic·Outfit7·Rovio 등 | 5차 |
| `2026-05-24-games-indie` | 100 | 50 | **인디 스튜디오·게임 매체/스토어** — itch.io·GOG·Humble·Klei·Re-Logic·Team Cherry·Iron Gate·Subset·PocketPair·Mintrocket·gamespot·ign·polygon·kotaku·eurogamer·pcgamer·rps·vg247·gamesindustry 등 | 5차 |
| `2026-05-24-games-mobile-gacha` | 100 | 50 | **모바일 가챠/CCG** — Sumzap·Akatsuki·Applibot·KLab·Pokelabo·Cygames sub·Aniplex 게임별·Bandai 게임별 sub·Yostar global·Manjuu·Sunborn·Kuro sub·Hypergryph sub·Infold·Shift Up nikke 글로벌·epic7 onstove·Crunchyroll Games 등 | 5차 b |
| `2026-05-24-games-mobile-casual` | 100 | 50 | **모바일 hyper-casual/match-3** — Voodoo·Lion·Homa·Crazy Labs·Rollic·SayGames·Azur·AppLovin·Playgendary·Gismart·Easybrain·MAG·Big Fish·Wooga·Tactile·Storm8·Pocket Gems·Yodo1·FRVR·ZeptoLab·Halfbrick·Ohayoo·Tripledot·Dream·Peak·Metacore·Socialpoint 등 | 5차 b |
| `2026-05-24-games-mobile-strategy-rpg` | 100 | 50 | **모바일 4X/SLG/midcore** — Plarium 게임별·Scopely 게임별·FunPlus 게임별·IGG 게임별·37Games·Century·Stillfront 자회사·InnoGames·Travian·Pixonic·Lilith 전략·Camel·Yotta·Joycity·Kabam·Glu·Skillz·Nexters Hero Wars·Topwar·Whiteout 등 | 5차 b |
| `2026-05-24-games-indie-studios-western` | 100 | 50 | **서구 인디 스튜디오** — Mossmouth·Whitethorn·Coffee Stain·Ghost Town·Megacrit·Maddy Makes·Tribute·Brace Yourself·Sokpop·Inkle·Failbetter·Bithell·Hopoo·Vlambeer·Crows Crows Crows·Nicalis·ZA/UM·Tarsier·Massive Monster·Necrosoft·Outersloth 등 | 5차 b |
| `2026-05-24-games-indie-studios-asia` | 100 | 50 | **JP/KR/CN/SEA 인디·doujin** — TYPE-MOON·07th Expansion·Liar-soft·Yuzusoft·Visual Arts·Nitroplus·DANGEN·Playism·Acquire·Eastasiasoft·Project Moon limbus·슈퍼크리에이티브·슈퍼플랜·RoyalCrow·TipsWorks·Pathea·Lemonsky·Mighty Bear·Toge·Mojiken 등 | 5차 b |
| `2026-05-24-games-indie-media-store` | 100 | 50 | **게임 매체/인디 큐레이션/소형 store** — IndieDB·ModDB·OpenCritic·MetaCritic·Giant Bomb·Destructoid·GameRant·Gematsu·Siliconera·Automaton·4Gamer·Famitsu·Game*Spark·디스이즈게임·게임메카·게임샷·17173·Duowan·Gamersky·3DMGame·Indienova·GamersGate·IndieGala 등 | 5차 b |

**4차(05-21) 합계: 500 링크 / 497 distinct host.** 1~3차에서 소진한 플랫폼(Discourse·GitHub·Arca·DCinside·Reddit·Steam·Wikipedia·Fandom·Inven·클리앙류)은 host 통째 배제.

**5차(05-24-games) 합계: 600 링크 / 300 distinct host (각 100 / 50 host = host당 2 fully exploited).** legacy(nexon/onstove/하요랩/루리웹/인벤/DC/아카/카페·블로그/스팀/닌텐도) host 통째 배제. 빌더 = `output/candidates/_build_2026-05-24-games.py`, prior 자동 glob 로드. codex 위임으로 6 THEMES 채움.

**5차 b(05-24-games 2nd wave) 합계: 600 링크 / 300 distinct host (각 100 / 50).** 인디·모바일 양 부족 보강 — 가챠·casual·strategy·서구 인디·아시아 인디·매체 6 세분. 빌더 = `output/candidates/_build_2026-05-24-games2.py`, 5차 1st 산출물까지 prior 로드. codex 위임. 합산 5차(1st+2nd) = 1200 링크 / 600 distinct host.

| `2026-05-24-games-official` | 100 | 50 | **게임 자체 official (게임명.com)** — terraria/valheim/balatro/vampire-survivors/factorio/rimworld/satisfactory/palworld/witcher/halo/forza/seaofthieves/warthunder/darktide/pathofexile/warframe/dota2/marvelrivals/residentevil/monsterhunter/persona 등 | 5차 c |
| `2026-05-24-games-crowdfund` | 100 | 4 | **펀딩 캠페인** — Kickstarter games(개별 캠페인 다수)·Fig·Indiegogo·BackerKit. host_cap 풀림(같은 host 안 캠페인 path 정상) | 5차 c |
| `2026-05-24-games-db-wiki` | 100 | 6 | **게임 DB/wiki/트래커** — GameFAQs 게임별 board·MobyGames·IGDB·HowLongToBeat·Backloggd·PCGamingWiki·SteamDB·TVTropes·fandom subdomain. host_cap=60 | 5차 c |
| `2026-05-24-games-mods-hub` | 100 | 5 | **mod hub** — NexusMods 게임별(40+)·Modrinth·CurseForge 게임별·GameBanana·Thunderstore 게임별·UESP. host_cap=60 | 5차 c |

**5차 c(05-24-games 3rd wave) 합계: 400 링크 / 65 distinct host.** 사용자 피드백 반영 — "회사 본사 마케팅 페이지" 빼고 *게임 단위 official + 펀딩 + DB + mod hub*. 빌더 = `output/candidates/_build_2026-05-24-games3.py`, per-theme host_cap (official=2, crowdfund=100, db/mods=60) + ignore_prior_hosts (kickstarter/nexusmods/igdb 등 prior 우회). 합산 5차(1st+2nd+3rd) = 1600 링크 / 665 distinct host.

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
