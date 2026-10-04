import pytest

from version_bump import gitops
from version_bump.errors import GitError


def test_show_file_and_missing(repo):
    repo.write("a.txt", "one\n")
    sha = repo.commit("chore: init")
    assert gitops.show_file(repo.path, sha, "a.txt") == "one\n"
    assert gitops.show_file(repo.path, sha, "nope.txt") is None
    assert gitops.show_file(repo.path, "HEAD", "a.txt") == "one\n"
    repo.write("crlf.txt", "a\r\nb\r\n")
    sha2 = repo.commit("chore: crlf")
    assert gitops.show_file(repo.path, sha2, "crlf.txt") == "a\r\nb\r\n"


def test_parent_and_changed_paths(repo):
    repo.write("a.txt", "one\n")
    root = repo.commit("chore: init")
    repo.write("b/c.txt", "two\n")
    repo.write("a.txt", "three\n")
    second = repo.commit("fix: two files")
    assert gitops.parent(repo.path, root) is None
    assert gitops.parent(repo.path, second) == root
    assert gitops.changed_paths(repo.path, root) == ["a.txt"]
    assert gitops.changed_paths(repo.path, second) == ["a.txt", "b/c.txt"]


def test_first_parent_range_and_subjects(repo):
    repo.write("a", "0")
    base = repo.commit("chore: base")
    repo.write("a", "1")
    c1 = repo.commit("fix: one")
    repo.write("a", "2")
    c2 = repo.commit("feat: two")
    assert gitops.first_parent_range(repo.path, base, "HEAD") == [c1, c2]
    assert gitops.first_parent_range(repo.path, c2, "HEAD") == []
    assert gitops.subject(repo.path, c2) == "feat: two"


def test_first_parent_range_skips_second_parent_commits(repo):
    repo.write("a", "0")
    base = repo.commit("chore: base")
    repo.git("checkout", "-q", "-b", "topic")
    repo.write("b", "1")
    repo.commit("fix: on topic")
    repo.git("checkout", "-q", "main")
    repo.write("a", "1")
    on_main = repo.commit("fix: on main")
    merge = repo.merge_branch("topic", "Merge branch 'topic'")
    assert gitops.first_parent_range(repo.path, base, "HEAD") == [on_main, merge]
    assert gitops.changed_paths(repo.path, merge) == ["b"]


def test_commits_touching(repo):
    repo.write(".version", "1")
    c1 = repo.commit("chore: v")
    repo.write("other", "x")
    repo.commit("fix: other")
    repo.write(".version", "2")
    c3 = repo.commit("chore: v2")
    assert gitops.commits_touching(repo.path, "HEAD", [".version"]) == [c3, c1]
    assert gitops.commits_touching(repo.path, "HEAD", ["missing"]) == []


def test_tags(repo):
    repo.write("a", "0")
    sha = repo.commit("chore: base")
    assert gitops.tag_target(repo.path, "v1.0.0") is None
    gitops.create_tag(repo.path, "v1.0.0", sha)
    assert gitops.tag_target(repo.path, "v1.0.0") == sha


def test_git_error(repo):
    with pytest.raises(GitError, match="rev-parse"):
        gitops.rev_parse(repo.path, "does-not-exist")
