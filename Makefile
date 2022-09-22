# SPDX-License-Identifier: GPL-3.0-only
.DEFAULT_GOAL := help
UV ?= uv

PREFIX ?= /usr
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib/nordvpn
UNITDIR ?= $(PREFIX)/lib/systemd/system
SYSUSERSDIR ?= $(PREFIX)/lib/sysusers.d
DATADIR ?= $(PREFIX)/share
SYSCONFDIR ?= /etc
PYTHON ?= /usr/bin/python3
BUILD_PYTHON ?= python3
DESTDIR ?=
BUILD ?= build
DIST ?= dist
NFPM_IMAGE ?= goreleaser/nfpm:v2.47.0
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"$$/\1/p' src/nordvpn_linux/__init__.py)
SOURCES := $(shell find src -name '*.py')
SHELL_SCRIPTS = $(wildcard packaging/launchers/*.in packaging/scripts/*.sh packaging/completions/nordvpn.bash tests/e2e/*/*.sh)

# $(call inst,SOURCE,DEST,MODE): install one file, creating its directory.
define inst
	mkdir -p "$(dir $(2))"
	install -m $(3) "$(1)" "$(2)"
endef

.PHONY: help dev lint shellcheck fmt typecheck test check pyz generated install-files install \
	uninstall packages deb stage e2e dist-tarball clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: ## Create or update the development environment
	$(UV) sync

lint: ## Lint and check formatting
	$(UV) run ruff check .
	$(UV) run ruff format --check .

shellcheck: ## Lint shell scripts
	shellcheck $(SHELL_SCRIPTS)

fmt: ## Fix lint issues and format
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: ## Run mypy --strict
	$(UV) run mypy

test: ## Unit + integration tests, with the daemon coverage gate
	$(UV) run pytest --cov --cov-report=term-missing
	$(UV) run coverage report --include='*/nordvpn_linux/daemon/*' --fail-under=90

check: lint typecheck test ## Everything CI runs except shellcheck and e2e

pyz: $(DIST)/nordvpn.pyz ## Build the zipapp

$(DIST)/nordvpn.pyz: $(SOURCES) packaging/zipapp_main.py
	rm -rf "$(BUILD)/pyz"
	mkdir -p "$(BUILD)/pyz" "$(DIST)"
	cp -R src/nordvpn_linux "$(BUILD)/pyz/"
	find "$(BUILD)/pyz" -name '__pycache__' -prune -exec rm -rf {} +
	cp packaging/zipapp_main.py "$(BUILD)/pyz/__main__.py"
	$(BUILD_PYTHON) -m zipapp "$(BUILD)/pyz" -o "$@" -c

generated: ## Render the launchers and systemd unit for PREFIX
	mkdir -p "$(BUILD)/gen"
	sed -e 's|@PYTHON@|$(PYTHON)|g' -e 's|@LIBDIR@|$(LIBDIR)|g' packaging/launchers/nordvpn.in > "$(BUILD)/gen/nordvpn"
	sed -e 's|@PYTHON@|$(PYTHON)|g' -e 's|@LIBDIR@|$(LIBDIR)|g' packaging/launchers/nordvpnd.in > "$(BUILD)/gen/nordvpnd"
	sed -e 's|@BINDIR@|$(BINDIR)|g' packaging/systemd/nordvpnd.service.in > "$(BUILD)/gen/nordvpnd.service"

