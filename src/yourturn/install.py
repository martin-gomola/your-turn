"""Install the handoff for each agent app, globally: only under the user's own app folders
(`~/.codex`, `~/.claude`, `~/.cursor`), never in a project, so no repository needs a .gitignore entry.

Codex gets the plugin, which holds the skill; without the Codex CLI, it gets the skill in the shared
`~/.agents/skills` folder instead, worded for any app, which Cursor then uses too. Claude Code and Cursor get the same skill in their global
skills folder; Claude Code also gets a short block in its global CLAUDE.md so every chat follows the
handoff, not only those where the skill is picked. Cursor gets the same always-on rule as a global rule file,
`~/.cursor/rules/your-turn.mdc`, which Customize → Rules lists by name under User; the `cursor-rule`
command prints the rule to add by hand instead. The handoff is plain text, so no process runs and no app
asks for a permission. Every step is idempotent, and `uninstall` removes only what `install` added.
`doctor` compares the installed text with the current one without writing or running anything.

Earlier versions also registered a `your-turn` MCP server, and later ones saved the Cursor rule as a local
plugin in `~/.cursor/plugins/local`; both commands remove either where it is left over.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

from yourturn import __version__, usage

MARKETPLACE_SOURCE = "martin-gomola/your-turn"
MARKETPLACE = "your-turn"
PLUGIN = f"your-turn@{MARKETPLACE}"
# `codex plugin list` can take minutes (2.5 measured), so install reads Codex's config instead; this bounds the fetch.
CODEX_TIMEOUT = 300
# The Quickstart's form: run through uvx, `your-turn` is not on PATH.
CURSOR_RULE = "uvx your-turn@latest cursor-rule"
# The same text in a Markdown block, which GitHub gives a copy button.
CURSOR_RULE_DOCS = "https://github.com/martin-gomola/your-turn/blob/main/docs/configuration.md#cursor-user-rule"
NAME = "your-turn"  # Skill folder in Claude Code and Cursor, and the name of the legacy MCP server.
STANDALONE_HANDOFF = "your-turn-handoff"  # Standalone skill name in your-turn-loop and Codex plugin.
APPS = {"codex": "Codex", "claude": "Claude Code", "cursor": "Cursor"}
SECTIONS = {**APPS, "loop": "Loop skills"}
ASK_TOOLS = {"claude": "AskUserQuestion", "cursor": "AskQuestion"}
# Each app's own edit tools, named in place of Codex's `apply_patch`.
EDIT_TOOLS = {"claude": "`Edit` or `Write`", "cursor": "`StrReplace`, `Write` or `ApplyPatch`"}
START, END = "<!-- your-turn:start -->", "<!-- your-turn:end -->"
# The block with the blank lines around it, so removing or replacing it leaves one blank line between neighbours.
BLOCK = re.compile(rf"\n*{re.escape(START)}.*?{re.escape(END)}\n*", re.DOTALL)
# The skill's rules that must be in every chat's context, not only when the agent picks the skill:
# Claude Code's CLAUDE.md block and the Cursor User Rule.
RULE = """## Your Turn handoff

End every final response to the user, including questions and review pauses, with this block at the very top or the very bottom: one
group of lines with no prose between them, each on one line with a blank line between them (chat apps
join adjacent lines into one paragraph), as plain Markdown outside code blocks. Progress updates need no block.

- `**Outcome:**` one sentence under 160 characters: the precise result, recommendation or explicit
  hypothesis, including any material limitation. Use a headline; put the essential reason and concise
  verification evidence in the body, referencing artifacts instead of raw logs or file inventories.
- `**Next step:**` `none`, `answer: …`, `decide: …`, `review: …`, `approve: …` or `run: …`, one action
  under 120 characters. Complete the authorized work you can perform before handing off. Write
  exactly `**Next step:** none` when no required human action remains; advice and disclosed
  uncertainty can also use `none`. Use `answer:` for necessary missing information; `decide:` names
  at least two options awaiting a choice; `review:` names a prepared artifact and the judgment
  actually needed; `approve:` requests genuinely pending permission, respecting prior authorization;
  `run:` names a necessary command only the user can run. Uncertainty alone does not require review.
