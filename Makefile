PYTHON      ?= python3
VENV        := venv
BIN         := $(VENV)/bin
PIP         := $(BIN)/pip
PY          := $(BIN)/python
MODULE      := -m govee_charts.main
UNAME_S     := $(shell uname -s)
AGENT_CHAT_ID_FILE := .cursor/agent-chat-id
AGENT_CHAT_ID ?= $(shell test -f $(AGENT_CHAT_ID_FILE) && tr -d '[:space:]' < $(AGENT_CHAT_ID_FILE))

.PHONY: help install venv deps config stop-local run serve workers discover ssl agent agent-ls agent-new \
	systemd-install systemd-uninstall systemd-restart systemd-status \
	launchd-install launchd-uninstall launchd-restart launchd-status \
	restart restart-ui restart-workers restart-all service-status

help:
	@echo "Targets:"
	@echo "  make install            Create venv, install deps, copy config if missing"
	@echo "  make ssl                Generate self-signed TLS cert (data/ssl/)"
	@echo "  make run                Stop any local instance, then BLE collector + web UI"
	@echo "  make serve              Stop any local instance, then web UI only"
	@echo "  make workers            Stop any local instance, then workers only"
	@echo "  make stop-local         Stop leftover local govee_charts.main processes"
	@echo "  make discover           Scan BLE Govee devices for 30s then exit"
	@echo "  make agent              Resume the pinned Cursor agent for this project"
	@echo "  make agent-ls           List Cursor agent sessions"
	@echo "  make agent-new          Create a chat and pin its id in $(AGENT_CHAT_ID_FILE)"
	@echo "  make systemd-install    Install systemd service (Linux, sudo, starts on boot)"
	@echo "  make systemd-uninstall  Remove systemd service"
	@echo "  make launchd-install    Install LaunchAgent (macOS, starts at login)"
	@echo "  make launchd-uninstall  Remove LaunchAgent"
	@echo "  make restart-ui         Restart UI service only"
	@echo "  make restart-workers    Restart workers service only"
	@echo "  make restart-all        Restart both UI and workers"
	@echo "  make restart            Default restart (workers on Linux; launchd on macOS)"
	@echo "  make service-status     Show background service status"

install: venv deps config

venv:
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)

deps: venv
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt

config:
	@if [ ! -f config.toml ]; then \
		cp config.example.toml config.toml; \
		echo "Created config.toml from config.example.toml"; \
	fi

stop-local:
	chmod +x scripts/stop-local.sh
	./scripts/stop-local.sh

run: deps config stop-local
	$(PY) $(MODULE) --mode all

serve: deps config stop-local
	$(PY) $(MODULE) --mode ui

workers: deps config stop-local
	$(PY) $(MODULE) --mode workers

discover: deps config
	$(PY) $(MODULE) --discover

ssl:
	chmod +x scripts/gen-ssl-cert.sh
	./scripts/gen-ssl-cert.sh

# Resume the project Cursor agent (chat id in .cursor/agent-chat-id).
agent:
	@if [ -z "$(AGENT_CHAT_ID)" ]; then \
		echo "No agent chat id. Run: make agent-new"; \
		echo "Or set AGENT_CHAT_ID=... / write $(AGENT_CHAT_ID_FILE)"; \
		exit 1; \
	fi
	@echo "Resuming agent $(AGENT_CHAT_ID)"
	@if command -v cursor-agent >/dev/null 2>&1; then \
		cursor-agent --workspace "$(CURDIR)" --trust --resume="$(AGENT_CHAT_ID)"; \
	elif command -v cursor >/dev/null 2>&1; then \
		cursor agent --workspace "$(CURDIR)" --trust --resume="$(AGENT_CHAT_ID)"; \
	else \
		echo "cursor-agent / cursor not found in PATH"; \
		exit 1; \
	fi

agent-ls:
	@if command -v cursor-agent >/dev/null 2>&1; then \
		cursor-agent ls; \
	elif command -v cursor >/dev/null 2>&1; then \
		cursor agent ls; \
	else \
		echo "cursor-agent / cursor not found in PATH"; \
		exit 1; \
	fi

agent-new:
	@mkdir -p .cursor
	@if command -v cursor-agent >/dev/null 2>&1; then \
		id=$$(cursor-agent create-chat); \
	elif command -v cursor >/dev/null 2>&1; then \
		id=$$(cursor agent create-chat); \
	else \
		echo "cursor-agent / cursor not found in PATH"; \
		exit 1; \
	fi; \
	id=$$(printf '%s' "$$id" | tr -d '[:space:]'); \
	if [ -z "$$id" ]; then echo "create-chat returned empty id"; exit 1; fi; \
	printf '%s\n' "$$id" > $(AGENT_CHAT_ID_FILE); \
	echo "Pinned $$id in $(AGENT_CHAT_ID_FILE)"; \
	echo "Resume with: make agent"

systemd-install: install
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh install

systemd-uninstall:
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh uninstall

systemd-restart:
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh restart-all

restart-ui:
ifeq ($(UNAME_S),Darwin)
	chmod +x scripts/install-launchd.sh
	./scripts/install-launchd.sh restart
else
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh restart-ui
endif

restart-workers:
ifeq ($(UNAME_S),Darwin)
	chmod +x scripts/install-launchd.sh
	./scripts/install-launchd.sh restart
else
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh restart-workers
endif

restart-all:
ifeq ($(UNAME_S),Darwin)
	chmod +x scripts/install-launchd.sh
	./scripts/install-launchd.sh restart
else
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh restart-all
endif

systemd-status:
	./scripts/install-systemd.sh status

launchd-install: install
	chmod +x scripts/install-launchd.sh
	./scripts/install-launchd.sh install

launchd-uninstall:
	chmod +x scripts/install-launchd.sh
	./scripts/install-launchd.sh uninstall

launchd-restart:
	chmod +x scripts/install-launchd.sh
	./scripts/install-launchd.sh restart

launchd-status:
	chmod +x scripts/install-launchd.sh
	./scripts/install-launchd.sh status

ifeq ($(UNAME_S),Darwin)
restart: launchd-restart
service-status: launchd-status
else
restart: restart-workers
service-status: systemd-status
endif
