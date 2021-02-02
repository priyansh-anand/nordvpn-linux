# SPDX-License-Identifier: GPL-3.0-only
.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help dev lint fmt typecheck test check

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: ## Create or update the development environment
	$(UV) sync

lint: ## Lint and check formatting
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt: ## Fix lint issues and format
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: ## Run mypy --strict
	$(UV) run mypy

test: ## Unit + integration tests, with the daemon coverage gate
	$(UV) run pytest --cov --cov-report=term-missing
	$(UV) run coverage report --include='*/nordvpn_linux/daemon/*' --fail-under=90

check: lint typecheck test ## Everything CI runs except e2e
