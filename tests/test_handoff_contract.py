from pathlib import Path

import pytest

from yourturn.heuristics import NEXT_KIND, is_check_command, parse_answer
from yourturn.install import CLAUDE_BLOCK, plugin_text


def test_every_next_kind_is_documented_in_all_handoffs():
    documents = [plugin_text("skills/your-turn-handoff/SKILL.md"), CLAUDE_BLOCK,
                 (Path(__file__).parents[1] / "docs/agents-snippet.md").read_text()]
    prefixes = NEXT_KIND.pattern.split("(", 1)[1].split(")", 1)[0].split("|")
    for document in documents:
        for prefix in prefixes:
            assert f"{prefix}:" in document


@pytest.mark.parametrize("join", [" && ", " || ", "; ", "\n"])
def test_check_after_setup(join):
    assert is_check_command(f"echo ready{join}uv run pytest")
    assert not is_check_command("echo 'pytest && make test'")


@pytest.mark.parametrize("step", ["no further action", "no action needed", "žiadny", "žiadne", "nič"])
@pytest.mark.parametrize("position", ["top", "bottom"])
def test_backtick_handoff_in_either_position(step, position):
    block = f"`Outcome: Done`\n`Next step: {step}`"
    text = block + "\n\nDetails." if position == "top" else "Details.\n\n" + block
    assert parse_answer(text) == ("Done", "none", "", True)
