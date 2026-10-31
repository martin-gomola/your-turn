from __future__ import annotations

from pathlib import Path

import pytest

from yourturn.cli import main
from yourturn.install import install_plugin


def fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marketplaces: str) -> Path:
    log = tmp_path / "calls.txt"
    script = tmp_path / "codex"
    script.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n"
                      f"[ \"$3\" = list ] && printf '{marketplaces}'\nexit 0\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    return log


def test_install_adds_marketplace_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = fake_codex(tmp_path, monkeypatch, "MARKETPLACE  ROOT\\nother  /x\\n")
    assert install_plugin()
    assert log.read_text().splitlines() == [
        "plugin marketplace list",
        "plugin marketplace add martin-gomola/your-turn",
        "plugin add your-turn@your-turn",
    ]


def test_install_reuses_existing_marketplace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = fake_codex(tmp_path, monkeypatch, "MARKETPLACE  ROOT\\nyour-turn  /Users/me/your-turn\\n")  # pii:allow (fake path)
    assert install_plugin()
    assert log.read_text().splitlines() == ["plugin marketplace list", "plugin marketplace upgrade your-turn", "plugin add your-turn@your-turn"]


def test_install_without_codex_still_lets_the_inbox_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert not install_plugin()


@pytest.mark.parametrize("argv", [[], ["--port", "9000"], ["serve", "--port", "9000"]])
def test_no_subcommand_serves(argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import uvicorn

    ports: list[int] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: ports.append(port))
    main(argv)
    assert ports == [9000 if argv else 8787]
    assert "Your Turn on http://127.0.0.1:" in capsys.readouterr().out


def test_usage_names_the_your_turn_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["nope"])
    assert capsys.readouterr().err.startswith("usage: your-turn ")