- `**Recap:**` from the second turn on: 1-2 sentences under 400 characters covering the whole chat, not
  this turn: the goal, what is settled and why, and what is open. Keep relevant earlier choices and
  their reasons; make any superseding choice explicit.
- `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` records an actual consequential
  choice made this turn, one line each. A pending choice belongs in `Next step`, not a settled Decision.

Keep labels, prefixes, `->` and the literal `(over …)` syntax in English; write prose values in the
language of your reply and use these labels only in the block. Separate alternatives with commas
inside `(over …)`. An optional suggestion goes in the body with `**Next step:** none`. End the
response after a bottom block.

Example:

```markdown
**Outcome:** The login redirect bug is fixed and covered by a test.

**Next step:** none

**Recap:** Fixing login redirects; the fix and its test are in, nothing is open.
```

While working:

- Edit files with {edit}, not from the shell, so Your Turn sees them.
- After your last code edit, run the check that covers it, alone or last in a chain joined with `&&`;
  keep fixing failures when possible. State remaining failures or limits in Outcome; use `run:` only
  when necessary verification requires the user's environment.
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


def _install_result(harness: str, detail: str, home: Path | None = None, ok: bool = True) -> None:
    mark = _paint("✓", "32") if ok else _paint("!", "33")
    print(f"{mark} {_paint(APPS[harness], '1;36')}", flush=True)
    print(f"  {detail}", flush=True)
    if home is not None:
        print(f"  {_paint(str(home), '2')}", flush=True)


def plugin_text(name: str) -> str:
    """A file of the Codex plugin: packaged into the wheel, or read from a source checkout."""
    packaged = files("yourturn").joinpath("plugin", name)
    path = packaged if packaged.is_file() else Path(__file__).resolve().parents[2] / "plugin" / name
    return path.read_text(encoding="utf-8")


def _skill_version(text: str) -> str | None:
    """Read `metadata.version` from a skill's leading YAML frontmatter."""
    front = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not front:
        return None
    match = re.search(r'(?m)^\s*version:\s*["\']?([^"\'\n]+?)["\']?\s*$', front.group(1))
    return match.group(1).strip() if match else None


