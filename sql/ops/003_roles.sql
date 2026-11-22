-- =====================================================================
-- ops/003_roles.sql — papel somente leitura para dashboards e GitHub Actions
-- O papel radar_leitura é criado por infra/vps/novo_projeto.sh (a senha nunca fica em arquivo).
-- Este script roda como radar_app (dono dos schemas). Enquanto o papel não existir, só avisa.
-- =====================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_leitura') THEN
        GRANT USAGE ON SCHEMA gold, ops TO radar_leitura;
        GRANT SELECT ON ALL TABLES IN SCHEMA gold, ops TO radar_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO radar_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA ops  GRANT SELECT ON TABLES TO radar_leitura;
    ELSE
        RAISE NOTICE 'Papel radar_leitura ainda não existe — permissões não aplicadas (rode infra/vps/novo_projeto.sh).';
    END IF;
END
$$;
