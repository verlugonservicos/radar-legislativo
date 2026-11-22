#!/usr/bin/env bash
# =============================================================================
# backup_bancos.sh — pg_dump diário dos bancos do portfólio (SPEC V3, seção 23.4)
#
# Lê bancos.conf (uma linha por banco:  <contêiner> <usuário> <banco>) e grava
#   $BACKUP_DIR/<banco>/<banco>_<AAAAMMDD_HHMM>.dump   (formato custom, -Fc)
# Retenção: $RETENCAO_DIARIA dias; aos domingos uma cópia vai para semanal/
# (mantidas $RETENCAO_SEMANAS semanas). Opcional: RCLONE_DESTINO para cópia externa.
#
# O dump roda dentro do contêiner, conectando em 127.0.0.1 (autenticação local do
# Supabase), com o próprio dono do banco: não precisa de senha nem de superusuário.
#
# Cron sugerido (crontab do seu usuário na VPS, o mesmo de $USER):
#   0 3 * * * /opt/portfolio/radar-legislativo/infra/vps/backup_bancos.sh
# =============================================================================
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${CONF:-$DIR/bancos.conf}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/postgres}"
RETENCAO_DIARIA="${RETENCAO_DIARIA:-7}"
RETENCAO_SEMANAS="${RETENCAO_SEMANAS:-4}"
LOG="${LOG:-$BACKUP_DIR/backup.log}"
RCLONE_DESTINO="${RCLONE_DESTINO:-}"

mkdir -p "$BACKUP_DIR" || { echo "sem permissão em $BACKUP_DIR"; exit 2; }
umask 077
log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

[ -r "$CONF" ] || { log "ERRO bancos.conf não encontrado: $CONF"; exit 2; }

falhas=0
carimbo=$(date +%Y%m%d_%H%M)
while read -r conteiner usuario banco _; do
  [[ -z "${conteiner:-}" || "$conteiner" == \#* ]] && continue
  destino="$BACKUP_DIR/$banco"; mkdir -p "$destino/semanal"
  arquivo="$destino/${banco}_${carimbo}.dump"
  if docker exec "$conteiner" pg_dump -h 127.0.0.1 -U "$usuario" -d "$banco" -Fc </dev/null > "$arquivo.tmp" \
     && [ -s "$arquivo.tmp" ]; then
    mv "$arquivo.tmp" "$arquivo"
    log "OK $banco $(du -h "$arquivo" | cut -f1) $arquivo"
    [ "$(date +%u)" = "7" ] && cp "$arquivo" "$destino/semanal/"
  else
    rm -f "$arquivo.tmp"; falhas=$((falhas + 1))
    log "ERRO falha no dump de $banco (contêiner $conteiner, usuário $usuario)"
    continue
  fi
  find "$destino" -maxdepth 1 -name "${banco}_*.dump" -mtime +"$RETENCAO_DIARIA" -delete
  find "$destino/semanal" -name "${banco}_*.dump" -mtime +$((RETENCAO_SEMANAS * 7)) -delete
done < "$CONF"

if [ -n "$RCLONE_DESTINO" ] && command -v rclone >/dev/null; then
  rclone copy "$BACKUP_DIR" "$RCLONE_DESTINO" --exclude backup.log && log "OK cópia externa para $RCLONE_DESTINO" \
    || { log "ERRO cópia externa"; falhas=$((falhas + 1)); }
fi

[ "$falhas" -eq 0 ] && log "backup concluído sem falhas" || log "backup concluído com $falhas falha(s)"
exit "$falhas"
