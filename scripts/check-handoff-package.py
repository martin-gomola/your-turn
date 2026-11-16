"""Build and install the wheel directly and via sdist, outside the checkout."""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"})


with tempfile.TemporaryDirectory(prefix="handoff-package-") as temporary:
    workspace = Path(temporary)
    dist = workspace / "dist"
    run(["uv", "build", "--out-dir", str(dist)], ROOT)
    archive = next(dist.glob("*.tar.gz"))
    with tarfile.open(archive) as source:
        source.extractall(workspace / "source", filter="data")
    extracted = next((workspace / "source").iterdir())
    assert not (extracted / ".git").exists()
    run(["uv", "build", str(extracted), "--wheel", "--out-dir", str(workspace / "rebuilt")], workspace)
    for index, wheel in enumerate([next(dist.glob("*.whl")), next((workspace / "rebuilt").glob("*.whl"))]):
        with zipfile.ZipFile(wheel) as package:
            bundled = package.read("yourturn/plugin/skills/your-turn-handoff/SKILL.md")
            assert bundled == (ROOT / "plugin/skills/your-turn-handoff/SKILL.md").read_bytes()
            assert package.read("yourturn/plugin/skills/your-turn-handoff/LICENSE")
        environment = workspace / f"env-{index}"
        run(["uv", "venv", str(environment)], workspace)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)], workspace)
        code = '''from pathlib import Path
import tempfile
import yourturn.install as installer
assert "site-packages" in str(installer.__file__)
assert "**Outcome:**" in installer.plugin_text("skills/your-turn-handoff/SKILL.md")
installer.shutil.which = lambda name: None
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary)
    homes={name:root/name for name in ("codex","claude","cursor")}
    installer.agents_home=lambda:root/"agents"
    installer.install(["codex","claude","cursor"],homes)
    assert (root/"agents/skills/your-turn/SKILL.md").is_file()
    assert (homes["claude"]/"skills/your-turn/SKILL.md").is_file()
    assert (homes["cursor"]/"rules/your-turn.mdc").is_file()
'''
        run([str(python), "-c", code], workspace)
    print("Wheel and sdist-rebuilt wheel both install the bundled handoff outside Git without optional client CLIs.")