def _read_skill_version(path: Path) -> str | None:
    try:
        return _skill_version(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def handoff_version() -> str:
    return _skill_version(plugin_text(f"skills/{STANDALONE_HANDOFF}/SKILL.md")) or __version__


def _version_banner() -> str:
    handoff = handoff_version()
    return f"v{__version__}" if handoff == __version__ else f"v{__version__} (handoff v{handoff})"


def skill_text(harness: str) -> str:
    """The Codex handoff skill, renamed and worded for another app, plus how it asks questions."""
    text = plugin_text("skills/your-turn-handoff/SKILL.md")
    text = text.replace("name: your-turn-handoff", f"name: {NAME}").replace("Codex", APPS[harness])
    text = text.replace("`apply_patch`", EDIT_TOOLS[harness])
    text = re.sub(r"Edit files with your app's native edit tool[^\n]+", f"Edit files with {APPS[harness]}'s native edit tool ({EDIT_TOOLS[harness]}), not from the shell, so Your Turn observes the edit events.", text)
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


CURSOR_RULE_FRONT = "---\ndescription: Your Turn handoff at the end of every response\nalwaysApply: true\n---\n\n"


def cursor_rule_file() -> str:
    """The global Cursor rule file that carries the rule into every Agent chat."""
    return CURSOR_RULE_FRONT + rule_text("cursor")


# The local plugin an earlier version saved the rule in, by path within its folder.
LEGACY_PLUGIN_FILES = (".cursor-plugin/plugin.json", f"rules/{NAME}.mdc")
LEGACY_MANIFEST = {"name": NAME, "description": "Your Turn handoff: the always-on rule for every Agent chat",
                   "author": {"name": "Martin Gomola"}}


def detect(homes: dict[str, Path]) -> list[str]:
    """Apps whose home folder exists on this machine."""
    return [harness for harness, home in homes.items() if home.is_dir()]


def _write(path: Path, text: str) -> str:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "written"


def _ours(path: Path, name: str = NAME) -> bool:
    """A skill file Your Turn wrote, in any version: its name and heading, whatever the wording."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return text.startswith(f"---\nname: {name}\n") and "\n# Your Turn handoff\n" in text


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
    root = home if home is not None else Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    # Codex's own record of installed plugins; anything unreadable just means a full install, which is idempotent.
    try:
        config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    marketplaces = config.get("marketplaces") if isinstance(config.get("marketplaces"), dict) else {}

    def enabled(plugin: str) -> bool:
        return isinstance(plugins.get(plugin), dict) and plugins[plugin].get("enabled") is True

    # Marketplace name from before the repo became your-turn-loop and dropped its Codex plugin; only older installs carry it.
    standalone = "your-turn-handoff@my-agent-skills"
    if enabled(standalone):
        if PLUGIN in plugins:
            _codex(["plugin", "remove", PLUGIN], home, check=False)
        if _shared_skill():
            _remove_skill(agents_home())
        _install_result("codex", f"Using installed handoff {standalone}")
        return True
    marketplace = marketplaces.get(MARKETPLACE)
    # A Git marketplace ships the skill with the release, so the same version needs no refresh unless its text drifted.
    release = root / "plugins" / "cache" / MARKETPLACE / NAME / __version__
    cached_skill = release / "skills" / STANDALONE_HANDOFF / "SKILL.md"
    if (enabled(PLUGIN) and isinstance(marketplace, dict) and marketplace.get("source_type") == "git"
            and release.is_dir()
            and (not cached_skill.exists() or _state(cached_skill, plugin_text(f"skills/{STANDALONE_HANDOFF}/SKILL.md")) == "current")):
        shared = ", shared skill removed" if _shared_skill() and _remove_skill(agents_home()) == "removed" else ""
        _install_result("codex", f"Plugin {PLUGIN} {__version__} unchanged{shared}")
        return True
    if marketplace is None:
        _codex(["plugin", "marketplace", "add", MARKETPLACE_SOURCE], home)
    else:
        # Refresh a Git marketplace so an installed plugin picks up the current skill (a local one has nothing to refresh).
        try:
            subprocess.run(["codex", "plugin", "marketplace", "upgrade", MARKETPLACE], capture_output=True, text=True, env=env, timeout=CODEX_TIMEOUT)
        except subprocess.TimeoutExpired:
            pass
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
    env = _claude_env(home)
    config = Path(env["CLAUDE_CONFIG_DIR"]) / ".claude.json" if "CLAUDE_CONFIG_DIR" in env else Path.home() / ".claude.json"
    try:
        servers = json.loads(config.read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError, AttributeError):
        servers = None
    # Skips a slow CLI start when the config shows no server; anything unreadable is left to the CLI.
    if isinstance(servers, dict) and NAME not in servers:
        return ""
    removed = subprocess.run(["claude", "mcp", "remove", "--scope", "user", NAME], capture_output=True, text=True, env=env)
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


def _legacy_cursor_plugin(home: Path) -> str:
    """Remove the local plugin an earlier version saved the rule in, unless it is a symlink or the user's own."""
    folder = home / "plugins" / "local" / NAME
    if folder.is_symlink() or not folder.is_dir():
        return ""
    try:
        ours = json.loads((folder / LEGACY_PLUGIN_FILES[0]).read_text(encoding="utf-8")) == LEGACY_MANIFEST
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not ours:
        return ""
    for name in LEGACY_PLUGIN_FILES:
        (folder / name).unlink(missing_ok=True)
    for path in (folder / ".cursor-plugin", folder / "rules", folder):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return ", old rule plugin removed"


def _cursor_rule(home: Path) -> Path:
    return home / "rules" / f"{NAME}.mdc"


def _rule_kept(path: Path) -> str:
    """Why the rule file is left alone: a symlink's target may be shared, and a same-named rule may be the user's."""
    if path.is_symlink():
        return f"kept (symlink, left untouched: {path})"
    try:
        ours = not path.exists() or path.read_text(encoding="utf-8").startswith(CURSOR_RULE_FRONT + "## Your Turn handoff\n")
    except (OSError, UnicodeDecodeError):
        ours = False
    return "" if ours else "kept (not written by Your Turn)"


def install_cursor(home: Path) -> None:
    # Cursor also reads the shared skills folder, so with our skill there its own copy would be a second one.
    if _shared_skill():
        _remove_skill(home)
        skill = "shared from ~/.agents/skills"
    else:
        skill = _write_skill(home, skill_text("cursor"))
    path = _cursor_rule(home)
    rule = _rule_kept(path) or _write(path, cursor_rule_file())
    _install_result("cursor", f"Skill {skill} · rule {rule}{_legacy_cursor_plugin(home)}{_legacy_cursor_mcp(home)}", home)
    if rule not in ("written", "unchanged"):
        print(f"  Rule not saved. Add the rule as a User Rule from: {CURSOR_RULE_DOCS}", flush=True)


def uninstall_cursor(home: Path) -> None:
    path = _cursor_rule(home)
    rule = "not present" if not path.exists() and not path.is_symlink() else _rule_kept(path)
    if not rule:
        path.unlink()
        if not any(path.parent.iterdir()):
            path.parent.rmdir()
        rule = "removed"
    print(f"Cursor: skill {_remove_skill(home)}, rule {rule}{_legacy_cursor_plugin(home)}{_legacy_cursor_mcp(home)} ({home})."
          " Remove the Your Turn User Rule in Customize → Rules if you added one by hand.", flush=True)


# --- doctor --------------------------------------------------------------------------------------


def _state(path: Path, expected: str) -> str:
    try:
        return "current" if path.read_text(encoding="utf-8") == expected else "content mismatch"
    except FileNotFoundError:
        return "missing"
    except (OSError, UnicodeDecodeError):
        return "unreadable"


def _skill_note(path: Path, state: str, suffix: str = "") -> str:
    ver = handoff_version()
    if state == "current":
        return f"{path}{suffix} (v{ver})"
    if state == "content mismatch":
        got = _read_skill_version(path)
        detail = f"installed v{got}, expected v{ver}" if got and got != ver else f"differs from v{ver}"
        return f"{path}{suffix} ({detail})"
    return f"{path}{suffix}"


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


def _codex_plugin_state(home: Path) -> tuple[str, str]:
    """Verify the cached Codex plugin skill when present, without invoking the slow Codex CLI."""
    try:
        config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}

    def enabled(plugin: str) -> bool:
        return isinstance(plugins.get(plugin), dict) and plugins[plugin].get("enabled") is True

    if enabled("your-turn-handoff@my-agent-skills"):
        return "unverified", "Using standalone plugin your-turn-handoff@my-agent-skills."
    if enabled(PLUGIN):
        expected = plugin_text(f"skills/{STANDALONE_HANDOFF}/SKILL.md")
        ver = handoff_version()
        cache_root = home / "plugins" / "cache" / MARKETPLACE / NAME
        cached = cache_root / __version__ / "skills" / STANDALONE_HANDOFF / "SKILL.md"
        if cached.exists():
            state = _state(cached, expected)
            if state == "current":
                return state, f"{cached} (v{ver})"
            got = _read_skill_version(cached)
            detail = f"cached v{got}, expected v{ver}" if got and got != ver else f"differs from v{ver}"
            return state, f"{cached} ({detail}; run `install` to refresh)"
        if cache_root.is_dir():
            others = sorted(cache_root.glob(f"*/skills/{STANDALONE_HANDOFF}/SKILL.md"), reverse=True)
            if others:
                other = others[0]
                got = _read_skill_version(other) or other.parents[2].name
                return "content mismatch", f"{other} (cached v{got}, expected v{ver}; run `install` to refresh)"
    return ("unverified", "Codex keeps the plugin from its marketplace in its own cache, "
            "which Your Turn did not find here; `install` refreshes it.")


