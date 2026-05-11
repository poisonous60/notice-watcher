"""config 기반 범용 크롤링 엔진.

- ConfigAdapter / make_adapter : 선언적 config(JSON) 를 실행하는 어댑터
- validate_config            : config 검증
- TRANSFORMS / transform_names : 닫힌 transform 라이브러리
- CONFIG_JSON_SCHEMA          : (느슨한) JSON Schema

자세한 config 포맷은 engine/config_schema.py 의 docstring + engine/extract_helpers.py 참고.
"""
from __future__ import annotations

from .base_compat import BaseAdapter, NoticePost
from .config_adapter import ConfigAdapter, make_adapter, load_config, load_config_dir
from .config_schema import CONFIG_JSON_SCHEMA, ConfigError, validate_config, is_valid
from .transforms import TRANSFORMS, transform_names, apply_chain

__all__ = [
    "BaseAdapter",
    "NoticePost",
    "ConfigAdapter",
    "make_adapter",
    "load_config",
    "load_config_dir",
    "CONFIG_JSON_SCHEMA",
    "ConfigError",
    "validate_config",
    "is_valid",
    "TRANSFORMS",
    "transform_names",
    "apply_chain",
]
