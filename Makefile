PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
PLAYBOOK := provision/site.yml
INVENTORY := provision/inventories/local/hosts.yml

.PHONY: venv lint syntax test test-core test-setup test-ui test-provision test-provision-fast clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt

lint:
	$(BIN)/yamllint .
	$(BIN)/ansible-lint provision
	$(BIN)/ruff check core setup ui

syntax:
	$(BIN)/ansible-playbook --syntax-check $(PLAYBOOK) -i $(INVENTORY)

test: test-core test-setup test-ui

test-core:
	$(BIN)/pytest core/tests -q

test-setup:
	$(BIN)/pytest setup/tests -q

test-ui:
	$(BIN)/pytest ui/tests -q

test-provision:
	docker build -t kowalski-provision-test provision/test
	docker run --rm -v "$$PWD":/repo:ro kowalski-provision-test

test-provision-fast:
	docker build -t kowalski-provision-test provision/test
	docker run --rm -v "$$PWD":/repo:ro -e SKIP_TAGS=gpu,desktop kowalski-provision-test

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
