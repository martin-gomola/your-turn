from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from yourturn.cli import main
from yourturn.install import install_plugin


GIT_MARKETPLACE = '[marketplaces.your-turn]\nsource_type = "git"\nsource = "https://github.com/martin-gomola/your-turn.git"\n'


def fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str) -> Path:
    log = tmp_path / "calls.txt"
    script = tmp_path / "codex"
    script.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nexit 0\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text(config)
    monkeypatch.setenv("CODEX_HOME", str(home))
    return log


def test_install_adds_marketplace_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = fake_codex(tmp_path, monkeypatch, '[marketplaces.other]\nsource_type = "local"\nsource = "/x"\n')
    assert install_plugin()
    assert log.read_text().splitlines() == ["plugin marketplace add martin-gomola/your-turn", "plugin add your-turn@your-turn"]


def test_install_reuses_existing_marketplace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = fake_codex(tmp_path, monkeypatch, GIT_MARKETPLACE)
    assert install_plugin()
    assert log.read_text().splitlines() == ["plugin marketplace upgrade your-turn", "plugin add your-turn@your-turn"]


def test_install_treats_an_unreadable_codex_config_as_a_fresh_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = fake_codex(tmp_path, monkeypatch, "not = [toml")
    assert install_plugin()
    assert log.read_text().splitlines() == ["plugin marketplace add martin-gomola/your-turn", "plugin add your-turn@your-turn"]


def test_install_continues_when_marketplace_upgrade_hangs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = fake_codex(tmp_path, monkeypatch, GIT_MARKETPLACE)
    real_run = subprocess.run

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[2:4] == ["marketplace", "upgrade"]:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return real_run(args, **kwargs)

    monkeypatch.setattr("yourturn.install.subprocess.run", run)
    assert install_plugin()
    assert log.read_text().splitlines()[-1] == "plugin add your-turn@your-turn"


def test_install_without_codex_cli_saves_the_shared_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert install_plugin()
    assert (tmp_path / "home" / ".agents" / "skills" / "your-turn" / "SKILL.md").is_file()


@pytest.mark.parametrize("argv", [[], ["--port", "9000"], ["serve", "--port", "9000"]])
def test_no_subcommand_serves(argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import uvicorn

    ports: list[int] = []
    shutdown: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level, timeout_graceful_shutdown:
                        (ports.append(port), shutdown.append(timeout_graceful_shutdown)))
    main(argv)
    assert ports == [9000 if argv else 8787]
    # Open event streams never end on their own: without a timeout, Ctrl+C would hang and pages stay "Live".
    assert shutdown == [2]
    assert "Starting Your Turn at http://localhost:" in capsys.readouterr().out


def test_serve_explains_startup_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import uvicorn

    def fail_to_start(*args: object, **kwargs: object) -> None:
        raise SystemExit(3)

    monkeypatch.setattr(uvicorn, "run", fail_to_start)
    with pytest.raises(SystemExit):
        main(["serve"])

    error = capsys.readouterr().err
    assert "If it is already running, open http://localhost:8787" in error
    assert "your-turn serve --port 8788" in error


def test_usage_names_the_your_turn_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["nope"])
    assert capsys.readouterr().err.startswith("usage: your-turn ")


def test_phone_token_replaces_empty_file_and_keeps_it_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yourturn import cli

    path = tmp_path / ".your-turn" / "phone-token"
    path.parent.mkdir()
    path.write_text(" \n")
    monkeypatch.setattr(cli, "TOKEN_PATH", path)

    token = cli._phone_token()

    assert token and path.read_text() == token
    assert cli._phone_token() == token
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
