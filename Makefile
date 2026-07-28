PYTHON      ?= python3
VENV        := venv
BIN         := $(VENV)/bin
PIP         := $(BIN)/pip
PY          := $(BIN)/python
MODULE      := -m govee_charts.main

.PHONY: help install venv deps config run serve discover systemd-install systemd-uninstall systemd-restart restart systemd-status

help:
	@echo "Targets:"
	@echo "  make install            Create venv, install deps, copy config if missing"
	@echo "  make run                Run BLE collector + web UI (http://127.0.0.1:8080)"
	@echo "  make serve              Run web UI only (no BLE scanner)"
	@echo "  make discover           Scan BLE Govee devices for 30s then exit"
	@echo "  make systemd-install    Install systemd service (sudo, starts on boot)"
	@echo "  make systemd-uninstall  Remove systemd service"
	@echo "  make systemd-restart    Restart systemd service (sudo)"
	@echo "  make restart            Alias for systemd-restart"

install: venv deps config

venv:
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)

deps: venv
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

systemd-install: install
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh install

systemd-uninstall:
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh uninstall

systemd-restart:
	chmod +x scripts/install-systemd.sh
	./scripts/install-systemd.sh restart

restart: systemd-restart

systemd-status:
	./scripts/install-systemd.sh status
