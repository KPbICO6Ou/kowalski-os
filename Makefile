PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
PLAYBOOK := provision/site.yml
INVENTORY := provision/inventories/local/hosts.yml

.PHONY: venv lint syntax test test-core test-setup test-ui test-indexer test-voice test-provision test-provision-fast deb test-deb clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt

lint:
	$(BIN)/yamllint .
	$(BIN)/ansible-lint provision
	$(BIN)/ruff check core setup ui indexer voice

syntax:
	$(BIN)/ansible-playbook --syntax-check $(PLAYBOOK) -i $(INVENTORY)

test: test-core test-setup test-ui test-indexer test-voice

test-core:
	$(BIN)/pytest core/tests -q

test-setup:
	$(BIN)/pytest setup/tests -q

test-ui:
	$(BIN)/pytest ui/tests -q

test-indexer:
	$(BIN)/pytest indexer/tests -q

test-voice:
	$(BIN)/pytest voice/tests -q

test-provision:
	docker build -t kowalski-provision-test provision/test
	docker run --rm -v "$$PWD":/repo:ro kowalski-provision-test

test-provision-fast:
	docker build -t kowalski-provision-test provision/test
	docker run --rm -v "$$PWD":/repo:ro -e SKIP_TAGS=gpu,desktop kowalski-provision-test

deb:
	mkdir -p dist
	docker build -t kowalski-deb-build packaging/deb
	docker run --rm -v "$$PWD":/repo:ro -v "$$PWD/dist":/out kowalski-deb-build

test-deb: deb
	docker run --rm -v "$$PWD/dist":/out -v "$$PWD/packaging/deb/verify-deb.sh":/verify.sh:ro \
		ubuntu:24.04 bash /verify.sh

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
