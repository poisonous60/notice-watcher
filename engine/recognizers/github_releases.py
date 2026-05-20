"""GitHub repo Releases 페이지 → httpx_html.

URL 폼: https://github.com/<owner>/<repo>/releases
  - board = <owner>/<repo>. URL path 의 첫 두 segment.
  - /releases literal 필수 — repo 홈·/issues·/pulls·/tree/...·/wiki 는 release 아님(다른 종류 페이지).
  - /releases/tag/<ver> (개별 release) 도 제외 — 그건 단일 article, board 아님.

승급 출처: batch-register 가 만든 자동생성 config 19건(anthropics/claude-code, denoland/deno, …)이
모두 github.com/<owner>/<repo>/releases 폼 → recognizer-extension 으로 묶음 (2026-05-20).

주의 — 기존 자동생성 config 와 *기능 필드 byte-match 안 함*:
  LLM 이 repo 마다 다른(일부 버그난) selector·board 를 뽑았다 (board="godot"/"releases" 등 오류,
  per-repo author selector a[href^='/bartlomieju'] 같은 noise). 이 recognizer 는 그 noise 를
  교정한 *canonical* config — release 리스트 DOM 은 repo 불문 동일하므로 robust selector 하나로 충분.
  따라서 round-trip 검증은 "기존 config 재현"이 아니라 "각 멤버 URL → board=owner/repo·url_template
  정확 추출 + 같은-host 다른-종류 페이지 negative" 로 한다 (test_github_releases.py 참고).
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "github-releases"

# github.com/<owner>/<repo>/releases — 끝 anchor 로 /releases/tag/<ver>(개별 release) 제외.
# owner/repo 는 single path segment ([^/?#]+) — 더 깊은 path(/tree, /issues 등) 자동 배제.
_RE = re.compile(
    r"//github\.com/([^/?#]+)/([^/?#]+)/releases/?(?:[?#].*)?$", re.I
)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    owner, repo = m.group(1), m.group(2)
    board = f"{owner}/{repo}"
    list_url = f"https://github.com/{board}/releases"
    return {
        "version": 1,
        "site": "github.com",
        "board": board,
        "strategy": "httpx_html",
        "_slug_board": f"{owner}_{repo}",
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": list_url,
        },
        "timeout": 15,
        "polite_sleep": {"min": 1, "max": 1},
        "list": {
            "url_template": "https://github.com/{board}/releases",
            "pagination": {"kind": "query_param", "page_param": "page"},
            # release 리스트는 data-hpc 래퍼 안의 <section> 한 개당 한 release.
            "row_selector": "div[data-hpc] > section",
            # 실제 release row 만 — tag 링크 있는 section 으로 한정.
            "row_required_selector": "a[href*='/releases/tag/']",
            "include_notices": True,
            "fields": {
                "post_id": [
                    {
                        "from": "attr",
                        "selector": "a[href*='/releases/tag/']",
                        "attr": "href",
                        "transform": [["regex_extract", "/releases/tag/([^/?#]+)"]],
                    }
                ],
                "title": [
                    {
                        "from": "css",
                        "selector": "h2.sr-only",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    },
                    {
                        "from": "css",
                        "selector": "a[href*='/releases/tag/']",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    },
                ],
                "url": [
                    {
                        "from": "attr",
                        "selector": "a[href*='/releases/tag/']",
                        "attr": "href",
                        "transform": [["urljoin", "https://github.com"]],
                    },
                    {
                        "from": "template",
                        "value": "https://github.com/{board}/releases/tag/{post_id}",
                    },
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "relative-time",
                        "attr": "datetime",
                        "transform": [["iso8601", ["%Y-%m-%dT%H:%M:%SZ"]]],
                    }
                ],
                "author": [
                    {
                        "from": "css",
                        "selector": "div.Box-body img[alt^='@']",
                        "attr": "alt",
                        "transform": [["replace", "@", ""], ["collapse_ws"]],
                    }
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {
                    "from": "css",
                    "selector": "div.markdown-body[data-test-selector='body-content']",
                    "html": True,
                },
                {"from": "css", "selector": "div.markdown-body", "html": True},
            ],
        },
        "_source_url": list_url,
        "_note": (
            f"GitHub Releases({board}) — known-platform 자동 인식. 리스트 "
            "github.com/<owner>/<repo>/releases (div[data-hpc]>section 행, tag 링크 필수), "
            "post_id 는 /releases/tag/<ver> href 에서 추출, title h2.sr-only, "
            "published_at relative-time[datetime], 본문 div.markdown-body[body-content]. "
            "board=owner/repo 는 URL path 에서 추출."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
