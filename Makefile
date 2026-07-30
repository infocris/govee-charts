PYTHON      ?= python3
VENV        := venv
BIN         := $(VENV)/bin
PIP         := $(BIN)/pip
PY          := $(BIN)/python
MODULE      := -m govee_charts.main
UNAME_S     := $(shell uname -s)

.PHONY: help install venv deps config run serve discover ssl \
	systemd-install systemd-uninstall systemd-restart systemd-status \
	launchd-install launchd-uninstall launchd-restart launchd-status \
	restart service-status

help:
	@echo "Targets:"
	@echo "  make install            Create venv, install deps, copy config if missing"
	@echo "  make ssl                Generate self-signed TLS cert (data/ssl/)"
	@echo "  make run                Run BLE collector + web UI"
	@echo "  make serve              Run web UI only (no BLE scanner)"
	@echo "  make discover           Scan BLE Govee devices for 30s then exit"
	@echo "  make systemd-install    Install systemd service (Linux, sudo, starts on boot)"
	@echo "  make systemd-uninstall  Remove systemd service"
	@echo "  make launchd-install    Install LaunchAgent (macOS, starts at login)"
	@echo "  make launchd-uninstall  Remove LaunchAgent"
	@echo "  make restart            Restart background service (systemd or launchd)"
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

run: deps config
	$(PY) $(MODULE)

serve: deps config
	$(PY) $(MODULE) --no-scanner

discover: deps config
	$(PY) $(MODULE) --discover

ssl:
	chmod +x scripts/gen-ssl-cert.sh
	./scripts/gen-ssl-cert.sh

systemd-install: install
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh install

systemd-uninstall:
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh uninstall

systemd-restart:
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh restart

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
restart: systemd-restart
service-status: systemd-status
endif
