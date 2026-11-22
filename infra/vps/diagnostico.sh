#!/usr/bin/env bash
# =============================================================================
# diagnostico.sh — levantamento SOMENTE LEITURA da VPS (SPEC V3, seção 23.1)
#
# Uso (da máquina de desenvolvimento):
#   ssh vps-portfolio 'bash -s' < infra/vps/diagnostico.sh > docs/infra/diagnostico_vps.raw.txt
#
# Regras:
#   - Não altera nada: nenhum CREATE/ALTER/DROP, nenhum rm, docker stop/rm, ufw allow…
#   - Nunca imprime valores de .env nem variáveis de ambiente de contêineres:
#     de arquivos .env mostra apenas os NOMES das variáveis.
#   - Comandos com sudo usam `sudo -n` (sem pedir senha); se não houver permissão, são pulados.
# =============================================================================
set -u
# O script chega pela entrada padrão (bash -s): nenhum comando interno pode ler stdin,
# senão consome o restante do script. Por isso todo docker exec usa </dev/null e não usa -i.

bloco() { printf '\n### %s\n' "$1"; }
tenta() { "$@" </dev/null 2>&1 || echo "(indisponível: $*)"; }

bloco "Sistema"
tenta uname -a
tenta grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release
echo "cpus: $(nproc 2>/dev/null)"
tenta free -h
tenta df -h -x tmpfs -x devtmpfs -x overlay
tenta uptime

bloco "Docker"
tenta docker version --format 'cliente {{.Client.Version}} / servidor {{.Server.Version}}'
tenta docker compose version
tenta docker compose ls
tenta docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
tenta docker network ls --format '{{.Name}}\t{{.Driver}}'
tenta docker system df

bloco "Supabase — instalação"
DB_CTR=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '(^|[-_])db($|[-_0-9])' | head -1)
echo "conteiner_db: ${DB_CTR:-nao_encontrado}"
for c in $(docker ps --format '{{.Names}}' 2>/dev/null | grep -i -E 'supabase|db|kong|studio|pooler|supavisor' ); do
  wd=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$c" 2>/dev/null)
  proj=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$c" 2>/dev/null)
  svc=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$c" 2>/dev/null)
  nets=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" 2>/dev/null)
  echo "$c | projeto=$proj | servico=$svc | pasta=$wd | redes=$nets"
done
SUPA_DIR=""
[ -n "${DB_CTR}" ] && SUPA_DIR=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$DB_CTR" 2>/dev/null)
[ -z "$SUPA_DIR" ] && [ -d /opt/supabase ] && SUPA_DIR=/opt/supabase
echo "pasta_supabase: ${SUPA_DIR:-desconhecida}"
if [ -n "$SUPA_DIR" ] && [ -d "$SUPA_DIR" ]; then
  tenta ls -la "$SUPA_DIR"
  for envf in "$SUPA_DIR/.env" "$SUPA_DIR/docker/.env"; do
    if [ -r "$envf" ]; then
      echo "-- nomes das variáveis em $envf (valores omitidos):"
      grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$envf" | tr -d '=' | tr '\n' ' '; echo
    elif [ -e "$envf" ]; then
      echo "-- $envf existe mas não é legível por $(whoami)"
    fi
  done
  for cf in "$SUPA_DIR/docker-compose.yml" "$SUPA_DIR/docker/docker-compose.yml"; do
    if [ -r "$cf" ]; then
      echo "-- serviços e imagens em $cf:"
      grep -nE '^  [a-z0-9_-]+:$|image:' "$cf"
      echo "-- portas publicadas em $cf:"
      grep -nE '^\s+- "?\$?\{?[A-Z_0-9]*\}?:?[0-9]*:?[0-9]+"?$|ports:' "$cf" | head -40
    fi
  done
fi

