#!/usr/bin/env bash
# =============================================================================
# testar_restauracao.sh — prova que o backup restaura (SPEC V3, seção 23.5)
#
# Uso, NA VPS:  ./testar_restauracao.sh <banco> [arquivo.dump]
# Cria <banco>_restore_teste a partir do dump mais recente, compara o número de
# linhas de cada tabela dos schemas ops e gold com o banco original e remove o
# banco de teste ao final (mesmo em caso de erro).
# =============================================================================
set -euo pipefail

BANCO="${1:?uso: $0 <banco> [arquivo.dump]}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${CONF:-$DIR/bancos.conf}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/postgres}"
PG_ADMIN="${PG_ADMIN:-postgres}"

read -r CONTEINER DONO _ < <(awk -v b="$BANCO" '$3 == b {print $1, $2}' "$CONF")
[ -n "${CONTEINER:-}" ] || { echo "$BANCO não está em bancos.conf"; exit 1; }
DUMP="${2:-$(ls -1t "$BACKUP_DIR/$BANCO/${BANCO}"_*.dump 2>/dev/null | head -1)}"
[ -s "$DUMP" ] || { echo "nenhum dump encontrado para $BANCO"; exit 1; }
TESTE="${BANCO}_restore_teste"

psql_admin() { docker exec "$CONTEINER" psql -U "$PG_ADMIN" -d postgres -XAtq "$@" </dev/null; }
# O banco de teste pertence ao dono do projeto: o provisionador assume esse papel (SET) para removê-lo.
limpa() {
  psql_admin -c "SET ROLE \"$DONO\"" -c "DROP DATABASE IF EXISTS \"$TESTE\" WITH (FORCE)" >/dev/null \
    || echo "AVISO: não consegui remover $TESTE; remova manualmente." >&2
}
trap limpa EXIT

echo "Restaurando $DUMP em $TESTE…"
limpa
psql_admin -c "CREATE DATABASE \"$TESTE\" OWNER \"$DONO\" TEMPLATE template0 ENCODING 'UTF8'"
# O schema extensions e o pgvector são criados pelo provisionador (como no novo_projeto.sql);
# a restauração (feita pelo dono) pula essas entradas do dump.
docker exec "$CONTEINER" psql -h 127.0.0.1 -U "$DONO" -d "$TESTE" -XAtq </dev/null -c "
  CREATE SCHEMA IF NOT EXISTS extensions;
  GRANT USAGE, CREATE ON SCHEMA extensions TO \"$PG_ADMIN\";"
docker exec "$CONTEINER" psql -U "$PG_ADMIN" -d "$TESTE" -XAtq </dev/null \
  -c "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;"
docker exec -i "$CONTEINER" sh -c 'cat > /tmp/restore.dump' < "$DUMP"
docker exec "$CONTEINER" sh -c "pg_restore -l /tmp/restore.dump \
  | grep -v -E ' SCHEMA - extensions | EXTENSION - vector|COMMENT - EXTENSION vector' > /tmp/restore.list" </dev/null
docker exec "$CONTEINER" pg_restore -h 127.0.0.1 -U "$DONO" -d "$TESTE" --no-owner --exit-on-error \
  -L /tmp/restore.list /tmp/restore.dump </dev/null
docker exec "$CONTEINER" rm -f /tmp/restore.dump /tmp/restore.list </dev/null

contagens() {
  docker exec "$CONTEINER" psql -h 127.0.0.1 -U "$DONO" -d "$1" -XAtq -c "
    select format('select %L || ''|'' || count(*) from %I.%I;', n.nspname||'.'||c.relname, n.nspname, c.relname)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where c.relkind = 'r' and n.nspname in ('ops','gold') order by 1" </dev/null \
  | docker exec -i "$CONTEINER" psql -h 127.0.0.1 -U "$DONO" -d "$1" -XAtq
}

diff <(contagens "$BANCO") <(contagens "$TESTE") > /tmp/restauracao_diff.txt || true
if [ -s /tmp/restauracao_diff.txt ]; then
  echo "DIFERENÇAS entre original e restaurado (podem ser cargas feitas depois do dump):"
  cat /tmp/restauracao_diff.txt
  exit 1
fi
echo "OK: $(contagens "$TESTE" | wc -l) tabelas de ops/gold com as mesmas contagens."
