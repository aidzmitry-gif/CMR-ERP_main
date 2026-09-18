from __future__ import annotations

import pytest

from scripts.quality import source_snapshot

pytestmark = pytest.mark.unit


def test_actual_submodule_heads_marks_matching_and_drifted_worktrees(monkeypatch):
    def fake_git(args, cwd=source_snapshot.ROOT):
        if args == ["rev-parse", "HEAD"]:
            return 0, {"a": "abc", "b": "xyz"}[cwd.name], ""
        if args == ["branch", "--show-current"]:
            return 0, f"branch-{cwd.name}", ""
        raise AssertionError(args)

    monkeypatch.setattr(source_snapshot, "_git", fake_git)
    records, issues = source_snapshot.actual_submodule_heads(
        {"modules/a": "abc", "modules/b": "def"}
    )

    assert issues == []
    assert records == [
        {
            "path": "modules/a",
            "parentGitlink": "abc",
            "worktreeHead": "abc",
            "worktreeBranch": "branch-a",
            "matchesParentGitlink": True,
        },
        {
            "path": "modules/b",
            "parentGitlink": "def",
            "worktreeHead": "xyz",
            "worktreeBranch": "branch-b",
            "matchesParentGitlink": False,
        },
    ]


def test_parent_gitlinks_parse_submodule_entries(monkeypatch):
    def fake_git(args, cwd=source_snapshot.ROOT):
        if args == ["rev-parse", "HEAD"]:
            return 0, "parent", ""
        if args == ["ls-tree", "-r", "HEAD", "--", "modules"]:
            return 0, "160000 commit abc\tmodules/a\n100644 blob ignored\tREADME.md", ""
        raise AssertionError(args)

    monkeypatch.setattr(source_snapshot, "_git", fake_git)
    expected, head, issues = source_snapshot.parent_gitlinks()

    assert expected == {"modules/a": "abc"}
    assert head == "parent"
    assert issues == []


def test_parent_gitlinks_rejects_empty_tree(monkeypatch):
    def fake_git(args, cwd=source_snapshot.ROOT):
        if args == ["rev-parse", "HEAD"]:
            return 0, "parent", ""
        if args == ["ls-tree", "-r", "HEAD", "--", "modules"]:
            return 0, "100644 blob ignored\tREADME.md", ""
        raise AssertionError(args)

    monkeypatch.setattr(source_snapshot, "_git", fake_git)
    expected, head, issues = source_snapshot.parent_gitlinks()

    assert expected == {}
    assert head == "parent"
    assert issues == ["parent gitlinks empty: source snapshot cannot be verified"]