bloco "PostgreSQL"
if [ -n "${DB_CTR}" ]; then
  PSQL=(docker exec "$DB_CTR" psql -U postgres -d postgres -X -A -t -v ON_ERROR_STOP=1)
  tenta "${PSQL[@]}" -c "select version();"
  tenta "${PSQL[@]}" -c "select current_user, (select rolsuper from pg_roles where rolname=current_user) as superuser;"
  echo "-- extensão vector disponível:"
  tenta "${PSQL[@]}" -c "select name, default_version, installed_version from pg_available_extensions where name in ('vector','pg_stat_statements');"
  echo "-- bancos (nome | dono | tamanho):"
  tenta "${PSQL[@]}" -c "select datname, pg_get_userbyid(datdba), pg_size_pretty(pg_database_size(datname)) from pg_database where not datistemplate order by 1;"
  echo "-- papéis com login (nome | super | createdb | createrole):"
  tenta "${PSQL[@]}" -c "select rolname, rolsuper, rolcreatedb, rolcreaterole from pg_roles where rolcanlogin order by 1;"
  echo "-- objetos não padrão no template1 (deve ser vazio para usar template1; senão usar template0):"
  tenta docker exec "$DB_CTR" psql -U postgres -d template1 -X -A -t -c "select extname from pg_extension where extname <> 'plpgsql';"
  echo "-- configurações:"
  tenta "${PSQL[@]}" -c "select name, setting from pg_settings where name in ('max_connections','shared_buffers','listen_addresses','password_encryption','ssl') order by 1;"
  echo "-- regras do pg_hba (tipo | banco | usuário | endereço | método):"
  tenta "${PSQL[@]}" -c "select type, array_to_string(database,','), array_to_string(user_name,','), coalesce(address,''), auth_method from pg_hba_file_rules order by line_number;"
  echo "-- pg_hba.conf (linhas ativas; o arquivo não contém senhas):"
  HBA=$(docker exec "$DB_CTR" psql -U postgres -d postgres -X -A -t -c "show hba_file;" </dev/null 2>/dev/null)
  [ -n "$HBA" ] && tenta docker exec "$DB_CTR" sh -c "grep -vE '^[[:space:]]*(#|$)' '$HBA'"
  echo "-- o papel postgres pode criar bancos/papéis e a extensão vector?"
  tenta "${PSQL[@]}" -c "select rolcreatedb, rolcreaterole from pg_roles where rolname='postgres';"
  tenta "${PSQL[@]}" -c "show supautils.privileged_extensions;"
else
  echo "contêiner do banco não encontrado"
fi

bloco "Rede e portas em escuta"
tenta ss -tlnH
echo "-- firewall:"
if sudo -n true 2>/dev/null; then
  tenta sudo -n ufw status verbose
  tenta sudo -n ss -tlnpH
else
  echo "(sudo sem senha indisponível — firewall e processos por porta não listados)"
  tenta systemctl is-active ufw
fi

bloco "Proxy reverso e HTTPS"
for s in nginx caddy traefik apache2 haproxy; do
  printf '%s: %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || true)"
done
tenta docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' --filter "publish=443"
tenta docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' --filter "publish=80"
ls /etc/nginx/sites-enabled 2>/dev/null && echo "(nomes de sites nginx acima)"
ls /etc/letsencrypt/live 2>/dev/null && echo "(certificados letsencrypt acima — só nomes)"

bloco "n8n"
tenta docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' --filter "name=n8n"
printf 'servico_systemd_n8n: %s\n' "$(systemctl is-active n8n 2>/dev/null || true)"

bloco "Backups e agendamentos"
echo "-- crontab de $(whoami):"; crontab -l </dev/null 2>&1 | grep -v '^#' || true
echo "-- /etc/cron.d:"; ls /etc/cron.d 2>/dev/null
echo "-- timers systemd:"; tenta systemctl list-timers --no-pager --all
ls -d /var/backups/postgres 2>/dev/null || echo "/var/backups/postgres não existe"

bloco "Docker Swarm"
tenta docker info --format 'swarm={{.Swarm.LocalNodeState}} managers={{.Swarm.Managers}} nodes={{.Swarm.Nodes}}'
tenta docker stack ls
tenta docker service ls --format '{{.Name}}\t{{.Image}}\t{{.Replicas}}\t{{.Ports}}'
echo "-- redes attachable (podem receber contêineres fora do swarm):"
for n in verlugonnet supabase_default; do
  printf '%s attachable=%s scope=%s subnet=%s\n' "$n" \
    "$(docker network inspect -f '{{.Attachable}}' "$n" 2>/dev/null)" \
    "$(docker network inspect -f '{{.Scope}}' "$n" 2>/dev/null)" \
    "$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} gw={{.Gateway}} {{end}}' "$n" 2>/dev/null)"
done
echo "-- destino do supabase_proxy (comando do socat, sem segredos):"
tenta docker service inspect supabase_proxy --format '{{json .Spec.TaskTemplate.ContainerSpec.Args}} {{json .Spec.TaskTemplate.ContainerSpec.Command}}'
echo "-- rotas do traefik (só nomes de hosts nas labels dos serviços):"
for s in $(docker service ls --format '{{.Name}}' 2>/dev/null); do
  docker service inspect "$s" --format '{{range $k, $v := .Spec.Labels}}{{if eq (printf "%.15s" $k) "traefik.http.ro"}}{{$k}}={{$v}}
{{end}}{{end}}' 2>/dev/null | grep -i 'rule=' | sed "s/^/$s: /"
done

bloco "Fim"
echo "diagnóstico concluído em $(date -Is) por $(whoami)@$(hostname)"
