# Convenience targets. Every target is a plain docker compose command, listed in the
# README too, so nothing here is required (Windows has no make by default).
.PHONY: up down reset build logs info lint test seed rules-report rules-report-at openapi

# Not `up --wait`: it fails whenever the one-shot `info` container has already exited.
# `info` only starts once api and web are healthy, so waiting for it is the readiness check.
up:            ## start everything in the background, wait until ready, print the banner
	docker compose up -d --build
	docker compose wait info
	docker compose logs --no-log-prefix info

down:          ## stop the stack (keeps the database volume)
	docker compose down

reset:         ## stop and delete all data; the next `up` migrates and seeds from scratch
	docker compose down -v

build:         ## rebuild images
	docker compose build

logs:          ## follow all logs (Dozzle at http://localhost:8080 is nicer)
	docker compose logs -f

test:          ## run the test suite in the test container (APP_NOW frozen at the seed's now)
	docker compose run --rm tests

seed:          ## load the seed into the demo database if it isn't there yet (no-op once seeded)
	docker compose run --rm migrate python -m app.seed

# The committed rules_report.json is always generated at the seed's now (seed.json meta.now),
# whatever APP_NOW says in the shell or .env, from a freshly built image (so code edits
# count), and only replaces the committed file once the command has succeeded.
REPORT_NOW := 2026-11-11T15:00:00Z

rules-report:  ## regenerate the committed rules_report.json (scratch eos_report database)
	docker compose --progress quiet run --rm --build -T -e APP_NOW=$(REPORT_NOW) rules-report > rules_report.json.tmp
	mv rules_report.json.tmp rules_report.json
	@echo "rules_report.json written"

rules-report-at: ## print the report at another date, without touching the committed file: make rules-report-at NOW=2026-11-18T15:00:00Z
	docker compose --progress quiet run --rm --build -e APP_NOW=$(NOW) rules-report

openapi:       ## regenerate the committed openapi.json and the frontend's typed client from the API
	docker compose run --rm --no-deps -T tests python -m app.openapi_export > openapi.json.tmp
	mv openapi.json.tmp openapi.json
	cd frontend && npm run gen:api

info:          ## print the startup banner again
	docker compose logs --no-log-prefix info

lint:          ## ruff (backend) and eslint (frontend), inside containers
	docker run --rm -v "$(CURDIR)/backend:/app" -w /app python:3.12.16-slim-bookworm sh -c "pip install -q --root-user-action=ignore ruff==0.17.6 && ruff check . && ruff format --check ."
	docker run --rm -v "$(CURDIR)/frontend:/app" -w /app node:24.22.3-alpine sh -c "npm run lint"
