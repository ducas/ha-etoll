.PHONY: lint typecheck test ci

lint:
	ruff check custom_components/ tests/
	ruff format --check custom_components/ tests/

typecheck:
	mypy custom_components/etoll/client.py custom_components/etoll/const.py

test:
	pytest tests/ -v --cov=custom_components/etoll --cov-report=term-missing

ci: lint typecheck test
