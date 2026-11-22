# Radar Legislativo — atalhos. Requer Python 3.12 (ajuste PYTHON se necessário).
PYTHON ?= python3.12
VENV   := .venv
PY     := $(VENV)/bin/python

.PHONY: setup lock db-init db-check test test-integration lint format precommit

setup:            ## cria o ambiente, instala dependências e os hooks do pre-commit
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements-dev.txt
	$(VENV)/bin/pip install -e . --no-deps
	$(VENV)/bin/pre-commit install

lock:             ## regenera requirements*.txt a partir dos .in (requer uv)
	uv pip compile requirements.in -o requirements.txt --python-version 3.12 --no-header --no-annotate
	uv pip compile requirements-dev.in -o requirements-dev.txt --python-version 3.12 --no-header --no-annotate

db-init:          ## cria schemas bronze/silver/gold/ops e tabelas de controle
	$(PY) -m radar db init

db-check:         ## testa a conexão e lista as camadas
	$(PY) -m radar db check

test:             ## testes unitários com cobertura
	$(VENV)/bin/pytest -m "not integration" --cov=radar --cov-report=term-missing

test-integration: ## testes que usam o banco de DATABASE_URL
	$(VENV)/bin/pytest -m integration

lint:
	$(VENV)/bin/ruff check . && $(VENV)/bin/ruff format --check .

format:
	$(VENV)/bin/ruff check --fix . && $(VENV)/bin/ruff format .

precommit:
	$(VENV)/bin/pre-commit run --all-files
