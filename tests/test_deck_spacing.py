"""Deck owns its spacing scale; component spacing must consume that owner."""

import re
from pathlib import Path


CSS = (Path(__file__).parents[1] / "src/yourturn/static/app.css").read_text()
DECK_CSS = CSS.split("/* Deck reference:", 1)[1]


def test_deck_spacing_tokens_have_one_scoped_owner():
    owner = re.search(r'body\[data-view="deck"\]\s*\{([^}]+)\}', DECK_CSS).group(1)
    expected = {"1": "4px", "2": "8px", "3": "12px", "4": "16px", "5": "24px", "6": "32px"}
    declarations = re.findall(r"--space-([1-6])\s*:\s*([^;]+);", DECK_CSS)
    assert dict(declarations) == expected
    assert len(declarations) == len(expected)
    assert dict(re.findall(r"--space-([1-6])\s*:\s*([^;]+);", owner)) == expected


def test_deck_padding_margins_and_gaps_use_tokens():
    declarations = re.findall(r"(?<![\w-])(gap|row-gap|column-gap|padding(?:-[\w-]+)?|margin(?:-[\w-]+)?)\s*:\s*([^;}]+)", DECK_CSS)
    raw = [(name, value) for name, value in declarations if re.search(r"[\d.]+(?:px|rem|em)\b", value)]
    assert not raw, f"Deck spacing must consume --space-1 through --space-6: {raw}"
