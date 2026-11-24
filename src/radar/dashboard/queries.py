"""Um dataset por arquivo JSON (SPEC V3 12.4). Cada consulta lê só `gold.mart_*` e views de `ops`."""

from __future__ import annotations

DATASETS: dict[str, str] = {
    "kpis_diarios": "SELECT * FROM gold.mart_kpis_diarios ORDER BY data",
    "proposicoes_tema_semana": "SELECT * FROM gold.mart_proposicoes_tema_semana ORDER BY inicio_semana, tema",
    "proposicoes_recentes": (
        "SELECT id_proposicao, sigla_tipo, numero, ano, data_apresentacao, ementa, tema_ia, tema_ia_score, "
        "tema_ia_segundo, temas_oficiais, resumo_executivo, nivel_impacto, setores_afetados, relevancia_score, "
        "situacao, orgao, regime, link_camara, em_pauta, dias_em_tramitacao "
        "FROM gold.mart_proposicoes_recentes ORDER BY relevancia_score DESC NULLS LAST, data_apresentacao DESC"
    ),
    "tramitacao_tema": "SELECT * FROM gold.mart_tramitacao_tema ORDER BY mediana_dias DESC",
    "setores": "SELECT * FROM gold.mart_setores ORDER BY qtd DESC",
    "lotes_autoria": "SELECT * FROM gold.mart_lotes_autoria ORDER BY data, qtd DESC",
    "projetos_partido": "SELECT sigla_partido, tema, id_deputado, nome, qtd FROM gold.mart_projetos_partido ORDER BY qtd DESC",
    "top_relevantes": "SELECT * FROM gold.mart_top_relevantes ORDER BY posicao",
    "partidos": "SELECT * FROM gold.mart_partidos ORDER BY deputados DESC",
    "similaridade_partidos": "SELECT * FROM gold.mart_similaridade_partidos ORDER BY partido_a, partido_b",
    "votacoes_dia": "SELECT * FROM gold.mart_votacoes_dia ORDER BY data",
    "deputados": "SELECT * FROM gold.mart_deputados ORDER BY score_atividade DESC, nome",
    "deputados_uf": "SELECT * FROM gold.mart_deputados_uf ORDER BY sigla_uf",
    # resumos prontos para a página (o mart detalhado passa de 1 MB com vários meses carregados)
    "despesas_mensal": (
        "SELECT ano, mes, sum(qtd)::int AS qtd, sum(valor_liquido) AS valor_liquido "
        "FROM gold.mart_despesas GROUP BY 1, 2 ORDER BY 1, 2"
    ),
    "despesas_tipo": (
        "SELECT tipo_despesa, sum(qtd)::int AS qtd, sum(valor_liquido) AS valor_liquido "
        "FROM gold.mart_despesas GROUP BY 1 ORDER BY 3 DESC"
    ),
    "fornecedores": "SELECT * FROM gold.mart_fornecedores ORDER BY valor DESC",
    "despesas_outliers": "SELECT * FROM gold.mart_despesas_outliers ORDER BY z_score DESC",
    "agenda": "SELECT * FROM gold.mart_agenda ORDER BY data, hora",
    "pauta_critica": "SELECT * FROM gold.mart_pauta_critica ORDER BY data, relevancia_score DESC",
    "articulacao": "SELECT * FROM gold.mart_articulacao ORDER BY membros DESC",
    "blocos_partidos": "SELECT * FROM gold.mart_blocos_partidos ORDER BY bloco, membros DESC",
    "liderancas": "SELECT * FROM gold.mart_liderancas ORDER BY tipo DESC, titulo, nome",
    "operacao": "SELECT * FROM gold.mart_operacao ORDER BY id_execucao",
    "cobertura": "SELECT * FROM gold.mart_cobertura ORDER BY grupo, endpoint",
    "funil_camadas": "SELECT * FROM gold.mart_funil_camadas ORDER BY bronze DESC",
    "qualidade": "SELECT * FROM gold.mart_qualidade ORDER BY data, entidade",
    "custos_ia": "SELECT * FROM gold.mart_custos_ia ORDER BY data",
    "tamanho_schemas": "SELECT * FROM ops.vw_tamanho_schemas ORDER BY tamanho_mb DESC",
}

# Busca semântica (bônus da SPEC 10.7): 5 vizinhas de cada proposição da tabela, pelo índice HNSW.
SIMILARES = """
SELECT r.id_proposicao, s.id_proposicao AS id, s.rotulo, s.ementa, round(s.sim::numeric, 3) AS similaridade
FROM gold.mart_proposicoes_recentes r
JOIN gold.proposicao_embeddings e ON e.id_proposicao = r.id_proposicao
CROSS JOIN LATERAL (
    SELECT o.id_proposicao, f.sigla_tipo || ' ' || f.numero || '/' || f.ano AS rotulo, left(f.ementa, 160) AS ementa,
           1 - (o.embedding OPERATOR(extensions.<=>) e.embedding) AS sim
    FROM gold.proposicao_embeddings o
    JOIN gold.fato_proposicao f ON f.id_proposicao = o.id_proposicao
    WHERE o.id_proposicao <> r.id_proposicao
    ORDER BY o.embedding OPERATOR(extensions.<=>) e.embedding
    LIMIT 5
) s
ORDER BY r.id_proposicao, s.sim DESC
"""

ULTIMA_EXECUCAO = """
SELECT id_execucao, modo, status, finalizado_em FROM ops.pipeline_execucoes
WHERE status IN ('success', 'partial') AND modo IN ('incremental', 'backfill')
ORDER BY finalizado_em DESC NULLS LAST LIMIT 1
"""
PERIODO = """
SELECT (SELECT data_ref FROM gold.vw_data_referencia) AS data_ref,
       (SELECT min(data) FROM gold.mart_kpis_diarios) AS inicio
"""
COBERTURA = "SELECT count(*) FILTER (WHERE status = 'ok') AS ok, count(*) AS total FROM ops.vw_cobertura_atual"
AVALIACAO = """
SELECT acuracia, cobertura, limiar, avaliadas, detalhes -> 'sem_vazamento' ->> 'acuracia_top1' AS acuracia_sem_vazamento,
       criado_em FROM ops.avaliacao_ia ORDER BY id DESC LIMIT 1
"""
CUSTO_IA = "SELECT coalesce(sum(custo_usd), 0) AS total, count(DISTINCT id_execucao) AS execucoes FROM ops.custos_ia"
TEMAS = "SELECT nome, cor_hex AS cor, critico FROM gold.dim_tema ORDER BY nome = 'Outros', nome"
