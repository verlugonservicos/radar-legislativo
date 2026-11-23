# Radar Legislativo

Pipeline de ETL e análise de dados sobre a API de Dados Abertos da Câmara dos Deputados, com arquitetura medalhão (landing → bronze → silver → gold), classificação e resumos com IA, automação com n8n e dashboards HTML.

## Organização

| Pasta | Conteúdo | No Git? |
|---|---|---|
| `docs/especificacao/` | Plano de Projeto, PRD e SPEC (V1 e V2 congeladas, V3 vigente) | Sim |
| `docs/decisoes.md` | Registros de decisões de arquitetura (ADRs) | Sim |
| `docs/infra/`, `infra/vps/` | Diagnóstico da VPS e scripts do portfólio (banco por projeto, gateway, backup) | Sim |
| `docs/historico/` | Histórico das sessões de trabalho | Sim |
| `notebooks/` | Análise exploratória (`01_exploracao_api.ipynb`) | Sim |
| `config/` | Catálogo dos 78 endpoints, OpenAPI oficial e mapa Bronze → Silver | Sim |
| `docs/dicionario_de_dados.md` | Campos de cada endpoint e destino na Silver (gerado) | Sim |
| `src/radar/` | Código do pipeline (CLI `python -m radar`) | Sim |
| `sql/` | DDL das camadas (`000_schemas.sql`, `ops/`) | Sim |
| `tests/` | Testes unitários e de integração | Sim |
| `negocio/` | Material do desafio, áudio do DataCast, rascunhos | Não |
| `data/` | Dados extraídos (landing JSON, dumps) | Não |

A especificação vigente para implementação é a **V3** (Supabase self-hosted na VPS, um banco por projeto): `docs/especificacao/*_V3.*`.

## Como rodar

Requer Python 3.12.

```bash
make setup            # ambiente, dependências e hooks do pre-commit
cp .env.example .env  # preencha as credenciais (o .env nunca vai para o Git)
make tunnel           # em outro terminal: túnel SSH até o banco na VPS
make db-init          # cria os schemas bronze, silver, gold e ops
make test             # testes unitários
```

Catálogo: `python -m radar catalog check` (cobertura 78/78 contra o OpenAPI), `catalog sync`, `catalog amostras` e `catalog dicionario`.

O banco fica no Supabase self-hosted da VPS do autor, num banco dedicado ao projeto, sem porta pública.
Provisionamento, túnel, DBeaver e backup: [`docs/operacao.md`](docs/operacao.md).

## Andamento

| Marco | Status |
|---|---|
| M0 Setup | ✅ |
| M0.A Infra VPS | ✅ |
| M1 Catálogo dos 78 endpoints | ✅ |
| M2 Landing + Bronze | ✅ |
| M3 Silver + Gold | ✅ |
| M4 IA | ✅ |
| M5 Dashboards | ⏳ |
| M6 Automação | ⏳ |
| M7 Docs e pitch | ⏳ |
