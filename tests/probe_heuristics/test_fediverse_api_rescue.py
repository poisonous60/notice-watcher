"""scripts.register._try_fediverse_api_rescue — rc=5 fediverse API rescue."""
from __future__ import annotations


class _Response:
    def __init__(self, status_code: int, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


def run() -> list[tuple[str, bool, str]]:
    import scripts.register as register

    cases: list[tuple[str, bool, str]] = []
    original_get = register.httpx.get if hasattr(register, "httpx") else None
    original_register = register._register_built_config

    def _case(name: str, url: str, responses: dict[str, _Response], expected_platform: str) -> None:
        calls: list[str] = []
        registered: list[dict] = []

        def fake_get(api_url, **kwargs):  # noqa: ANN001, ARG001
            calls.append(api_url)
            return responses.get(api_url, _Response(404, {}))

        def fake_register(cfg, slug, source_url, *, out, force):  # noqa: ANN001, ARG001
            registered.append(cfg)
            return 0

        register.httpx.get = fake_get
        register._register_built_config = fake_register
        try:
            rc = register._try_fediverse_api_rescue(url, "slug", out=None, force=False)
        finally:
            register._register_built_config = original_register
            if original_get is not None:
                register.httpx.get = original_get
        cases.append((
            name,
            rc == 0
            and registered
            and expected_platform in registered[0].get("_recognized_platform", "")
            and calls,
            f"rc={rc!r} registered={registered!r} calls={calls!r}",
        ))

    _case(
        "lemmy_site_api_rescues",
        "https://lemmy.example/",
        {"https://lemmy.example/api/v3/site": _Response(200, {"site_view": {"site": {"name": "Lemmy"}}})},
        "lemmy",
    )
    _case(
        "mbin_entries_api_rescues_after_lemmy_miss",
        "https://mbin.example/",
        {
            "https://mbin.example/api/v3/site": _Response(404, {}),
            "https://mbin.example/api/entries?sortBy=newest&perPage=10": _Response(200, {"items": []}),
        },
        "mbin",
    )

    return cases
