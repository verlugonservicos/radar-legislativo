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

## Regras
- Nenhum arquivo de `/opt/supabase` é alterado.
- Senhas nunca são gravadas em arquivos versionados nem passadas na linha de comando.
- Quando houver um segundo projeto no portfólio, esta pasta migra para um repositório próprio (`portfolio-infra`).