def _installed_loop_skills() -> tuple[list[tuple[str, str | None]], list[str], str | None]:
    """Read installed Loop skill versions and the newest lockfile date from `~/.agents`."""
    skills_dir = agents_home() / "skills"
    installed: list[tuple[str, str | None]] = []
    missing: list[str] = []
    for name in LOOP_SKILLS:
        path = skills_dir / name / "SKILL.md"
        if path.is_file():
            installed.append((name, _read_skill_version(path)))
        else:
            missing.append(name)
    latest_date: str | None = None
    try:
        lock = json.loads((agents_home() / ".skill-lock.json").read_text(encoding="utf-8"))
        entries = lock.get("skills") if isinstance(lock, dict) else None
        if isinstance(entries, dict):
            dates = [
                str(entries[name].get("updatedAt", ""))[:10]
                for name in LOOP_SKILLS
                if isinstance(entries.get(name), dict) and entries[name].get("updatedAt")
            ]
            latest_date = max(dates) if dates else None
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    return installed, missing, latest_date


def _format_loop_skills(installed: list[tuple[str, str | None]]) -> str:
    return ", ".join(f"{name} {ver}" if ver else name for name, ver in installed)


def _check_loop_skills() -> list[tuple[str, str, str, str]]:
    skills_dir = agents_home() / "skills"
    installed, missing, latest_date = _installed_loop_skills()
    results: list[tuple[str, str, str, str]] = []
    if installed and not missing:
        updated = f", updated {latest_date}" if latest_date else ""
        results.append(("loop", "skills", "installed",
                        f"{_format_loop_skills(installed)} · {skills_dir}{updated} "
                        "(run `DISABLE_TELEMETRY=1 npx skills check` to compare with GitHub)"))
    elif installed:
        results.append(("loop", "skills", "partial",
                        f"installed: {_format_loop_skills(installed)}; missing: {', '.join(missing)} "
                        "(run `install` to sync)"))
    else:
        results.append(("loop", "skills", "not installed",
                        f"Optional Loop skills not found in {skills_dir}; `install` adds them when Node.js is available."))
    dup = skills_dir / STANDALONE_HANDOFF / "SKILL.md"
    if dup.exists() or (skills_dir / STANDALONE_HANDOFF).is_symlink():
        dup_ver = _read_skill_version(dup) if dup.exists() else None
        ver_label = f"v{dup_ver}, " if dup_ver else ""
        results.append(("loop", "duplicate handoff", "duplicate",
                        f"{dup} ({ver_label}duplicates Your Turn v{handoff_version()}; run `install` to remove it)"))
    return results


