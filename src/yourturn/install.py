"""Install the handoff for each agent app, globally: only under the user's own app folders
(`~/.codex`, `~/.claude`, `~/.cursor`), never in a project, so no repository needs a .gitignore entry.

Codex gets the plugin, which holds the skill; without the Codex CLI, it gets the skill in the shared
`~/.agents/skills` folder instead, worded for any app, which Cursor then uses too. Claude Code and Cursor get the same skill in their global
skills folder; Claude Code also gets a short block in its global CLAUDE.md so every chat follows the
handoff, not only those where the skill is picked. Cursor gets the same always-on rule as a local plugin
in `~/.cursor/plugins/local`, which it loads after a reload unless an admin turned local plugins off;
the `cursor-rule` command prints the rule to add by hand instead. The handoff is plain text, so no process
runs and no app asks for a permission. Every step is idempotent, and `uninstall` removes only what `install` added.
`doctor` compares the installed text with the current one without writing or running anything.

Earlier versions also registered a `your-turn` MCP server; both commands remove it where it is left over.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

MARKETPLACE_SOURCE = "martin-gomola/your-turn"
MARKETPLACE = "your-turn"
PLUGIN = f"your-turn@{MARKETPLACE}"
# The Quickstart's form: run through uvx, `your-turn` is not on PATH.
CURSOR_RULE = "uvx --from git+https://github.com/martin-gomola/your-turn your-turn cursor-rule"
# The same text in a Markdown block, which GitHub gives a copy button.
CURSOR_RULE_DOCS = "https://github.com/martin-gomola/your-turn/blob/main/docs/configuration.md#cursor-user-rule"
NAME = "your-turn"  # Skill folder in Claude Code and Cursor, and the name of the legacy MCP server.
APPS = {"codex": "Codex", "claude": "Claude Code", "cursor": "Cursor"}
ASK_TOOLS = {"claude": "AskUserQuestion", "cursor": "AskQuestion"}
# Each app's own edit tools, named in place of Codex's `apply_patch`.
EDIT_TOOLS = {"claude": "`Edit` or `Write`", "cursor": "`StrReplace`, `Write` or `ApplyPatch`"}
START, END = "<!-- your-turn:start -->", "<!-- your-turn:end -->"
# The block with the blank lines around it, so removing or replacing it leaves one blank line between neighbours.
BLOCK = re.compile(rf"\n*{re.escape(START)}.*?{re.escape(END)}\n*", re.DOTALL)
# The skill's rules that must be in every chat's context, not only when the agent picks the skill:
# Claude Code's CLAUDE.md block and the Cursor User Rule.
RULE = """## Your Turn handoff

End every response to the user, on every turn, with this block at the very top or the very bottom: one
group of lines with no prose between them, each on one line, as plain Markdown outside code blocks.

- `**Outcome:**` one sentence: what is now true.
- `**Next step:**` `none`, `answer: …`, `decide: …`, `review: …`, `approve: …` or `run: …`. When the task
  is done, write exactly `**Next step:** none` and stop. A question the user must react to goes here.
- `**Recap:**` from the second turn on: 1-2 sentences under 400 characters (goal, what is settled, what
  is open).
- `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` only for a non-trivial trade-off
  (architecture, edge-case behavior, library or approach), one line each.

Keep the labels and prefixes in English, even when you reply in another language, and start no other
line with them. An optional suggestion goes in the body; never close with a polite offer such as
"Let me know if…" or "Should I also…?".

Example:

```markdown
**Outcome:** The login redirect bug is fixed and covered by a test.
**Next step:** none
**Recap:** Fixing login redirects; the fix and its test are in, nothing is open.
```

While working:

- Edit files with {edit}, not from the shell, so Your Turn sees them.
- After your last code edit, run the check that covers it, alone or last in a chain joined with `&&`;
  if you cannot, make the next step `run: <command>`.
- Ask the user to choose with `{ask}`. The `your-turn` skill has the details.
"""
QUESTIONS = """
## Questions

