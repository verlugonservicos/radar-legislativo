# Radar Legislativo

Pipeline de ETL e análise de dados sobre a API de Dados Abertos da Câmara dos Deputados, com arquitetura medalhão (landing → bronze → silver → gold), classificação e resumos com IA, automação com n8n e dashboards HTML.

**Dashboards:** https://verlugonservicos.github.io/radar-legislativo/ — 8 painéis (visão executiva,
proposições e temas com IA, votações e partidos, deputados, despesas, agenda, articulação e operação).
Detalhes no glossário do próprio site.

## Organização

| Pasta | Conteúdo | No Git? |
|---|---|---|
| `docs/` | Especificação (Plano, PRD, SPEC), ADRs, operação, dicionário de dados, histórico e diagnóstico da VPS | Não (só local) |
| `notebooks/` | Análise exploratória (`01_exploracao_api.ipynb`) | Sim |
| `config/` | Catálogo dos 78 endpoints, OpenAPI oficial e mapa Bronze → Silver | Sim |
| `src/radar/` | Código do pipeline (CLI `python -m radar`) | Sim |
| `sql/` | DDL das camadas (`000_schemas.sql`, `ops/`) | Sim |
| `tests/` | Testes unitários e de integração | Sim |
| `negocio/` | Material do desafio, áudio do DataCast, rascunhos | Não |
| `data/` | Dados extraídos (landing JSON, dumps) | Não |

A especificação vigente para implementação é a **V3** (Supabase self-hosted na VPS, um banco por projeto), mantida localmente em `docs/especificacao/`.

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
Provisionamento, túnel e backup: ver `infra/vps/README.md`.

## Andamento

| Marco | Status |
|---|---|
| M0 Setup | ✅ |
| M0.A Infra VPS | ✅ |
| M1 Catálogo dos 78 endpoints | ✅ |
| M2 Landing + Bronze | ✅ |
| M3 Silver + Gold | ✅ |
| M4 IA | ✅ |
| M5 Dashboards | ⏳ validação |
| M6 Automação | ⏳ |
| M7 Docs e pitch | ⏳ |
