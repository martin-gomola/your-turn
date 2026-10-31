"""Global handoff install and uninstall, run against app folders under tmp_path (never the real home)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yourturn.cli import main
from yourturn.install import CLAUDE_BLOCK, END, START, install, uninstall

MINE = "# My rules\n\nKeep answers short.\n"
OTHER = {"mcpServers": {"context7": {"command": "npx", "args": ["context7"]}}}
# What an earlier version added to Cursor's mcp.json.
LEGACY = {"your-turn": {"type": "stdio", "command": "bash", "args": ["-lc", "uvx yourturn mcp"]}}


def _homes(tmp_path: Path) -> dict[str, Path]:
    homes = {name: tmp_path / name for name in ("codex", "claude", "cursor")}
    for home in homes.values():
        home.mkdir()
    return homes


def _tree(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): path.read_text() for path in sorted(root.rglob("*")) if path.is_file()}


def _fake(tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A CLI on an otherwise empty PATH that logs its arguments and its app-home variable."""
    bin_dir, log = tmp_path / "bin", tmp_path / f"{name}.log"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(f'#!/bin/sh\necho "$CODEX_HOME$CLAUDE_CONFIG_DIR|$*" >> {log}\nexit 0\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return log


@pytest.fixture
def no_clis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No codex or claude on PATH, and a project folder as the working directory that must stay empty."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def test_install_is_global_idempotent_and_uninstall_restores_the_files(tmp_path: Path, no_clis: Path) -> None:
    homes = _homes(tmp_path)
    (homes["claude"] / "CLAUDE.md").write_text(MINE)
    (homes["cursor"] / "mcp.json").write_text(json.dumps(OTHER))

    install(["claude", "cursor"], homes)
    first = _tree(tmp_path)
    claude_skill = (homes["claude"] / "skills" / "your-turn" / "SKILL.md").read_text()
    cursor_skill = (homes["cursor"] / "skills" / "your-turn" / "SKILL.md").read_text()
    assert "name: your-turn\n" in claude_skill and "Claude Code" in claude_skill and "`AskUserQuestion`" in claude_skill
    assert "Cursor" in cursor_skill and "`AskQuestion`" in cursor_skill and "Codex" not in cursor_skill
    assert "**Outcome:**" in cursor_skill and "**Next step:**" in cursor_skill and "**Decision:**" in cursor_skill
    assert "log_decision" not in cursor_skill and "MCP" not in cursor_skill
    assert (homes["claude"] / "CLAUDE.md").read_text() == f"{MINE}\n{CLAUDE_BLOCK}"
    assert "**Decision:**" in CLAUDE_BLOCK
    assert json.loads((homes["cursor"] / "mcp.json").read_text()) == OTHER  # Not touched: nothing to register.
    # Nothing lands in the project, and Codex (not selected) is untouched.
    assert list(no_clis.iterdir()) == [] and list(homes["codex"].iterdir()) == []

    install(["claude", "cursor"], homes)
    assert _tree(tmp_path) == first

    uninstall(["claude", "cursor"], homes)
    assert (homes["claude"] / "CLAUDE.md").read_text() == MINE
    assert json.loads((homes["cursor"] / "mcp.json").read_text()) == OTHER
    assert not (homes["claude"] / "skills" / "your-turn").exists() and not (homes["cursor"] / "skills" / "your-turn").exists()
    after = _tree(tmp_path)
    uninstall(["claude", "cursor"], homes)
    assert _tree(tmp_path) == after


def test_block_is_replaced_in_place_and_files_it_created_are_removed(tmp_path: Path, no_clis: Path) -> None:
    homes = _homes(tmp_path)
    memory = homes["claude"] / "CLAUDE.md"
    memory.write_text(f"Above.\n\n{START}\nold handoff text\n{END}\n\nBelow.\n")
    install(["claude"], homes)
    assert memory.read_text() == f"Above.\n\n{CLAUDE_BLOCK}\nBelow.\n"
    uninstall(["claude"], homes)
    assert memory.read_text() == "Above.\n\nBelow.\n"

    # Files that held only what install wrote are gone again, so uninstall leaves no empty leftovers.
    memory.unlink()
    install(["claude", "cursor"], homes)
    uninstall(["claude", "cursor"], homes)
    assert not memory.exists() and list(homes["cursor"].iterdir()) == [homes["cursor"] / "skills"]


def test_install_removes_the_mcp_server_an_earlier_version_added(tmp_path: Path, no_clis: Path) -> None:
    homes = _homes(tmp_path)
    mcp = homes["cursor"] / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {**OTHER["mcpServers"], **LEGACY}}))
    install(["cursor"], homes)
    assert json.loads(mcp.read_text()) == OTHER
    # A file that held only our server goes away; an unreadable one is left alone.
    mcp.write_text(json.dumps({"mcpServers": LEGACY}))
    install(["cursor"], homes)
    assert not mcp.exists()
    mcp.write_text("{not json")
    uninstall(["cursor"], homes)
    assert mcp.read_text() == "{not json"


def test_claude_legacy_mcp_server_is_removed_through_the_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    homes = _homes(tmp_path)
    log = _fake(tmp_path, "claude", monkeypatch)
    install(["claude"], homes)
    uninstall(["claude"], homes)
    home = str(homes["claude"])
    # Only ever removed: nothing is added at user scope any more.
    assert log.read_text().splitlines() == [f"{home}|mcp remove --scope user your-turn"] * 2


def test_codex_uninstall_removes_the_plugin_and_marketplace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    homes = _homes(tmp_path)
    log = _fake(tmp_path, "codex", monkeypatch)
    uninstall(["codex"], homes)
    home = str(homes["codex"])
    assert log.read_text().splitlines() == [f"{home}|plugin remove your-turn@your-turn", f"{home}|plugin marketplace remove your-turn"]


def test_cli_uninstall_only_touches_apps_that_are_present(tmp_path: Path, no_clis: Path) -> None:
    claude = tmp_path / "claude"
    install(["claude"], {"claude": claude})
    main(["uninstall", "--codex-home", str(tmp_path / "no-codex"), "--claude-home", str(claude),
          "--cursor-home", str(tmp_path / "no-cursor")])
    assert not (claude / "skills" / "your-turn").exists() and not (claude / "CLAUDE.md").exists()
    assert not (tmp_path / "no-codex").exists() and not (tmp_path / "no-cursor").exists()


def test_cli_install_exits_after_setup(tmp_path: Path, no_clis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = tmp_path / "claude"
    main(["install", "--harness", "claude", "--claude-home", str(claude)])  # Returns instead of serving.
    assert (claude / "skills" / "your-turn" / "SKILL.md").is_file()
    # Run through uvx, `your-turn` is not on PATH, so the hint is the full command.
    assert capsys.readouterr().out.endswith("Start the inbox with: uvx --from git+https://github.com/martin-gomola/your-turn your-turn serve\n")
