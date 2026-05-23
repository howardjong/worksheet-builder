VENV_BIN := .venv/bin
PYTHON := $(if $(wildcard $(VENV_BIN)/python),$(VENV_BIN)/python,python)
RUFF := $(if $(wildcard $(VENV_BIN)/ruff),$(VENV_BIN)/ruff,ruff)
MYPY := $(if $(wildcard $(VENV_BIN)/mypy),$(VENV_BIN)/mypy,mypy)
PYTEST := $(if $(wildcard $(VENV_BIN)/pytest),$(VENV_BIN)/pytest,pytest)

.PHONY: lint typecheck test test-golden test-all format clean batch

lint:
	$(RUFF) check .

typecheck:
	$(MYPY) .

test:
	$(PYTEST) tests/ -v --ignore=tests/test_e2e.py

test-golden:
	$(PYTEST) tests/test_e2e.py -v

test-all:
	$(PYTEST) tests/ -v

format:
	$(RUFF) format .

clean:
	rm -rf artifacts/ __pycache__ .mypy_cache .pytest_cache .ruff_cache

batch:
	$(PYTHON) batch.py --input-dir ./samples/input --profile profiles/ian.yaml --theme space --output ./output/