def check(harnesses: list[str], homes: dict[str, Path]) -> list[tuple[str, str, str, str]]:
    """(app, artifact, state, note) for each handoff artifact, read-only and without running any app CLI."""
    results: list[tuple[str, str, str, str]] = []
    for harness in harnesses:
        home = homes[harness]
        shared = agents_home() / "skills" / NAME / "SKILL.md"
        if harness == "codex":
            if shutil.which("codex"):
                state, note = _codex_plugin_state(home)
                results.append(("codex", "plugin", state, note))
            else:
                state = _state(shared, shared_skill_text())
                results.append(("codex", "shared skill", state, _skill_note(shared, state)))
            continue
        if harness == "cursor" and _shared_skill():
            state = _state(shared, shared_skill_text())
            results.append(("cursor", "skill", state, _skill_note(shared, state, " (shared)")))
        else:
            skill_path = home / "skills" / NAME / "SKILL.md"
            state = _state(skill_path, skill_text(harness))
            results.append((harness, "skill", state, _skill_note(skill_path, state)))
        if harness == "claude":
            results.append(("claude", "CLAUDE.md block", _block_state(home / "CLAUDE.md"), str(home / "CLAUDE.md")))
            capture = usage.state(home)
            results.append(("claude", "plan usage capture", "unverified (off)" if capture == "off" else capture,
                            "Opt-in: `install --claude-usage` routes the status line through a local script that saves "
                            "the 5-hour and weekly usage for the Deck and keeps your status line."))
        else:
            results.append(("cursor", "rule", _state(_cursor_rule(home), cursor_rule_file()), str(_cursor_rule(home))))
            results.append(("cursor", "rule loaded", "unverified",
                            "Cursor applies the rule file in new chats, and Your Turn cannot see whether it did; Customize → "
                            "Rules lists it as your-turn under User. Without it, add a User Rule with the text from "
                            f"{CURSOR_RULE_DOCS}, or the text that `{CURSOR_RULE}` prints."))
    if harnesses:
        results.extend(_check_loop_skills())
    return results


