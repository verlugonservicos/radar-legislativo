#!/usr/bin/env bash
# =============================================================================
# novo_projeto.sh — cria banco e papéis de um projeto do portfólio na VPS
# (SPEC V3, seção 23.2; decisão D4: roda com o papel postgres, sem superusuário)
#
# Uso, NA VPS, pelo autor:
#   ./novo_projeto.sh <banco> <prefixo> [--digitar-senhas] [--rotacionar-senhas]
#   ex.: ./novo_projeto.sh radar_legislativo radar
#
# Cria:  banco <banco> (dono <prefixo>_app, template0, UTF8)
#        papel <prefixo>_app      — dono do banco, usado pelo pipeline
#        papel <prefixo>_leitura  — somente leitura, statement_timeout 15s, 5 conexões
#        extensão vector no schema extensions
# e acrescenta o banco a bancos.conf (backup diário).
#
# Senhas: por padrão são GERADAS (32 caracteres) e mostradas UMA vez — guarde no seu
# gerenciador de senhas. Com --digitar-senhas, você digita (sem aspas nem barras).
# As senhas vão ao psql pela entrada padrão: não aparecem na lista de processos
# nem são gravadas em arquivo.
# =============================================================================
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-supabase-db}"
PG_ADMIN="${PG_ADMIN:-postgres}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL="$DIR/sql/novo_projeto.sql"
CONF="$DIR/bancos.conf"

uso() { sed -n '4,8p' "$0"; exit 1; }
[ $# -ge 2 ] || uso
BANCO="$1"; PREFIXO="$2"; shift 2
DIGITAR=0; ROTACIONAR=0
for arg in "$@"; do
  case "$arg" in
    --digitar-senhas) DIGITAR=1 ;;
    --rotacionar-senhas) ROTACIONAR=1 ;;
    *) uso ;;
  esac
done

valida_nome() { [[ "$1" =~ ^[a-z][a-z0-9_]{1,40}$ ]] || { echo "nome inválido: $1 (use a-z, 0-9, _)"; exit 1; }; }
valida_nome "$BANCO"; valida_nome "$PREFIXO"
APP="${PREFIXO}_app"; LEITURA="${PREFIXO}_leitura"

gera_senha() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; }
le_senha() {
  local rotulo="$1" s1 s2
  while true; do
    read -r -s -p "Senha para $rotulo: " s1; echo >&2
    read -r -s -p "Repita a senha: " s2; echo >&2
    if [ "$s1" != "$s2" ]; then echo "As senhas não conferem." >&2; continue; fi
    if [ ${#s1} -lt 16 ]; then echo "Use pelo menos 16 caracteres." >&2; continue; fi
    if [[ "$s1" =~ [\'\"\\[:space:]] ]]; then echo "Não use aspas, barra invertida nem espaços." >&2; continue; fi
    printf '%s' "$s1"; return
  done
}

docker inspect "$DB_CONTAINER" >/dev/null 2>&1 || { echo "contêiner $DB_CONTAINER não encontrado"; exit 1; }

EXISTE_APP=$(docker exec "$DB_CONTAINER" psql -U "$PG_ADMIN" -d postgres -XAtc \
  "select count(*) from pg_roles where rolname='$APP'" </dev/null)
if [ "$EXISTE_APP" = "1" ] && [ "$ROTACIONAR" = "0" ]; then
  echo "Papéis já existem: as senhas atuais serão mantidas (use --rotacionar-senhas para trocar)."
  SENHA_APP="nao-usada"; SENHA_LEITURA="nao-usada"; MOSTRAR=0
elif [ "$DIGITAR" = "1" ]; then
  SENHA_APP=$(le_senha "$APP"); SENHA_LEITURA=$(le_senha "$LEITURA"); MOSTRAR=0
else
  SENHA_APP=$(gera_senha); SENHA_LEITURA=$(gera_senha); MOSTRAR=1
fi

echo "Provisionando banco '$BANCO' (papéis $APP e $LEITURA) em $DB_CONTAINER como $PG_ADMIN…"
{
  printf '\\set banco %s\n\\set app %s\n\\set leitura %s\n' "$BANCO" "$APP" "$LEITURA"
  printf '\\set senha_app %s\n\\set senha_leitura %s\n\\set rotacionar %s\n' \
    "$SENHA_APP" "$SENHA_LEITURA" "$ROTACIONAR"
  cat "$SQL"
} | docker exec -i "$DB_CONTAINER" psql -U "$PG_ADMIN" -d postgres -X

# Registra o banco para o backup (dump feito pelo dono, via 127.0.0.1 dentro do contêiner)
LINHA="$DB_CONTAINER $APP $BANCO"
touch "$CONF"
grep -qxF "$LINHA" "$CONF" || { echo "$LINHA" >> "$CONF"; echo "Acrescentado a bancos.conf: $LINHA"; }

if [ "$MOSTRAR" = "1" ]; then
  cat <<EOF

=====================================================================
 SENHAS GERADAS — mostradas só agora. Guarde no gerenciador de senhas.
   $APP      : $SENHA_APP
   $LEITURA  : $SENHA_LEITURA
 Depois, limpe a tela (comando: clear).
=====================================================================
EOF
fi
echo "Concluído."
