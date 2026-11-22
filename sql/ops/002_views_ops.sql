-- =====================================================================
-- ops/002_views_ops.sql — visões de operação
-- (ops.vw_cobertura_atual entra no M2, quando existirem as tabelas Bronze)
-- =====================================================================

-- Tamanho de cada camada em MB. O % do limite (DB_LIMITE_MB) é calculado na consulta do dashboard.
CREATE OR REPLACE VIEW ops.vw_tamanho_schemas AS
SELECT n.nspname                                                   AS schema,
       count(c.oid)                                                AS tabelas,
       round(coalesce(sum(pg_total_relation_size(c.oid)), 0) / 1024.0 / 1024.0, 2) AS tamanho_mb
FROM pg_namespace n
LEFT JOIN pg_class c
       ON c.relnamespace = n.oid AND c.relkind IN ('r', 'm', 'p')
WHERE n.nspname IN ('bronze', 'silver', 'gold', 'ops')
GROUP BY n.nspname;

-- Tamanho total do banco do projeto em MB (base do alerta de 80% de DB_LIMITE_MB).
CREATE OR REPLACE VIEW ops.vw_tamanho_banco AS
SELECT current_database()                                        AS banco,
       round(pg_database_size(current_database()) / 1024.0 / 1024.0, 2) AS tamanho_mb;
