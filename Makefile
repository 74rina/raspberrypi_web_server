PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
SETUP_STAMP := $(VENV)/.setup-complete

.PHONY: setup run clean

setup: $(SETUP_STAMP)

$(SETUP_STAMP): requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install -r requirements.txt
	touch $(SETUP_STAMP)

run: setup
	$(VENV_PYTHON) app.py

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache
