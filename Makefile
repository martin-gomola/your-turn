PORT ?= 8787
STATE_DIR ?= $(HOME)/.your-turn
LOG_FILE := $(STATE_DIR)/server.log
MARKETPLACE := your-turn
HANDOFF_SOURCE ?= ../my-agent-skills

.PHONY: install doctor up down restart phone status logs test screenshots demo update-skill

update-skill:
	@uv run --quiet python scripts/sync-handoff.py --source "$(HANDOFF_SOURCE)"

install:
	@command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
	@uv sync --quiet
	@# Registered first, so `your-turn install` adds the Codex plugin from this checkout.
	@if command -v codex >/dev/null; then \
		codex plugin marketplace list 2>/dev/null | grep -q "^$(MARKETPLACE) " || codex plugin marketplace add "$(CURDIR)"; \
	fi
	@# No input, so install only sets up and `up` starts the server in the background on $(PORT).
	@uv run --quiet your-turn install </dev/null
	@$(MAKE) --no-print-directory up

doctor:
	@uv run your-turn doctor

up:
	@uv run --quiet your-turn start --port $(PORT) --state-dir "$(STATE_DIR)" $(if $(PHONE),--phone)
	$(if $(PHONE),@cat "$(LOG_FILE)")

# Restart with --phone and show the QR code to scan with the iPhone.
phone:
	@$(MAKE) --no-print-directory down
	@$(MAKE) --no-print-directory up PHONE=1

down:
	@uv run --quiet your-turn stop --state-dir "$(STATE_DIR)"

restart: down up

status:
	@uv run --quiet your-turn status --port $(PORT)

logs:
	@tail -n 50 -f "$(LOG_FILE)"

test:
	@uv run pytest -q

screenshots:
	@uv sync --quiet
	@uvx --with playwright python scripts/readme_screenshots.py

# Made-up chats in every Deck state for design QA at http://127.0.0.1:8790/deck (disposable homes and state).
demo:
	@uv sync --quiet
	@uv run python scripts/deck_demo.py