When you need the user to choose, ask with the `{tool}` tool and list the options. Your Turn shows
the question and its options under Needs you until it is answered.
"""


def _paint(text: str, code: str) -> str:
    """Add terminal color without leaking ANSI escapes into redirected output."""
    if not sys.stdout.isatty() or os.getenv("NO_COLOR") or os.getenv("TERM") == "dumb":
        return text
    return f"\033[{code}m{text}\033[0m"


def _install_result(harness: str, detail: str, home: Path | None = None) -> None:
    print(f"{_paint('✓', '32')} {_paint(APPS[harness], '1;36')}", flush=True)
    print(f"  {detail}", flush=True)
    if home is not None:
        print(f"  {_paint(str(home), '2')}", flush=True)


def plugin_text(name: str) -> str:
    """A file of the Codex plugin: packaged into the wheel, or read from a source checkout."""
    packaged = files("yourturn").joinpath("plugin", name)
    path = packaged if packaged.is_file() else Path(__file__).resolve().parents[2] / "plugin" / name
    return path.read_text(encoding="utf-8")


def skill_text(harness: str) -> str:
    """The Codex handoff skill, renamed and worded for another app, plus how it asks questions."""
    text = plugin_text("skills/your-turn-handoff/SKILL.md")
    text = text.replace("name: your-turn-handoff", f"name: {NAME}").replace("Codex", APPS[harness])
    text = text.replace("`apply_patch`", EDIT_TOOLS[harness])
    return text.rstrip("\n") + "\n" + QUESTIONS.format(tool=ASK_TOOLS[harness])


def shared_skill_text() -> str:
    """The skill for `~/.agents/skills`, which more than one app reads, worded for any of them."""
    text = plugin_text("skills/your-turn-handoff/SKILL.md").replace("name: your-turn-handoff", f"name: {NAME}")
    text = text.replace("every turn in Codex", "every turn in any app")
    edit = ", ".join(f"{EDIT_TOOLS[app]} in {APPS[app]}" for app in EDIT_TOOLS)
    text = text.replace("Codex's native edit tool (`apply_patch`)", f"your app's native edit tool (`apply_patch` in Codex, {edit})")
    ask = ", ".join(f"`{ASK_TOOLS[app]}` in {APPS[app]}" for app in ASK_TOOLS)
    return text.rstrip("\n") + "\n" + QUESTIONS.replace("the `{tool}` tool", f"your app's question tool ({ask})")


def rule_text(harness: str) -> str:
    """The always-on part of the skill, worded for Claude Code or Cursor."""
    return RULE.format(edit=EDIT_TOOLS[harness], ask=ASK_TOOLS[harness])


CLAUDE_BLOCK = f"{START}\n{rule_text('claude')}{END}\n"


def cursor_plugin_files() -> dict[str, str]:
    """The local Cursor plugin that carries the rule into every Agent chat, by path within its folder."""
    manifest = {"name": NAME, "description": "Your Turn handoff: the always-on rule for every Agent chat",
                "author": {"name": "Martin Gomola"}}
    rule = ("---\ndescription: Your Turn handoff at the end of every response\nalwaysApply: true\n---\n\n"
            f"{rule_text('cursor')}")
    return {".cursor-plugin/plugin.json": json.dumps(manifest, indent=2) + "\n", f"rules/{NAME}.mdc": rule}


def detect(homes: dict[str, Path]) -> list[str]:
    """Apps whose home folder exists on this machine."""
    return [harness for harness, home in homes.items() if home.is_dir()]


def _write(path: Path, text: str) -> str:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "written"


def _ours(path: Path) -> bool:
    """A skill file Your Turn wrote, in any version: its name and heading, whatever the wording."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return text.startswith(f"---\nname: {NAME}\n") and "\n# Your Turn handoff\n" in text


def _linked(folder: Path) -> str:
    """A linked skill folder or SKILL.md: its target may be shared, so it is never written or removed."""
    link = next((path for path in (folder, folder / "SKILL.md") if path.is_symlink()), None)
    return f"kept (symlink, left untouched: {link})" if link else ""


def _write_skill(home: Path, text: str) -> str:
    folder = home / "skills" / NAME
    path = folder / "SKILL.md"
    if linked := _linked(folder):
        return linked
    if path.exists() and not _ours(path):
        return "kept (not written by Your Turn)"
    return _write(path, text)


def agents_home() -> Path:
    """The shared skills home that Codex reads without its CLI, and that Cursor reads too."""
    return Path.home() / ".agents"