def doctor(harnesses: list[str], homes: dict[str, Path]) -> int:
    """Print each artifact's state; 1 when one is missing, differs from the current text, cannot be read, or duplicates."""
    print(_paint(f"Your Turn doctor · {_version_banner()} (read-only)", "1;36"), flush=True)
    results = check(harnesses, homes)
    for app in dict.fromkeys(app for app, *_ in results):
        print(_paint(SECTIONS.get(app, app), "1;36"), flush=True)
        for _, artifact, state, note in (result for result in results if result[0] == app):
            color = ("32" if state in ("current", "installed")
                     else "33" if ("unverified" in state or state in ("not installed", "partial")) else "31")
            print(f"  {artifact}: {_paint(state, color)}", flush=True)
            print(f"    {_paint(note, '2')}", flush=True)
    if not results:
        print("No Codex, Claude Code or Cursor folder found, so there is nothing to check.", flush=True)
    return 1 if any(state in ("missing", "content mismatch", "unreadable", "duplicate") for _, _, state, _ in results) else 0


# --- Loop skills ---------------------------------------------------------------------------------

LOOP_REPO = "martin-gomola/your-turn-loop"
LOOP_PAGE = "https://martin-gomola.github.io/your-turn-loop/"
# ponytail: fixed list of the Loop's skills other than the handoff, which this package installs itself
# in each app's wording; add a name here when the Loop gains a skill.
LOOP_SKILLS = ("orchestrate", "what-to-ask", "second-opinion", "delegate-code", "codex-image")
# Skills CLI agent names; `antigravity` installs to ~/.gemini/config/skills, which the Gemini app reads too.
LOOP_AGENTS = {"codex": "codex", "claude": "claude-code", "cursor": "cursor"}


def loop_agents(harnesses: list[str], gemini: bool) -> list[str]:
    """Skills CLI agents for the chosen apps, plus Antigravity and the Gemini app when `~/.gemini` exists."""
    agents = [LOOP_AGENTS[harness] for harness in harnesses]
    if gemini and (Path.home() / ".gemini").is_dir():
        agents.append("antigravity")
    return agents


