-- =====================================================================
-- gold/030_load_pontes.sql — carga das pontes a partir da Silver. Idempotente.
-- =====================================================================

INSERT INTO gold.ponte_proposicao_autor
SELECT id_proposicao, nome_autor, id_deputado, tipo_autor, ordem_assinatura, proponente
FROM silver.proposicoes_autores
ON CONFLICT (id_proposicao, nome_autor) DO UPDATE SET
    id_deputado = EXCLUDED.id_deputado, tipo_autor = EXCLUDED.tipo_autor,
    ordem_assinatura = EXCLUDED.ordem_assinatura, proponente = EXCLUDED.proponente;

-- Frentes: a relação conformada (deputados_frentes) + título/datas vindos de frentes_membros.
INSERT INTO gold.ponte_frente_membro
SELECT df.id_frente, df.id_deputado, fm.titulo, fm.data_inicio, fm.data_fim
FROM silver.deputados_frentes df
LEFT JOIN LATERAL (
    SELECT titulo, data_inicio, data_fim FROM silver.frentes_membros m
    WHERE m.id_frente = df.id_frente AND m.id_deputado = df.id_deputado
    ORDER BY m.data_inicio DESC NULLS LAST LIMIT 1
) fm ON true
ON CONFLICT (id_frente, id_deputado) DO UPDATE SET
    titulo = EXCLUDED.titulo, data_inicio = EXCLUDED.data_inicio, data_fim = EXCLUDED.data_fim;

INSERT INTO gold.ponte_orgao_membro
SELECT id_orgao, id_deputado, cod_titulo, titulo, data_inicio, data_fim
FROM silver.orgaos_membros
ON CONFLICT (id_orgao, id_deputado, cod_titulo, data_inicio) DO UPDATE SET
    titulo = EXCLUDED.titulo, data_fim = EXCLUDED.data_fim;

INSERT INTO gold.ponte_bloco_partido
SELECT id_bloco, id_partido, sigla_partido FROM silver.blocos_partidos
ON CONFLICT (id_bloco, id_partido) DO UPDATE SET sigla_partido = EXCLUDED.sigla_partido;
