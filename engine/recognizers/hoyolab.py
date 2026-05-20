"""HoYoLAB 공식 게시판 → httpx_json (내부 API: bbs-api-os.hoyolab.com getNewsList).

URL 폼: https://www.hoyolab.com/circles/<gid>/<type>/official?lang=<lang>
  - gid = 게임 id (2=Genshin, 6=HSR, 8=ZZZ …). 페이지 path 의 첫 번째 숫자.
  - <type>(보통 0)·lang(기본 ko-kr) 은 목록 API 에 안 쓰임 (gids 만 필요).

승급 출처: 자동생성된 개별 config 3건(circles 2/6/8) 이 gids 숫자 빼고 완전 동일 →
recognizer-extension 으로 묶음 (2026-05-20). gid 만 URL path 에서 추출하면 builder 가 결정적 재현.
genshin(2)/hsr(6) 은 LLM 생성 시 rc=1 실패했으나 같은 skeleton 으로 자동 커버됨.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA, qs

NAME = "hoyolab"

# /circles/<gid>/<type>/official — gid 는 첫 숫자 path segment. official 게시판만 (recommend/한글 등 제외).
_RE = re.compile(r"//www\.hoyolab\.com/circles/(\d+)/\d+/official\b", re.I)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    gid = m.group(1)
    lang = qs(url).get("lang", "ko-kr")
    view_url = f"https://www.hoyolab.com/circles/{gid}/0/official?lang={lang}"
    return {
        "version": 1,
        "site": "www.hoyolab.com",
        "board": f"circles_{gid}_official",
        "strategy": "httpx_json",
        "_slug_board": f"circles_{gid}_official",
        "headers": {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "x-rpc-language": lang,
            "Referer": view_url,
            "Origin": "https://www.hoyolab.com",
        },
        "timeout": 15,
        "list": {
            "url_template": f"https://bbs-api-os.hoyolab.com/community/post/wapi/getNewsList?gids={gid}&type=1",
            "pagination": {"kind": "query_param", "page_param": "page", "size_param": "page_size"},
            "page_size_max": 15,
            "success_when": {"path": ["retcode"], "equals": 0},
            "list_path": ["data", "list"],
            "fields": {
                "post_id": [{"from": "json", "path": ["post", "post_id"]}],
                "title": [{"from": "json", "path": ["post", "subject"]}],
                "url": [{"from": "template", "value": "https://www.hoyolab.com/article/{post_id}"}],
                "published_at": [{"from": "json", "path": ["post", "created_at"], "transform": [["unixtime_to_iso", "+09:00", "s"]]}],
                "cover_image": [{"from": "json", "path": ["post", "cover"]}],
            },
        },
        "article": {
            "url_template": "https://bbs-api-os.hoyolab.com/community/post/wapi/getPostFull?post_id={post_id}",
            "fetch_kind": "json",
            "body_empty_acceptable": True,
            "success_when": {"path": ["retcode"], "equals": 0},
            "data_path": ["data", "post"],
            "content": [{"from": "json", "path": ["post", "content"]}],
        },
        "_source_url": view_url,
        "_note": (f"HoYoLAB official 게시판(gid={gid}) — known-platform 자동 인식. 목록 "
                  f"bbs-api-os.hoyolab.com/.../getNewsList?gids={gid}&type=1 (query_param 페이징, retcode==0, "
                  "list_path data.list, post_id/subject/created_at 는 entry.post 하위), 본문 .../getPostFull?post_id= "
                  "→ data.post.content. 헤더 UA + x-rpc-language + Referer/Origin. gid 만 URL path 에서 추출."),
    }


PATTERNS = [
    (_RE, _build),
]