def _shared_skill() -> Path | None:
    """Our skill in the shared folder, when Your Turn wrote it there."""
    path = agents_home() / "skills" / NAME / "SKILL.md"
    return path if not _linked(path.parent) and _ours(path) else None


def _remove_skill(home: Path) -> str:
    """Remove our SKILL.md, and its folder only when nothing else is left in it."""
    folder = home / "skills" / NAME
    path = folder / "SKILL.md"
    if linked := _linked(folder):
        return linked
    if not path.exists():
        return "not present"
    if not _ours(path):
        return "kept (not written by Your Turn)"
    path.unlink()
    if not any(folder.iterdir()):
        folder.rmdir()
    return "removed"


# --- Codex ---------------------------------------------------------------------------------------


def _codex(args: list[str], home: Path | None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CODEX_HOME": str(home)} if home is not None else None
    return subprocess.run(["codex", *args], capture_output=not check, text=True, check=check, env=env)


def install_plugin(home: Path | None = None) -> bool:
    """Install the handoff skill into Codex: the plugin through its CLI, else the skill in the shared folder.
    Returns False when neither could be saved."""
    if not shutil.which("codex"):
        skill = _write_skill(agents_home(), shared_skill_text())
        _install_result("codex", f"Skill {skill} (Codex CLI not found, so no plugin)", agents_home() / "skills")
        return skill in ("written", "unchanged")
    env = {**os.environ, "CODEX_HOME": str(home)} if home is not None else None
    listed = subprocess.run(["codex", "plugin", "marketplace", "list"], capture_output=True, text=True, env=env)
    if not any(line.split()[:1] == [MARKETPLACE] for line in listed.stdout.splitlines()):
        _codex(["plugin", "marketplace", "add", MARKETPLACE_SOURCE], home)
    else:
        # Refresh a Git marketplace so an installed plugin picks up the current skill (a local one has nothing to refresh).
        _codex(["plugin", "marketplace", "upgrade", MARKETPLACE], home, check=False)
    _codex(["plugin", "add", PLUGIN], home)
    # The plugin holds the skill, so a copy left from a run without the CLI would load twice.
    shared = ", shared skill removed" if _shared_skill() and _remove_skill(agents_home()) == "removed" else ""
    _install_result("codex", f"Plugin {PLUGIN} installed{shared}")
    return True


def uninstall_plugin(home: Path | None = None) -> None:
    shared = _remove_skill(agents_home()) if _shared_skill() else "not present"
    if not shutil.which("codex"):
        print(f"Codex: shared skill {shared}; CLI not found, so no plugin to remove.", flush=True)
        return
    # Either may already be gone; that is the state uninstall wants.
    _codex(["plugin", "remove", PLUGIN], home, check=False)
    _codex(["plugin", "marketplace", "remove", MARKETPLACE], home, check=False)
    print(f"Codex: removed {PLUGIN} and its marketplace; shared skill {shared}.", flush=True)


# --- Claude Code ---------------------------------------------------------------------------------


def _claude_env(home: Path) -> dict[str, str]:
    # Only for a non-default home: with CLAUDE_CONFIG_DIR set, Claude Code keeps its user config in
    # $CLAUDE_CONFIG_DIR/.claude.json instead of ~/.claude.json.
    if home.expanduser().resolve() == (Path.home() / ".claude").resolve():
        return dict(os.environ)
    return {**os.environ, "CLAUDE_CONFIG_DIR": str(home)}


def _legacy_claude_mcp(home: Path) -> str:
    """Remove the `your-turn` MCP server an earlier version registered at user scope."""
    if not shutil.which("claude"):
        return ""
    removed = subprocess.run(["claude", "mcp", "remove", "--scope", "user", NAME], capture_output=True, text=True, env=_claude_env(home))
    return ", old MCP server removed" if removed.returncode == 0 else ""


def install_claude(home: Path) -> None:
    skill = _write_skill(home, skill_text("claude"))
    memory = home / "CLAUDE.md"
    current = memory.read_text(encoding="utf-8") if memory.is_file() else ""
    if BLOCK.search(current):
        updated = BLOCK.sub(lambda _: f"\n\n{CLAUDE_BLOCK}\n", current, count=1).strip("\n") + "\n"
    else:
        updated = f"{current.rstrip()}\n\n{CLAUDE_BLOCK}" if current.strip() else CLAUDE_BLOCK
    block = _write(memory, updated)
    _install_result("claude", f"Skill {skill} · CLAUDE.md block {block}{_legacy_claude_mcp(home)}", home)


def uninstall_claude(home: Path) -> None:
    skill = _remove_skill(home)
    memory, block = home / "CLAUDE.md", "not present"
    if memory.is_file():
        current = memory.read_text(encoding="utf-8")
        if BLOCK.search(current):
            rest = BLOCK.sub("\n\n", current, count=1).strip("\n")
            if rest:
                memory.write_text(rest + "\n", encoding="utf-8")
            else:
                memory.unlink()  # The file held only our block.
            block = "removed"
    print(f"Claude Code: skill {skill}, CLAUDE.md block {block}{_legacy_claude_mcp(home)} ({home}).", flush=True)


# --- Cursor --------------------------------------------------------------------------------------


def _legacy_cursor_mcp(home: Path) -> str:
    """Remove the `your-turn` server an earlier version added to `mcp.json`, leaving the rest as it was."""
    path = home / "mcp.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        return ""
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    if not isinstance(servers, dict) or servers.pop(NAME, None) is None:
        return ""
    if not servers and set(config) == {"mcpServers"}:
        path.unlink()  # The file held only our server.
    else:
        _write(path, json.dumps(config, indent=2) + "\n")
    return ", old MCP server removed"


def _cursor_plugin(home: Path) -> Path:
    return home / "plugins" / "local" / NAME


def _plugin_kept(folder: Path) -> str:
    """Why a plugin folder is left alone: Cursor skips symlinks there, and a same-named plugin may be the user's."""
    if folder.is_symlink():
        return f"kept (symlink, left untouched: {folder})"
    manifest = folder / ".cursor-plugin" / "plugin.json"
    if not folder.exists():
        return ""
    try:
        ours = json.loads(manifest.read_text(encoding="utf-8")) == json.loads(cursor_plugin_files()[".cursor-plugin/plugin.json"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        ours = False
    return "" if ours else "kept (not written by Your Turn)"


def _write_cursor_plugin(home: Path) -> str:
    folder = _cursor_plugin(home)
    if kept := _plugin_kept(folder):
        return kept
    results = [_write(folder / name, text) for name, text in cursor_plugin_files().items()]
    return "written" if "written" in results else "unchanged"


def _remove_cursor_plugin(home: Path) -> str:
    """Remove our plugin files, and each folder only when nothing else is left in it."""
    folder = _cursor_plugin(home)
    if not folder.exists() and not folder.is_symlink():
        return "not present"
    if kept := _plugin_kept(folder):
        return kept
    for name in cursor_plugin_files():
        (folder / name).unlink(missing_ok=True)
    for path in (folder / ".cursor-plugin", folder / "rules", folder):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return "removed"


def install_cursor(home: Path) -> None:
    # Cursor also reads the shared skills folder, so with our skill there its own copy would be a second one.
    if _shared_skill():
        _remove_skill(home)
        skill = "shared from ~/.agents/skills"
    else:
        skill = _write_skill(home, skill_text("cursor"))
    rule = _write_cursor_plugin(home)
    _install_result("cursor", f"Skill {skill} · rule plugin {rule}{_legacy_cursor_mcp(home)}", home)
    if rule not in ("written", "unchanged"):
        print(f"  Rule plugin not saved. Add the rule as a User Rule from: {CURSOR_RULE_DOCS}", flush=True)


def uninstall_cursor(home: Path) -> None:
    skill, rule = _remove_skill(home), _remove_cursor_plugin(home)
    print(f"Cursor: skill {skill}, rule plugin {rule}{_legacy_cursor_mcp(home)} ({home}). Remove the Your Turn User Rule"
          " in Customize → Rules if you added one by hand.", flush=True)


# --- doctor --------------------------------------------------------------------------------------


def _state(path: Path, expected: str) -> str:
    try:
        return "current" if path.read_text(encoding="utf-8") == expected else "content mismatch"
    except FileNotFoundError:
        return "missing"
    except (OSError, UnicodeDecodeError):
        return "unreadable"


def _block_state(memory: Path) -> str:
    """Our CLAUDE.md block against the current one; the rest of the file is never compared or shown."""
    try:
        text = memory.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing"
    except (OSError, UnicodeDecodeError):
        return "unreadable"
    found = re.search(rf"{re.escape(START)}.*?{re.escape(END)}\n?", text, re.DOTALL)
    if found is None:
        return "content mismatch" if START in text else "missing"
    return "current" if found.group(0).rstrip("\n") == CLAUDE_BLOCK.rstrip("\n") else "content mismatch"


def check(harnesses: list[str], homes: dict[str, Path]) -> list[tuple[str, str, str, str]]:
    """(app, artifact, state, note) for each handoff artifact, read-only and without running any app CLI."""
    results: list[tuple[str, str, str, str]] = []
    for harness in harnesses:
        home = homes[harness]
        shared = agents_home() / "skills" / NAME / "SKILL.md"
        if harness == "codex":
            if shutil.which("codex"):
                results.append(("codex", "plugin", "unverified", "Codex keeps the plugin from its marketplace in its own cache, "
                                "which Your Turn does not read; `install` refreshes it."))
            else:
                results.append(("codex", "shared skill", _state(shared, shared_skill_text()), str(shared)))
            continue
        if harness == "cursor" and _shared_skill():
            results.append(("cursor", "skill", _state(shared, shared_skill_text()), f"{shared} (shared)"))
        else:
            results.append((harness, "skill", _state(home / "skills" / NAME / "SKILL.md", skill_text(harness)),
                            str(home / "skills" / NAME / "SKILL.md")))
        if harness == "claude":
            results.append(("claude", "CLAUDE.md block", _block_state(home / "CLAUDE.md"), str(home / "CLAUDE.md")))
        else:
            folder = _cursor_plugin(home)
            states = [_state(folder / name, text) for name, text in cursor_plugin_files().items()]
            results.append(("cursor", "rule plugin", next((state for state in states if state != "current"), "current"),
                            str(folder)))
            results.append(("cursor", "rule loaded", "unverified",
                            "Cursor loads the local plugin after a reload unless an admin turned local plugins off, and "
                            "Your Turn cannot see whether it did; Customize → Rules shows it. Without it, add a User Rule "
                            f"with the text from {CURSOR_RULE_DOCS}, or the text that `{CURSOR_RULE}` prints "
                            "(in a clone: `make cursor-rule`)."))
    return results


def doctor(harnesses: list[str], homes: dict[str, Path]) -> int:
    """Print each artifact's state; 1 when one is missing, differs from the current text, or cannot be read."""
    print(_paint("Your Turn doctor (read-only)", "1;36"), flush=True)
    results = check(harnesses, homes)
    for app in dict.fromkeys(app for app, *_ in results):
        print(_paint(APPS[app], "1;36"), flush=True)
        for _, artifact, state, note in (result for result in results if result[0] == app):
            color = "32" if state == "current" else "33" if "unverified" in state else "31"
            print(f"  {artifact}: {_paint(state, color)}", flush=True)
            print(f"    {_paint(note, '2')}", flush=True)
    if not results:
        print("No Codex, Claude Code or Cursor folder found, so there is nothing to check.", flush=True)
    return 1 if any(state in ("missing", "content mismatch", "unreadable") for _, _, state, _ in results) else 0


def install(harnesses: list[str], homes: dict[str, Path]) -> list[str]:
    """Set up each app and return the ones that got the handoff, which need a restart to load it."""
    print(_paint("Your Turn setup", "1;36"), flush=True)
    print(_paint("───────────────", "2"), flush=True)
    if not harnesses:
        print("No Codex, Claude Code or Cursor folder found, so nothing was installed.", flush=True)
    done = []
    for harness in harnesses:
        if harness == "codex":
            if install_plugin(homes[harness]):
                done.append(harness)
            continue
        {"claude": install_claude, "cursor": install_cursor}[harness](homes[harness])
        done.append(harness)
    return done


def uninstall(harnesses: list[str], homes: dict[str, Path]) -> None:
    for harness in harnesses:
        {"codex": uninstall_plugin, "claude": uninstall_claude, "cursor": uninstall_cursor}[harness](homes[harness])
