# Convenience targets. Every target is a plain docker compose command, listed in the
# README too, so nothing here is required (Windows has no make by default).
.PHONY: up down reset build logs info lint

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

info:          ## print the startup banner again
	docker compose logs --no-log-prefix info

lint:          ## ruff (backend) and eslint (frontend), inside containers
	docker run --rm -v "$(CURDIR)/backend:/app" -w /app python:3.12.16-slim-bookworm sh -c "pip install -q --root-user-action=ignore ruff==0.17.6 && ruff check . && ruff format --check ."
	docker run --rm -v "$(CURDIR)/frontend:/app" -w /app node:24.22.3-alpine sh -c "npm run lint"
