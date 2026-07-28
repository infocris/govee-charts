PYTHON      ?= python3
VENV        := venv
BIN         := $(VENV)/bin
PIP         := $(BIN)/pip
PY          := $(BIN)/python
MODULE      := -m govee_charts.main

.PHONY: help install venv deps config run discover

help:
	@echo "Targets:"
	@echo "  make install    Create venv, install deps, copy config if missing"
	@echo "  make run        Run BLE collector + web UI (http://127.0.0.1:8080)"
	@echo "  make discover   Scan BLE Govee devices for 30s then exit"

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

discover: deps config
	$(PY) $(MODULE) --discover
