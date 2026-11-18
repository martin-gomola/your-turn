PORT ?= 8787
STATE_DIR ?= $(HOME)/.your-turn
LOG_FILE := $(STATE_DIR)/server.log
MARKETPLACE := your-turn
HANDOFF_SOURCE ?= ../your-turn-loop

SITE_PORT ?= 8791

.PHONY: install doctor up down restart phone status logs test screenshots demo update-skill site site-assets

# Build and serve the install page locally (loopback only; Ctrl-C to stop).
site: site-assets
	@echo "Serving the install page at http://127.0.0.1:$(SITE_PORT) (Ctrl-C to stop)"
	@python3 -m http.server $(SITE_PORT) --bind 127.0.0.1 --directory site

# Internal step for site and the Pages workflow: copy the README screenshots in (site/images is ignored).
# Separate only because CI needs the copy without a server that never exits.
site-assets:
	@mkdir -p site/images
	@cp docs/images/inbox-light.png docs/images/deck.gif docs/images/deck-launcher.png src/yourturn/static/icon.svg site/images/

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

# Python suite, then the front-end node tests (tests/*.test.mjs), which pytest does not run.
test:
	@uv run pytest -q
	@node --test tests/*.test.mjs

screenshots:
	@uv sync --quiet
	@uvx --with playwright python scripts/readme_screenshots.py

# Made-up chats in every Deck state for design QA at http://127.0.0.1:8790/deck (disposable homes and state).
demo:
	@uv sync --quiet
	@uv run python -m demo.deck
