PYTHON ?= python3

.PHONY: test lint sync-docs check-docs build clean install release-check

test:
	pytest --tb=short -q

lint:
	black --check .
	mypy oasyce --ignore-missing-imports || true

sync-docs:
	$(PYTHON) scripts/sync_docs.py --write

check-docs:
	$(PYTHON) scripts/sync_docs.py

build:
	$(PYTHON) -m build

clean:
	rm -rf dist/ build/ *.egg-info

install:
	pip install -e ".[dev,test]"

release-check:
	@$(PYTHON) scripts/release_check.py
