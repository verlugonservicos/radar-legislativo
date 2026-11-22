-- =====================================================================
-- ops/004_views_cobertura.sql — cobertura dos endpoints na Bronze (SPEC V3, seção 7)
-- Executado pelo `db init` depois da criação das tabelas Bronze e da
-- sincronização de ops.catalogo_endpoints.
-- =====================================================================

-- Para cada endpoint ativo do catálogo: última execução com dados, linhas na Bronze
-- (estimativa do planejador, sem varrer as tabelas) e status.
CREATE OR REPLACE VIEW ops.vw_cobertura_atual AS
WITH ultima AS (
    SELECT DISTINCT ON (endpoint)
           endpoint, id_execucao, registros, inseridos, erros, observacao
    FROM ops.cobertura_endpoints
    ORDER BY endpoint, (registros > 0) DESC, id_execucao DESC
)
SELECT c.endpoint,
       c.grupo,
       c.path,
       c.frequencia,
       u.id_execucao                               AS ultima_execucao,
       COALESCE(u.registros, 0)                    AS registros_ultima,
       COALESCE(u.erros, 0)                        AS erros_ultima,
       GREATEST(COALESCE(t.reltuples, 0), 0)::bigint AS linhas_bronze_estimadas,
       u.observacao,
       CASE
           WHEN COALESCE(u.registros, 0) > 0 OR COALESCE(t.reltuples, 0) > 0 THEN 'ok'
           WHEN u.observacao IS NOT NULL                                   THEN 'vazio_justificado'
           ELSE 'sem_dados'
       END                                         AS status
FROM ops.catalogo_endpoints c
LEFT JOIN ultima u ON u.endpoint = c.endpoint
LEFT JOIN pg_class t
       ON t.relname = c.endpoint
      AND t.relnamespace = 'bronze'::regnamespace
      AND t.relkind = 'r'
WHERE NOT c.obsoleto;
