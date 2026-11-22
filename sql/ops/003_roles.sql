-- =====================================================================
-- ops/003_roles.sql — papel somente leitura para dashboards e GitHub Actions
-- A senha NUNCA fica neste arquivo. Crie o papel no SQL Editor do Supabase:
--   CREATE ROLE dashboard_leitura LOGIN PASSWORD '<definir no painel>';
-- Enquanto o papel não existir, este script só emite um aviso.
-- =====================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_leitura') THEN
        GRANT USAGE ON SCHEMA gold, ops TO dashboard_leitura;
        GRANT SELECT ON ALL TABLES IN SCHEMA gold, ops TO dashboard_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO dashboard_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA ops  GRANT SELECT ON TABLES TO dashboard_leitura;
    ELSE
        RAISE NOTICE 'Papel dashboard_leitura ainda não existe — permissões não aplicadas (ver docs/operacao.md).';
    END IF;
END
$$;
