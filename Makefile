.PHONY: lint typecheck test test-golden test-all format clean batch

lint:
	ruff check .

typecheck:
	mypy .

test:
	pytest tests/ -v --ignore=tests/test_e2e.py

test-golden:
	pytest tests/test_e2e.py -v

test-all:
	pytest tests/ -v

format:
	ruff format .

clean:
	rm -rf artifacts/ __pycache__ .mypy_cache .pytest_cache .ruff_cache

batch:
	python batch.py --input-dir ./samples/input --profile profiles/ian.yaml --theme space --output ./output/
