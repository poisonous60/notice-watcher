"""사이트 정찰(probe) 도구.

목록 URL 하나에 대해:
- 어떤 경로로 접근 가능한가?
- request 입출력은 어떻게 되는가?
- 목록 글에 접근 가능한가?

를 매트릭스로 진단해 raw 아티팩트 + summary를 디스크에 저장한다.
"""
from .types import Result, Diagnosis, Classification

__all__ = ["Result", "Diagnosis", "Classification"]
