"""adapters 패키지의 BaseAdapter / NoticePost 재노출.

engine 은 adapters.base 의 인터페이스 위에 얹힌다. cross-package import 를 여기 한 곳에 모은다.
(프로젝트 루트가 sys.path 에 있어야 한다 — scripts/* 가 처리.)
"""
from __future__ import annotations

from adapters.base import BaseAdapter, NoticePost  # noqa: F401