def install_loop_skills(agents: list[str]) -> bool:
    """Install the Loop skills globally through the Skills CLI, the same command the Loop page builds."""
    if not agents:
        return True
    if not shutil.which("npx"):
        print(f"{_paint('!', '33')} Loop skills skipped: Node.js (npx) not found. Pick them on {LOOP_PAGE}", flush=True)
        return False
    command = ["npx", "--yes", "skills", "add", LOOP_REPO, "--skill", *LOOP_SKILLS, "--agent", *agents, "--global", "--yes"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=300,
                              env={**os.environ, "DISABLE_TELEMETRY": "1"}).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        done = False
    if done:
        installed, _, _ = _installed_loop_skills()
        summary = _format_loop_skills(installed) if installed else ", ".join(LOOP_SKILLS)
        where = f"for {', '.join(agents)} · {agents_home() / 'skills'}"
        print(f"{_paint('✓', '32')} {_paint('Loop skills', '1;36')}", flush=True)
        print(f"  {summary}", flush=True)
        print(f"  {_paint(where, '2')}", flush=True)
    else:
        print(f"{_paint('!', '33')} Loop skills not installed. Run: {' '.join(command)}", flush=True)
    return done


def _remove_standalone_handoff(homes: dict[str, Path]) -> str:
    """Remove a duplicate standalone `your-turn-handoff` from `~/.agents/skills` when Your Turn owns it."""
    folder = agents_home() / "skills" / STANDALONE_HANDOFF
    skill = folder / "SKILL.md"
    if not folder.exists() and not folder.is_symlink():
        return ""
    if linked := _linked(folder):
        print(f"{_paint('!', '33')} {_paint('Standalone handoff', '1;36')}", flush=True)
        print(f"  Duplicate {STANDALONE_HANDOFF} {linked}; remove it to avoid loading two handoff skills", flush=True)
        return "kept"
    if not skill.is_file() or not _ours(skill, STANDALONE_HANDOFF):
        return ""
    old_ver = _read_skill_version(skill)
    target = folder.resolve()
    for home in homes.values():
        link = home / "skills" / STANDALONE_HANDOFF
        try:
            if link.is_symlink() and link.resolve() == target:
                link.unlink()
        except OSError:
            pass
    skill.unlink(missing_ok=True)
    license_file = folder / "LICENSE"
    if license_file.is_file() and not license_file.is_symlink():
        license_file.unlink()
    tests_dir = folder / "tests"
    if tests_dir.is_dir() and not tests_dir.is_symlink():
        files_in_tests = [p for p in tests_dir.rglob("*") if p.is_file() or p.is_symlink()]
        if all(not p.is_symlink() and p.suffix in {".yaml", ".yml", ".md"} for p in files_in_tests):
            shutil.rmtree(tests_dir)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    lock_path = agents_home() / ".skill-lock.json"
    if lock_path.is_file() and not lock_path.is_symlink():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            skills = lock.get("skills") if isinstance(lock, dict) else None
            if (isinstance(skills, dict) and isinstance(skills.get(STANDALONE_HANDOFF), dict)
                    and skills[STANDALONE_HANDOFF].get("source") == LOOP_REPO):
                del skills[STANDALONE_HANDOFF]
                lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    label = f" (v{old_ver})" if old_ver else ""
    print(f"{_paint('✓', '32')} {_paint('Standalone handoff', '1;36')}", flush=True)
    print(f"  Removed duplicate {STANDALONE_HANDOFF}{label}; Your Turn manages v{handoff_version()}", flush=True)
    print(f"  {_paint(str(agents_home() / 'skills'), '2')}", flush=True)
    return "removed"


def install(harnesses: list[str], homes: dict[str, Path]) -> list[str]:
    """Set up each app and return the ones that got the handoff, which need a restart to load it."""
    title = f"Your Turn setup · {_version_banner()}"
    print(_paint(title, "1;36"), flush=True)
    print(_paint("─" * len(title), "2"), flush=True)
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
    if done:
        _remove_standalone_handoff(homes)
    return done


def uninstall(harnesses: list[str], homes: dict[str, Path]) -> None:
    for harness in harnesses:
        {"codex": uninstall_plugin, "claude": uninstall_claude, "cursor": uninstall_cursor}[harness](homes[harness])
