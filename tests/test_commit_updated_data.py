"""Push generated data onto origin/main that moved during generation.

The production step is scripts/commit-updated-data.sh. The pre-fix step is
tests/fixtures/old_commit_updated_data.sh (run 40418054139: `git push` with no
fetch). Point COMMIT_DATA_SCRIPT at that fixture and
test_remote_advance_without_content_conflict_pushes_generated_files_only
fails with "fetch first". The default script rebases and pushes when the
remote commits do not touch the generated files, and aborts when they do.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW_SCRIPT = ROOT / "scripts" / "commit-updated-data.sh"
OLD_SCRIPT = ROOT / "tests" / "fixtures" / "old_commit_updated_data.sh"

BASE_FILES = {
    "README.md": "base\n",
    "data/programs-latest.json": '{"v":1}\n',
    "data/programs-2026-10-12.json": '{"date":"2026-10-12"}\n',
    "web/static/data/programs-latest.json": '{"v":1}\n',
    "web/static/data/programs-2026-10-12.json": '{"date":"2026-10-12"}\n',
}


def _git_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["GIT_CONFIG_GLOBAL"] = str(empty)
    env["GIT_CONFIG_SYSTEM"] = str(empty)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_AUTHOR_NAME"] = "Seed"
    env["GIT_AUTHOR_EMAIL"] = "seed@example.com"
    env["GIT_COMMITTER_NAME"] = "Seed"
    env["GIT_COMMITTER_EMAIL"] = "seed@example.com"
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX"):
        env.pop(key, None)
    return env


def _git(
    cwd: Path,
    *args: str,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} -> {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _selected_script() -> Path:
    raw = os.environ.get("COMMIT_DATA_SCRIPT", "")
    if not raw:
        return NEW_SCRIPT
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _run(
    clone: Path,
    env: dict[str, str],
    script: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    chosen = script if script is not None else _selected_script()
    run_env = dict(env)
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        run_env.pop(key, None)
    return subprocess.run(
        ["bash", str(chosen)],
        cwd=clone,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"exit={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _subjects(repo: Path, env: dict[str, str], rev: str = "main") -> list[str]:
    return _git(repo, "log", "--format=%s", rev, env=env).stdout.splitlines()


def _rebase_in_progress(clone: Path) -> bool:
    git_dir = clone / ".git"
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _setup(
    tmp_path: Path,
    remote_commits: list[tuple[str, dict[str, str]]],
    local_edits: dict[str, str],
    *,
    delete_local: tuple[str, ...] = (),
) -> tuple[dict[str, str], Path, Path]:
    """Shallow clone of base, then move origin/main, then edit the clone.

    This matches actions/checkout (fetch-depth 1) followed by a main that
    advances while data is generated.
    """
    env = _git_env(tmp_path)
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin), env=env)
    _git(tmp_path, "init", "-b", "main", str(seed), env=env)
    for rel, text in BASE_FILES.items():
        _write(seed / rel, text)
    _git(seed, "add", ".", env=env)
    _git(seed, "commit", "-m", "base", env=env)
    _git(seed, "remote", "add", "origin", str(origin), env=env)
    _git(seed, "push", "-u", "origin", "main", env=env)
    _git(
        tmp_path,
        "-c",
        "protocol.file.allow=always",
        "clone",
        "--depth",
        "1",
        origin.as_uri(),
        str(clone),
        env=env,
    )
    assert _git(clone, "rev-parse", "--is-shallow-repository", env=env).stdout.strip() == "true"
    _git(clone, "config", "protocol.file.allow", "always", env=env)

    for message, files in remote_commits:
        for rel, text in files.items():
            _write(seed / rel, text)
            _git(seed, "add", "--", rel, env=env)
        _git(seed, "commit", "-m", message, env=env)
        _git(seed, "push", "origin", "main", env=env)

    for rel, text in local_edits.items():
        _write(clone / rel, text)
    for rel in delete_local:
        (clone / rel).unlink()
    return env, origin, clone


def _generated_local_edits() -> dict[str, str]:
    return {
        "data/programs-latest.json": '{"v":2}\n',
        "web/static/data/programs-latest.json": '{"v":2}\n',
        "data/programs-2026-11-02.json": '{"date":"2026-11-02"}\n',
        "web/static/data/programs-2026-11-02.json": '{"date":"2026-11-02"}\n',
        "notes.tmp": "not generated\n",
    }


def _remote_advance() -> list[tuple[str, dict[str, str]]]:
    return [
        ("advance main", {"README.md": "advanced\n"}),
        ("advance main again", {"README.md": "advanced again\n"}),
    ]


def test_remote_advance_without_content_conflict_pushes_generated_files_only(tmp_path):
    env, origin, clone = _setup(
        tmp_path,
        _remote_advance(),
        _generated_local_edits(),
        delete_local=(
            "data/programs-2026-10-12.json",
            "web/static/data/programs-2026-10-12.json",
        ),
    )

    result = _run(clone, env)

    assert result.returncode == 0, _detail(result)
    assert _subjects(origin, env)[:3] == [
        "chore: update programs data",
        "advance main again",
        "advance main",
    ]
    assert _git(clone, "rev-parse", "HEAD", env=env).stdout == _git(
        origin, "rev-parse", "main", env=env
    ).stdout
    parent_subject = _git(clone, "log", "-1", "--format=%s", "HEAD^", env=env).stdout.strip()
    assert parent_subject == "advance main again"
    parents = [
        line
        for line in _git(clone, "cat-file", "-p", "HEAD", env=env).stdout.splitlines()
        if line.startswith("parent ")
    ]
    assert len(parents) == 1
    names = _git(
        clone, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", env=env
    ).stdout.splitlines()
    assert set(names) == {
        "data/programs-latest.json",
        "data/programs-2026-10-12.json",
        "data/programs-2026-11-02.json",
        "web/static/data/programs-latest.json",
        "web/static/data/programs-2026-10-12.json",
        "web/static/data/programs-2026-11-02.json",
    }
    assert _git(clone, "show", "HEAD:README.md", env=env).stdout == "advanced again\n"
    assert _git(clone, "show", "HEAD:data/programs-latest.json", env=env).stdout == '{"v":2}\n'
    assert _git(clone, "cat-file", "-e", "HEAD:notes.tmp", env=env, check=False).returncode != 0
    assert _git(
        clone, "cat-file", "-e", "HEAD:data/programs-2026-10-12.json", env=env, check=False
    ).returncode != 0
    identity = _git(clone, "log", "-1", "--format=%an%n%ae%n%cn%n%ce", env=env).stdout.splitlines()
    assert identity == [
        "github-actions[bot]",
        "github-actions[bot]@users.noreply.github.com",
        "github-actions[bot]",
        "github-actions[bot]@users.noreply.github.com",
    ]
    assert not _rebase_in_progress(clone)
    porcelain = _git(clone, "status", "--porcelain", env=env).stdout.splitlines()
    assert porcelain == ["?? notes.tmp"]


def test_push_succeeds_when_main_has_not_moved(tmp_path):
    env, origin, clone = _setup(tmp_path, [], _generated_local_edits())

    result = _run(clone, env)

    assert result.returncode == 0, _detail(result)
    assert _subjects(origin, env)[:2] == ["chore: update programs data", "base"]
    assert _git(clone, "rev-parse", "HEAD", env=env).stdout == _git(
        origin, "rev-parse", "main", env=env
    ).stdout
    parent_subject = _git(clone, "log", "-1", "--format=%s", "HEAD^", env=env).stdout.strip()
    assert parent_subject == "base"
    assert not _rebase_in_progress(clone)


def test_old_push_without_fetch_is_rejected_when_main_advances(tmp_path):
    env, origin, clone = _setup(tmp_path, _remote_advance(), _generated_local_edits())
    before = _git(origin, "rev-parse", "main", env=env).stdout

    result = _run(clone, env, OLD_SCRIPT)

    assert result.returncode != 0, _detail(result)
    assert "[rejected]" in result.stderr
    assert "fetch first" in result.stderr
    assert "failed to push some refs" in result.stderr
    assert _git(origin, "rev-parse", "main", env=env).stdout == before
    assert "chore: update programs data" not in _subjects(origin, env)


def test_rebase_content_conflict_aborts_and_does_not_push(tmp_path):
    env, origin, clone = _setup(
        tmp_path,
        [("remote data edit", {"data/programs-latest.json": '{"v":3}\n'})],
        {
            "data/programs-latest.json": '{"v":2}\n',
            "web/static/data/programs-latest.json": '{"v":2}\n',
        },
    )
    before = _git(origin, "rev-parse", "main", env=env).stdout

    result = _run(clone, env)

    assert result.returncode == 1, _detail(result)
    combined = result.stdout + result.stderr
    assert "CONFLICT" in combined
    assert "aborting without push" in result.stderr
    assert not _rebase_in_progress(clone)
    assert "interactive rebase in progress" not in _git(clone, "status", env=env).stdout
    assert _git(origin, "rev-parse", "main", env=env).stdout == before
    assert _subjects(origin, env)[0] == "remote data edit"
    assert (clone / "data" / "programs-latest.json").read_text() == '{"v":2}\n'
    assert "<<<<<<<" not in (clone / "data" / "programs-latest.json").read_text()
    assert _git(clone, "status", "--porcelain", env=env).stdout == ""
    assert _git(origin, "show", "main:data/programs-latest.json", env=env).stdout == '{"v":3}\n'


def test_rejected_push_stays_a_failure(tmp_path):
    env, origin, clone = _setup(
        tmp_path,
        [("advance main", {"README.md": "advanced\n"})],
        {"data/programs-latest.json": '{"v":2}\n'},
    )
    before = _git(origin, "rev-parse", "main", env=env).stdout
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'pre-receive: rejected' >&2\nexit 1\n")
    hook.chmod(0o755)

    result = _run(clone, env)

    assert result.returncode != 0, _detail(result)
    assert "aborting without push" not in result.stderr
    assert "rejected" in result.stderr.lower()
    assert not _rebase_in_progress(clone)
    assert _git(origin, "rev-parse", "main", env=env).stdout == before
    assert "chore: update programs data" not in _subjects(origin, env)


def test_no_data_change_does_not_create_a_commit_when_main_advances(tmp_path):
    env, origin, clone = _setup(
        tmp_path,
        [("advance main", {"README.md": "advanced\n"})],
        {},
    )

    result = _run(clone, env)

    assert result.returncode == 0, _detail(result)
    assert _subjects(origin, env)[0] == "advance main"
    assert "chore: update programs data" not in _subjects(origin, env)
    assert _git(clone, "rev-parse", "HEAD", env=env).stdout == _git(
        origin, "rev-parse", "main", env=env
    ).stdout
    assert _git(clone, "status", "--porcelain", env=env).stdout == ""


def _step(workflow: str, name: str) -> str:
    marker = f"name: {name}\n"
    start = workflow.index(marker)
    rest = workflow[start + len(marker):]
    next_step = rest.find("\n      - name:")
    if next_step == -1:
        return workflow[start:]
    return workflow[start:start + len(marker) + next_step]


def test_commit_step_delegates_to_script_and_other_workflows_do_not_push():
    workflow = (ROOT / ".github" / "workflows" / "data-update.yml").read_text()
    script = NEW_SCRIPT.read_text()
    step = _step(workflow, "Commit updated data")

    assert "bash scripts/commit-updated-data.sh" in step
    assert "inputs.smoke_only != true" in step
    assert "git push" not in step
    assert "git fetch" not in step
    assert "git push" not in workflow
    assert "git pull" not in workflow
    assert "git merge" not in workflow
    assert "--force-with-lease" not in workflow

    commands = [
        line.strip()
        for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert any("git fetch origin main" in line for line in commands)
    assert any("git rebase origin/main" in line for line in commands)
    assert any("git rebase --abort" in line for line in commands)
    assert sum(line == "git push" or line.startswith("git push ") for line in commands) == 1
    assert "git add data/ web/static/data/" in script
    assert "--force" not in script
    assert "force-with-lease" not in script
    assert "git pull" not in script
    assert "git merge" not in script

    for name in ("record.yml", "deploy-pages.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        assert "git push" not in text
        assert "git commit" not in text
