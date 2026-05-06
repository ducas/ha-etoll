.PHONY: lint typecheck test ci

lint:
	python3 -m ruff check custom_components/ tests/
	python3 -m ruff format --check custom_components/ tests/

typecheck:
	python3 -m mypy custom_components/etoll/client.py custom_components/etoll/const.py \
		--follow-imports=silent

test:
	python3 -m pytest tests/ -v --cov=custom_components/etoll --cov-report=term-missing

ci: lint typecheck test
