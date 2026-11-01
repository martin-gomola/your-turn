"""Global handoff install and uninstall, run against app folders under tmp_path (never the real home)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yourturn.cli import main
from yourturn.install import CLAUDE_BLOCK, END, START, check, install, rule_text, skill_text, uninstall

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
    plugin = homes["cursor"] / "plugins" / "local" / "your-turn"
    assert json.loads((plugin / ".cursor-plugin" / "plugin.json").read_text())["name"] == "your-turn"
    assert (plugin / "rules" / "your-turn.mdc").read_text() == (
        "---\ndescription: Your Turn handoff at the end of every response\nalwaysApply: true\n---\n\n" + rule_text("cursor"))
    # Nothing lands in the project, and Codex (not selected) is untouched.
    assert list(no_clis.iterdir()) == [] and list(homes["codex"].iterdir()) == []

    install(["claude", "cursor"], homes)
    assert _tree(tmp_path) == first

    uninstall(["claude", "cursor"], homes)
    assert (homes["claude"] / "CLAUDE.md").read_text() == MINE
    assert json.loads((homes["cursor"] / "mcp.json").read_text()) == OTHER
    assert not (homes["claude"] / "skills" / "your-turn").exists() and not (homes["cursor"] / "skills" / "your-turn").exists()
    assert not plugin.exists()
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
    assert not memory.exists() and sorted(path.name for path in homes["cursor"].iterdir()) == ["plugins", "skills"]
    assert list((homes["cursor"] / "plugins" / "local").iterdir()) == []


def _stale(text: str) -> str:
    """An older copy: same version line, different wording."""
    return text.replace("End every response", "Finish each reply", 1)


def test_install_rewrites_owned_text_that_differs_under_the_same_version(tmp_path: Path, no_clis: Path) -> None:
    homes = _homes(tmp_path)
    claude_skill, cursor_skill = (homes[app] / "skills" / "your-turn" / "SKILL.md" for app in ("claude", "cursor"))
    memory = homes["claude"] / "CLAUDE.md"
    for path, app in ((claude_skill, "claude"), (cursor_skill, "cursor")):
        path.parent.mkdir(parents=True)
        path.write_text(_stale(skill_text(app)))
    memory.write_text(f"{MINE}\n{_stale(CLAUDE_BLOCK)}\nAfter.\n")
    assert _stale(skill_text("claude")) != skill_text("claude") and 'version: "' in _stale(skill_text("claude"))
    assert {state for _, artifact, state, _ in check(["claude", "cursor"], homes)
            if artifact in ("skill", "CLAUDE.md block")} == {"content mismatch"}

    install(["claude", "cursor"], homes)
    assert claude_skill.read_text() == skill_text("claude") and cursor_skill.read_text() == skill_text("cursor")
    assert memory.read_text() == f"{MINE}\n{CLAUDE_BLOCK}\nAfter.\n"
    first = _tree(tmp_path)
    install(["claude", "cursor"], homes)
    assert _tree(tmp_path) == first


@pytest.mark.parametrize("app", ["claude", "cursor"])
@pytest.mark.parametrize("linked", ["folder", "file"])
@pytest.mark.parametrize("action", [install, uninstall])
def test_linked_skill_and_its_target_are_left_untouched(tmp_path: Path, no_clis: Path, capsys: pytest.CaptureFixture[str],
                                                        app: str, linked: str, action: Any) -> None:
    homes = _homes(tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "SKILL.md").write_text(_stale(skill_text(app)))  # Ours, so only the link stops a rewrite or removal.
    folder = homes[app] / "skills" / "your-turn"
    folder.parent.mkdir()
    if linked == "folder":
        folder.symlink_to(shared, target_is_directory=True)
        link = folder
    else:
        folder.mkdir()
        link = folder / "SKILL.md"
        link.symlink_to(shared / "SKILL.md")
    capsys.readouterr()

    action([app], homes)
    assert (shared / "SKILL.md").read_text() == _stale(skill_text(app)) and link.is_symlink()
    assert sorted(path.name for path in shared.iterdir()) == ["SKILL.md"]
    out = capsys.readouterr().out
    assert f"kept (symlink, left untouched: {link})" in out
    assert "Skill saved" not in out and "removed" not in out.split("skill", 1)[-1].split(",", 1)[0]


def test_uninstall_and_install_leave_what_your_turn_did_not_write(tmp_path: Path, no_clis: Path) -> None:
    homes = _homes(tmp_path)
    install(["claude", "cursor"], homes)
    notes = homes["claude"] / "skills" / "your-turn" / "notes.md"
    notes.write_text("my notes\n")
    uninstall(["claude", "cursor"], homes)
    # Only our SKILL.md goes; the folder stays for the user's own file.
    assert _tree(homes["claude"]) == {"skills/your-turn/notes.md": "my notes\n"}
    assert not (homes["cursor"] / "skills" / "your-turn").exists()

    # A user's own skill that happens to use the name is neither overwritten nor removed.
    own = homes["cursor"] / "skills" / "your-turn" / "SKILL.md"
    own.parent.mkdir(parents=True)
    own.write_text("---\nname: your-turn\ndescription: my own turn-taking notes\n---\n\nMine.\n")
    install(["cursor"], homes)
    uninstall(["cursor"], homes)
    assert own.read_text().endswith("Mine.\n")
    assert [(app, artifact, state) for app, artifact, state, _ in check(["cursor"], homes)][0] == ("cursor", "skill", "content mismatch")


def test_doctor_reports_each_artifact_without_writing_or_running_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    homes = _homes(tmp_path)
    install_log = _fake(tmp_path, "codex", monkeypatch)
    claude_log = _fake(tmp_path, "claude", monkeypatch)

    def states() -> dict[tuple[str, str], str]:
        return {(app, artifact): state for app, artifact, state, _ in check(["codex", "claude", "cursor"], homes)}

    assert states() == {("codex", "plugin"): "unverified", ("claude", "skill"): "missing", ("claude", "CLAUDE.md block"): "missing",
                        ("cursor", "skill"): "missing", ("cursor", "rule plugin"): "missing", ("cursor", "rule loaded"): "unverified"}
    install(["claude", "cursor"], homes)
    install_log.unlink(missing_ok=True)
    claude_log.unlink()
    secret = "zebra-ledger-42 instructions\n"
    (homes["claude"] / "CLAUDE.md").write_text(secret + (homes["claude"] / "CLAUDE.md").read_text())
    # A saved plugin is current text, never proof that Cursor loaded it.
    assert states() == {("codex", "plugin"): "unverified", ("claude", "skill"): "current", ("claude", "CLAUDE.md block"): "current",
                        ("cursor", "skill"): "current", ("cursor", "rule plugin"): "current", ("cursor", "rule loaded"): "unverified"}

    (homes["cursor"] / "skills" / "your-turn" / "SKILL.md").write_bytes(b"\xff\xfe not text")
    (homes["claude"] / "CLAUDE.md").write_text(secret + f"{START}\nedited by hand\n{END}\n")
    before = _tree(homes["claude"])
    capsys.readouterr()
    assert main(["doctor", "--codex-home", str(homes["codex"]), "--claude-home", str(homes["claude"]),
                 "--cursor-home", str(homes["cursor"])]) == 1
    out = capsys.readouterr().out
    assert "content mismatch" in out and "unreadable" in out and "rule loaded: unverified" in out
    assert "docs/configuration.md#cursor-user-rule" in out
    assert "`uvx --from git+https://github.com/martin-gomola/your-turn your-turn cursor-rule` prints." in out
    assert "make cursor-rule" not in out
    # Only our block is compared, and nothing of the user's CLAUDE.md is shown.
    assert "zebra-ledger" not in out and "edited by hand" not in out
    assert _tree(homes["claude"]) == before and not install_log.exists() and not claude_log.exists()


def test_cursor_rule_carries_the_contract_itself_and_the_docs_match_it() -> None:
    rule = rule_text("cursor")
    for part in ("**Outcome:**", "**Next step:**", "**Recap:**", "**Decision:**", "`none`", "answer: …", "decide: …", "review: …",
                 "approve: …", "run: …", "`**Next step:** none`", "in English", "`AskQuestion`", "`StrReplace`", "&&"):
        assert part in rule, part
    assert "AskUserQuestion" not in rule and "`Edit`" not in rule and START not in rule
    assert CLAUDE_BLOCK == f"{START}\n{rule_text('claude')}{END}\n"
    docs = (Path(__file__).resolve().parents[1] / "docs" / "configuration.md").read_text(encoding="utf-8")
    # Four backticks, because the rule holds a fenced example of its own.
    assert f"\n````markdown\n{rule}````\n" in docs


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
    assert capsys.readouterr().out.endswith("\n→ Restart Claude Code to load the handoff, then start the inbox with: "
                                            "uvx --from git+https://github.com/martin-gomola/your-turn your-turn serve "
                                            "(or `make up` in a clone)\n")


@pytest.mark.parametrize("running", [False, True])
def test_cli_install_in_a_terminal_starts_the_inbox_unless_it_runs(tmp_path: Path, no_clis: Path, monkeypatch: pytest.MonkeyPatch,
                                                                    capsys: pytest.CaptureFixture[str], running: bool) -> None:
    import uvicorn

    from yourturn import cli

    served: list[int] = []
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_inbox_running", lambda port: running)
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: served.append(port))
    claude = tmp_path / "claude"
    main(["install", "--harness", "claude", "--claude-home", str(claude), "--codex-home", str(tmp_path / "codex"),
          "--cursor-home", str(tmp_path / "cursor")])
    out = capsys.readouterr().out
    assert "\n→ Restart Claude Code to load the handoff.\n" in out and (claude / "skills" / "your-turn" / "SKILL.md").is_file()
    if running:
        assert served == [] and out.endswith("→ Your Turn is already running at http://localhost:8787\n")
    else:
        assert served == [8787]
        assert "→ Next time, start the inbox with: uvx --from git+https://github.com/martin-gomola/your-turn your-turn serve\n" in out
        assert out.endswith("Starting Your Turn at http://localhost:8787. Press Ctrl+C to stop it.\n")


def test_cli_install_names_only_the_apps_it_set_up(tmp_path: Path, no_clis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    homes = _homes(tmp_path)
    main(["install", "--codex-home", str(homes["codex"]), "--claude-home", str(homes["claude"]),
          "--cursor-home", str(homes["cursor"])])
    # Codex has no CLI here, so it gets the shared skill instead of the plugin, and still needs a restart.
    assert "\n→ Restart Codex, Claude Code and Cursor to load the handoff, then start the inbox with: " in capsys.readouterr().out
    main(["install", "--codex-home", str(tmp_path / "none"), "--claude-home", str(tmp_path / "none"),
          "--cursor-home", str(tmp_path / "none")])
    assert capsys.readouterr().out.endswith("\n→ Start the inbox with: uvx --from git+https://github.com/martin-gomola/your-turn your-turn serve "
                                            "(or `make up` in a clone)\n")


def test_install_saves_the_cursor_rule_plugin_without_printing_the_rule(tmp_path: Path, no_clis: Path,
                                                                        capsys: pytest.CaptureFixture[str]) -> None:
    homes = _homes(tmp_path)
    install(["cursor"], homes)
    out = capsys.readouterr().out
    assert "Skill written · rule plugin written" in out
    # The happy path asks for nothing: no check to run, no link to follow, no rule body.
    assert "Customize" not in out and "http" not in out
    assert not any(line.strip() and line.strip() in out for line in rule_text("cursor").splitlines())
    assert "loaded" not in out and "missing" not in out


def test_codex_without_cli_gets_one_shared_skill_until_the_plugin_replaces_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    homes = _homes(tmp_path)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    shared = tmp_path / "home" / ".agents" / "skills" / "your-turn" / "SKILL.md"
    own = homes["cursor"] / "skills" / "your-turn" / "SKILL.md"
    install(["cursor"], homes)
    assert own.is_file()

    install(["codex", "claude", "cursor"], homes)
    out = capsys.readouterr().out
    assert "Skill written (Codex CLI not found, so no plugin)" in out and "Skill shared from ~/.agents/skills" in out
    # Worded for every app that reads the folder, and Cursor keeps no second copy beside it.
    text = shared.read_text()
    for part in ("name: your-turn\n", "`apply_patch` in Codex", "`StrReplace`, `Write` or `ApplyPatch` in Cursor",
                 "`AskQuestion` in Cursor", "`AskUserQuestion` in Claude Code"):
        assert part in text, part
    assert "{tool}" not in text and not own.exists()
    states = {(app, artifact): state for app, artifact, state, _ in check(["codex", "cursor"], homes)}
    assert states[("codex", "shared skill")] == "current" and states[("cursor", "skill")] == "current"

    # Once the CLI is there, the plugin holds the skill, so the shared copy goes and Cursor writes its own again.
    log = _fake(tmp_path, "codex", monkeypatch)
    install(["codex", "cursor"], homes)
    assert "Plugin your-turn@your-turn installed, shared skill removed" in capsys.readouterr().out
    assert not shared.exists() and own.read_text() == skill_text("cursor") and log.exists()


@pytest.mark.parametrize("kind", ["own", "symlink"])
def test_cursor_plugin_the_user_owns_is_left_untouched(tmp_path: Path, no_clis: Path, capsys: pytest.CaptureFixture[str],
                                                       kind: str) -> None:
    homes = _homes(tmp_path)
    folder = homes["cursor"] / "plugins" / "local" / "your-turn"
    target = tmp_path / "elsewhere" if kind == "symlink" else folder
    (target / ".cursor-plugin").mkdir(parents=True)
    (target / ".cursor-plugin" / "plugin.json").write_text('{"name": "your-turn", "description": "mine"}\n')
    if kind == "symlink":
        folder.parent.mkdir(parents=True)
        folder.symlink_to(target, target_is_directory=True)
    before = _tree(tmp_path / "elsewhere" if kind == "symlink" else folder)
    install(["cursor"], homes)
    uninstall(["cursor"], homes)
    out = capsys.readouterr().out
    assert _tree(tmp_path / "elsewhere" if kind == "symlink" else folder) == before
    assert "rule plugin kept (" in out and "Rule plugin not saved." in out


def test_cli_install_failure_stays_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    homes = _homes(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "codex").write_text("#!/bin/sh\nexit 7\n")
    (bin_dir / "codex").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    with pytest.raises(SystemExit) as exited:
        main(["install", "--harness", "codex", "--codex-home", str(homes["codex"])])
    assert exited.value.code == 1
    assert "Plugin install failed: codex plugin marketplace add" in capsys.readouterr().err


def test_cursor_rule_prints_only_the_rule_and_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                              capsys: pytest.CaptureFixture[str]) -> None:
    homes = _homes(tmp_path)
    codex_log, claude_log = _fake(tmp_path, "codex", monkeypatch), _fake(tmp_path, "claude", monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path / "cursor")
    before = _tree(tmp_path)
    assert main(["cursor-rule"]) == 0
    captured = capsys.readouterr()
    assert captured.out == rule_text("cursor") and captured.err == ""
    assert _tree(tmp_path) == before and not (tmp_path / "home").exists()
    assert not codex_log.exists() and not claude_log.exists()
