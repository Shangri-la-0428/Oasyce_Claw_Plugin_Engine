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
	@echo "=== Release Checklist ==="
	@echo ""
	@echo "1. Tests..."
	@pytest --tb=short -q || (echo "FAIL: Tests not passing" && exit 1)
	@echo ""
	@echo "2. Doc sync..."
	@$(PYTHON) scripts/sync_docs.py || (echo "FAIL: Docs out of sync" && exit 1)
	@echo ""
	@echo "3. Build..."
	@$(PYTHON) -m build 2>/dev/null && echo "Build OK" || (echo "FAIL: Build failed" && exit 1)
	@echo ""
	@echo "4. Version check..."
	@$(PYTHON) -c "import tomllib; v=tomllib.load(open('pyproject.toml','rb'))['project']['version']; print(f'Version: v{v}')"
	@echo ""
	@echo "=== All checks passed. Ready to release. ==="
	@echo "  git tag v$$($(PYTHON) -c \"import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])\")"
	@echo "  git push origin --tags    # triggers PyPI release via GitHub Actions"
