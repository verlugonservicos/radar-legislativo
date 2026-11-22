# Radar Legislativo — atalhos. Requer Python 3.12 (ajuste PYTHON se necessário).
PYTHON ?= python3.12
VENV   := .venv
PY     := $(VENV)/bin/python

# VPS (SPEC V3, seção 23). Sobrescreva na linha de comando se precisar: make tunnel VPS_SSH=outro
VPS_SSH            ?= vps-portfolio
VPS_DB_DESTINO     ?= 127.0.0.1:5433
TUNNEL_PORTA_LOCAL ?= 5433
VPS_DIR            ?= /opt/portfolio/radar-legislativo

.PHONY: catalog catalog-check amostras dicionario setup lock db-init db-check test test-integration lint format precommit tunnel vps-diag vps-sync

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

tunnel:           ## túnel SSH até o pg-gateway da VPS (deixe aberto em outro terminal)
	@echo "Túnel localhost:$(TUNNEL_PORTA_LOCAL) -> $(VPS_SSH):$(VPS_DB_DESTINO)  (Ctrl+C encerra)"
	ssh -N -o ExitOnForwardFailure=yes -L $(TUNNEL_PORTA_LOCAL):$(VPS_DB_DESTINO) $(VPS_SSH)

vps-diag:         ## diagnóstico somente leitura da VPS (saída bruta fica local)
	ssh $(VPS_SSH) 'bash -s' < infra/vps/diagnostico.sh > docs/infra/diagnostico_vps.raw.txt
	@echo "Saída em docs/infra/diagnostico_vps.raw.txt (não versionada)"

vps-sync:         ## copia infra/vps para a VPS (não executa nada lá)
	ssh $(VPS_SSH) 'mkdir -p $(VPS_DIR)/infra/vps'
	rsync -av --exclude '*.raw.txt' infra/vps/ $(VPS_SSH):$(VPS_DIR)/infra/vps/

catalog:          ## sincroniza config/endpoints.yaml com o OpenAPI oficial
	$(PY) -m radar catalog sync

catalog-check:    ## cobertura 78/78 do catálogo contra o OpenAPI
	$(PY) -m radar catalog check

amostras:         ## grava uma resposta real de cada endpoint em tests/fixtures/api
	$(PY) -m radar catalog amostras

dicionario:       ## gera docs/dicionario_de_dados.md
	$(PY) -m radar catalog dicionario

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