install-files: pyz generated ## Copy files into DESTDIR+PREFIX (changes nothing else)
	$(call inst,$(DIST)/nordvpn.pyz,$(DESTDIR)$(LIBDIR)/nordvpn.pyz,0644)
	$(call inst,$(BUILD)/gen/nordvpn,$(DESTDIR)$(BINDIR)/nordvpn,0755)
	$(call inst,$(BUILD)/gen/nordvpnd,$(DESTDIR)$(BINDIR)/nordvpnd,0755)
	$(call inst,$(BUILD)/gen/nordvpnd.service,$(DESTDIR)$(UNITDIR)/nordvpnd.service,0644)
	$(call inst,packaging/sysusers.d/nordvpn.conf,$(DESTDIR)$(SYSUSERSDIR)/nordvpn.conf,0644)
	$(call inst,packaging/completions/nordvpn.bash,$(DESTDIR)$(DATADIR)/bash-completion/completions/nordvpn,0644)
	$(call inst,packaging/completions/_nordvpn,$(DESTDIR)$(DATADIR)/zsh/site-functions/_nordvpn,0644)
	$(call inst,packaging/completions/nordvpn.fish,$(DESTDIR)$(DATADIR)/fish/vendor_completions.d/nordvpn.fish,0644)
	$(call inst,LICENSE,$(DESTDIR)$(DATADIR)/licenses/nordvpn-linux/LICENSE,0644)
	@if [ ! -e "$(DESTDIR)$(SYSCONFDIR)/nordvpn/nordvpnd.toml" ]; then \
		mkdir -p "$(DESTDIR)$(SYSCONFDIR)/nordvpn" && \
		install -m 0644 packaging/nordvpnd.toml "$(DESTDIR)$(SYSCONFDIR)/nordvpn/nordvpnd.toml"; \
	fi

install: install-files ## Install, create the group and start the daemon (run as root)
	systemd-sysusers $(SYSUSERSDIR)/nordvpn.conf
	systemctl daemon-reload
	systemctl enable --now nordvpnd.service
	@echo "Installed. Add yourself to the nordvpn group: sudo usermod -aG nordvpn \$$USER"

uninstall: ## Stop the daemon and remove installed files (run as root)
	-systemctl disable --now nordvpnd.service
	rm -f "$(DESTDIR)$(BINDIR)/nordvpn" "$(DESTDIR)$(BINDIR)/nordvpnd"
	rm -f "$(DESTDIR)$(UNITDIR)/nordvpnd.service" "$(DESTDIR)$(SYSUSERSDIR)/nordvpn.conf"
	rm -f "$(DESTDIR)$(DATADIR)/bash-completion/completions/nordvpn"
	rm -f "$(DESTDIR)$(DATADIR)/zsh/site-functions/_nordvpn"
	rm -f "$(DESTDIR)$(DATADIR)/fish/vendor_completions.d/nordvpn.fish"
	rm -rf "$(DESTDIR)$(LIBDIR)" "$(DESTDIR)$(DATADIR)/licenses/nordvpn-linux"
	-systemctl daemon-reload
	@echo "Kept: $(SYSCONFDIR)/nordvpn, /var/lib/nordvpn and the nordvpn group."

packages: ## Build .deb, .rpm and Arch packages into dist/ (needs Docker)
	$(MAKE) stage
	for packager in deb rpm archlinux; do \
		docker run --rm -e VERSION=$(VERSION) -v "$(CURDIR):/src" -w /src $(NFPM_IMAGE) \
			package --config packaging/nfpm.yaml --packager $$packager --target $(DIST)/ || exit 1; \
	done

deb: ## Build only the .deb (used by the e2e tests)
	$(MAKE) stage
	docker run --rm -e VERSION=$(VERSION) -v "$(CURDIR):/src" -w /src $(NFPM_IMAGE) \
		package --config packaging/nfpm.yaml --packager deb --target $(DIST)/

e2e: deb ## End-to-end tests in Docker (E2E_KEEP=1 keeps the stack running)
	$(UV) run pytest -m e2e tests/e2e -v

stage:
	rm -rf build/root
	mkdir -p $(DIST)
	$(MAKE) install-files DESTDIR="$(CURDIR)/build/root" PREFIX=/usr SYSCONFDIR=/etc PYTHON=/usr/bin/python3

dist-tarball: ## Source tarball of HEAD for releases
	mkdir -p $(DIST)
	git archive --format=tar.gz --prefix=nordvpn-linux-$(VERSION)/ -o $(DIST)/nordvpn-linux-$(VERSION).tar.gz HEAD

clean: ## Remove build output
	rm -rf build dist .coverage htmlcov .mypy_cache .pytest_cache .ruff_cache
