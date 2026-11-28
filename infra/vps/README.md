# infra/vps — scripts executados na VPS

Infraestrutura do portfólio na VPS (SPEC V3, seção 23; decisões D1–D5 em `docs/infra/diagnostico_vps.md`).
Destino na VPS: `/opt/portfolio/radar-legislativo/infra/vps/`.

| Arquivo | O que faz | Altera a VPS? |
|---------|-----------|---------------|
| `diagnostico.sh` | Levantamento do servidor, Docker, Supabase, PostgreSQL, rede, proxy, n8n e backups | Não (somente leitura) |
| `novo_projeto.sh` + `sql/novo_projeto.sql` | Cria banco e papéis `<prefixo>_app` / `<prefixo>_leitura` de um projeto, isolados dos demais | Sim |
| `docker-compose.gateway.yml` | `pg-gateway`: acesso ao banco em `127.0.0.1:5433` e `172.18.0.1:5433`, sem expor a 5432 | Sim |
| `backup_bancos.sh` + `bancos.conf` | `pg_dump` diário de cada banco, com retenção | Sim (grava em `/var/backups/postgres`) |
| `testar_restauracao.sh` | Restaura o último dump num banco temporário e compara contagens | Cria e remove um banco de teste |
| `stack.radar.yml` + `Dockerfile` (raiz) | Runner HTTP do pipeline como stack `radar` do Swarm, na rede `verlugonnet`, sem porta publicada (M6, ADR-031) | Sim |

## Ordem de uso (primeira vez)

```bash
# 1. Na máquina de desenvolvimento: copiar os scripts para a VPS
rsync -av infra/vps/ vps-portfolio:/opt/portfolio/radar-legislativo/infra/vps/

# 2. Na VPS (ssh vps-portfolio), pelo autor:
cd /opt/portfolio/radar-legislativo/infra/vps
./novo_projeto.sh radar_legislativo radar          # mostra as senhas geradas uma única vez
docker compose -f docker-compose.gateway.yml up -d # pg-gateway
sudo mkdir -p /var/backups/postgres && sudo chown "$USER": /var/backups/postgres
./backup_bancos.sh && ./testar_restauracao.sh radar_legislativo   # (depois do db init)
crontab -e   # 0 3 * * * /opt/portfolio/radar-legislativo/infra/vps/backup_bancos.sh

# 3. Na máquina de desenvolvimento: túnel + db init
make tunnel        # deixe aberto em outro terminal
make db-check && make db-init
```

## Runner (M6)

```bash
# 1. Na máquina de desenvolvimento: enviar o código (sem .env, data, docs, site)
make vps-deploy-sync

# 2. Na VPS, uma vez: .env (permissão 600, digitado pelo autor) e a deploy key como secret
#    docker secret create gh_deploy_key <arquivo da chave privada> && rm <arquivo da chave privada>
# 3. Na VPS, a cada versão:
cd /opt/portfolio/radar-legislativo
docker build -t radar-runner:<versão> .
RADAR_VERSAO=<versão> docker stack deploy -c infra/vps/stack.radar.yml radar
```

Os workflows ficam em `n8n/workflows/` e são importados no n8n existente (D3), com as credenciais
criadas no próprio n8n: `Radar Runner Token` (Header Auth `X-Runner-Token`), `Radar Postgres`,
`Radar Telegram Bot` e `Gmail account` (OAuth, usada pelo WF03 no lugar do SMTP).
Nos nós do Telegram, o *Chat ID* é preenchido só no n8n (nos arquivos fica `<TELEGRAM_CHAT_ID>`): é o
`chat.id` da resposta de `getUpdates`, não o `update_id`. Agenda: WF01 06:00 (diário), WF02 09:00
(diário), WF03 segunda 08:00; WF99 é o *Error Workflow* dos demais.

## Regras
- Nenhum arquivo de `/opt/supabase` é alterado.
- Senhas nunca são gravadas em arquivos versionados nem passadas na linha de comando.
- Quando houver um segundo projeto no portfólio, esta pasta migra para um repositório próprio (`portfolio-infra`).
