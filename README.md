# Radar Legislativo

Pipeline de ETL e análise de dados sobre a API de Dados Abertos da Câmara dos Deputados, com arquitetura medalhão (landing → bronze → silver → gold), classificação e resumos com IA, automação com n8n e dashboards HTML.

## Organização

| Pasta | Conteúdo | No Git? |
|---|---|---|
| `docs/especificacao/` | Plano de Projeto, PRD e SPEC (V1 congelada, V2 vigente) | Sim |
| `docs/adr/` | Registros de decisões de arquitetura | Sim |
| `docs/historico/` | Histórico das sessões de trabalho | Sim |
| `notebooks/` | Análise exploratória | Sim |
| `src/radar/` | Código do pipeline (CLI `python -m radar`) | Sim |
| `sql/` | DDL das camadas (`000_schemas.sql`, `ops/`) | Sim |
| `tests/` | Testes unitários e de integração | Sim |
| `negocio/` | Material do desafio, áudio do DataCast, rascunhos | Não |
| `data/` | Dados extraídos (landing JSON, dumps) | Não |

A especificação vigente para implementação é a **V2**: `docs/especificacao/*_V2.*`.

## Como rodar

Requer Python 3.12.

```bash
make setup            # ambiente, dependências e hooks do pre-commit
cp .env.example .env  # preencha as credenciais (o .env nunca vai para o Git)
make db-init          # cria os schemas bronze, silver, gold e ops
make test             # testes unitários
```

Detalhes de configuração do Supabase e do papel somente leitura: [`docs/operacao.md`](docs/operacao.md).

## Andamento

| Marco | Status |
|---|---|
| M0 Setup | ✅ |
| M1 Catálogo dos 78 endpoints | ⏳ |
| M2 Landing + Bronze | ⏳ |
| M3 Silver + Gold | ⏳ |
| M4 IA | ⏳ |
| M5 Dashboards | ⏳ |
| M6 Automação | ⏳ |
| M7 Docs e pitch | ⏳ |
