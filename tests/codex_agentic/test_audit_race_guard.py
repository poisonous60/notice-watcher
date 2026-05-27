from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from generate import codex_agentic as ca  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return proc.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _entry(text: str) -> ca._AuditEntry:
    data = text.encode("utf-8")
    return ca._AuditEntry(
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        mtime_ns=0,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Audit Test")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "guarded.py").write_text("pre\n", encoding="utf-8")
    _commit(repo, "pre")
    return repo


def test_same_head_keeps_content_change_violation(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")

    before = {str(repo / "scripts" / "guarded.py"): _entry("pre\n")}
    after = {str(repo / "scripts" / "guarded.py"): _entry("agent edit\n")}

    violations = ca._audit_diff(
        before,
        after,
        self_slug="slug",
        configs_root=repo / "configs",
        pre_head=head,
        post_head=head,
    )

    assert violations == [f"{repo / 'scripts' / 'guarded.py'} (CONTENT CHANGED)"]


def test_head_advance_allows_pulled_tracked_change(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pre_head = _git(repo, "rev-parse", "HEAD")
    before = ca._audit_snapshot_paths(repo, "slug")

    (repo / "scripts" / "guarded.py").write_text("pulled\n", encoding="utf-8")
    post_head = _commit(repo, "post")
    after = ca._audit_snapshot_paths(repo, "slug")

    assert ca._audit_diff(
        before,
        after,
        self_slug="slug",
        configs_root=repo / "configs",
        pre_head=pre_head,
        post_head=post_head,
    ) == []


def test_head_advance_still_flags_worktree_edit_on_pulled_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pre_head = _git(repo, "rev-parse", "HEAD")
    before = ca._audit_snapshot_paths(repo, "slug")

    (repo / "scripts" / "guarded.py").write_text("pulled\n", encoding="utf-8")
    post_head = _commit(repo, "post")
    (repo / "scripts" / "guarded.py").write_text("agent edit\n", encoding="utf-8")
    after = ca._audit_snapshot_paths(repo, "slug")

    violations = ca._audit_diff(
        before,
        after,
        self_slug="slug",
        configs_root=repo / "configs",
        pre_head=pre_head,
        post_head=post_head,
    )

    assert violations == [f"{repo / 'scripts' / 'guarded.py'} (CONTENT CHANGED)"]


def test_head_advance_flags_changed_path_outside_pull_set(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pre_head = _git(repo, "rev-parse", "HEAD")
    before = ca._audit_snapshot_paths(repo, "slug")

    (repo / "README.md").write_text("pulled\n", encoding="utf-8")
    post_head = _commit(repo, "post")
    (repo / "scripts" / "guarded.py").write_text("agent edit\n", encoding="utf-8")
    after = ca._audit_snapshot_paths(repo, "slug")

    violations = ca._audit_diff(
        before,
        after,
        self_slug="slug",
        configs_root=repo / "configs",
        pre_head=pre_head,
        post_head=post_head,
    )

    assert violations == [f"{repo / 'scripts' / 'guarded.py'} (CONTENT CHANGED)"]


def test_unavailable_head_warns_and_falls_back_to_old_behavior(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "not-git"
    repo.mkdir()

    before = {str(repo / "scripts" / "guarded.py"): _entry("pre\n")}
    after = {str(repo / "scripts" / "guarded.py"): _entry("pulled\n")}
    snapshot, head = ca._audit_snapshot(repo, "slug")

    violations = ca._audit_diff(
        before,
        after,
        self_slug="slug",
        configs_root=repo / "configs",
        pre_head=head,
        post_head="different",
    )

    assert snapshot == {}
    assert head is None
    assert violations == [f"{repo / 'scripts' / 'guarded.py'} (CONTENT CHANGED)"]
    assert "[audit] HEAD snapshot unavailable" in capsys.readouterr().err
