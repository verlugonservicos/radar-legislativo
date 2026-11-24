-- =====================================================================
-- gold/100_marts.sql — marts dos dashboards (SPEC V3 9.6). Executado DEPOIS da IA.
--
-- Cada mart é uma materialized view com índice único. O arquivo inteiro roda numa transação:
-- derruba e recria as views (a definição nunca fica defasada do código) e os leitores só veem a
-- troca no COMMIT. Desvio consciente do REFRESH CONCURRENTLY da SPEC (ADR-027).
--
-- Janelas relativas à data de referência (gold.vw_data_referencia): o dado mais recente
-- (proposição, votação ou evento), limitado a hoje. Com a carga diária ela é "hoje"; numa base
-- parada há alguns dias, os painéis continuam mostrando a última semana com dados.
-- =====================================================================

DROP VIEW IF EXISTS gold.mart_alertas_pendentes;
DROP MATERIALIZED VIEW IF EXISTS
    gold.mart_kpis_diarios, gold.mart_proposicoes_tema_semana, gold.mart_proposicoes_recentes,
    gold.mart_tramitacao_tema, gold.mart_partidos, gold.mart_similaridade_partidos,
    gold.mart_votacoes_dia, gold.mart_deputados, gold.mart_deputados_uf, gold.mart_despesas,
    gold.mart_fornecedores, gold.mart_despesas_outliers, gold.mart_agenda, gold.mart_pauta_critica,
    gold.mart_articulacao, gold.mart_blocos_partidos, gold.mart_liderancas, gold.mart_top_relevantes,
    gold.mart_operacao, gold.mart_cobertura, gold.mart_qualidade, gold.mart_custos_ia,
    gold.mart_funil_camadas, gold.mart_setores, gold.mart_projetos_partido
    CASCADE;

-- ------------------------------------------------------------------ data de referência
CREATE OR REPLACE VIEW gold.vw_data_referencia AS
SELECT least(current_date, greatest(
           (SELECT max(data) FROM gold.fato_votacao WHERE data <= current_date),
           (SELECT max(data) FROM gold.fato_evento WHERE data <= current_date),
           (SELECT max(data_apresentacao) FROM gold.fato_proposicao WHERE data_apresentacao <= current_date)
       )) AS data_ref;

-- ------------------------------------------------------------------ Visão Executiva
-- Um dia por linha nos últimos 90 dias (dias sem atividade aparecem com zero).
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_kpis_diarios AS
WITH dias AS (
    SELECT t.data FROM gold.dim_tempo t, gold.vw_data_referencia r
    WHERE t.data BETWEEN r.data_ref - 89 AND r.data_ref
),
prop AS (
    SELECT p.data_apresentacao AS data, count(*) AS proposicoes,
           count(*) FILTER (WHERE p.relevancia_score >= 0.5) AS proposicoes_relevantes
    FROM gold.fato_proposicao p GROUP BY 1
),
vot AS (
    SELECT data, count(*) AS votacoes, count(*) FILTER (WHERE aprovacao = 1) AS votacoes_aprovadas
    FROM gold.fato_votacao GROUP BY 1
),
eve AS (SELECT data, count(*) AS eventos FROM gold.fato_evento GROUP BY 1),
dis AS (SELECT data, count(*) AS discursos FROM gold.fato_discurso GROUP BY 1),
des AS (SELECT data_documento AS data, sum(valor_liquido) AS valor_despesas FROM gold.fato_despesa GROUP BY 1),
ale AS (SELECT enviado_em::date AS data, count(*) AS alertas_enviados FROM ops.alertas_enviados GROUP BY 1)
SELECT d.data,
       coalesce(prop.proposicoes, 0)::int AS proposicoes,
       coalesce(prop.proposicoes_relevantes, 0)::int AS proposicoes_relevantes,
       coalesce(vot.votacoes, 0)::int AS votacoes,
       coalesce(vot.votacoes_aprovadas, 0)::int AS votacoes_aprovadas,
       coalesce(eve.eventos, 0)::int AS eventos,
       coalesce(dis.discursos, 0)::int AS discursos,
       coalesce(des.valor_despesas, 0)::numeric(14,2) AS valor_despesas,
       coalesce(ale.alertas_enviados, 0)::int AS alertas_enviados
FROM dias d
LEFT JOIN prop USING (data) LEFT JOIN vot USING (data) LEFT JOIN eve USING (data)
LEFT JOIN dis USING (data) LEFT JOIN des USING (data) LEFT JOIN ale USING (data);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_kpis_diarios ON gold.mart_kpis_diarios (data);

-- Proposições relevantes por tema e semana (últimas 26 semanas)
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_proposicoes_tema_semana AS
SELECT t.inicio_semana, coalesce(p.tema_ia, 'Outros') AS tema, p.sigla_tipo, count(*)::int AS qtd
FROM gold.fato_proposicao p
JOIN gold.dim_tempo t ON t.data = p.data_apresentacao
CROSS JOIN gold.vw_data_referencia r
WHERE p.tema_ia IS NOT NULL AND p.data_apresentacao BETWEEN r.data_ref - 181 AND r.data_ref
GROUP BY 1, 2, 3;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_prop_tema_semana ON gold.mart_proposicoes_tema_semana (inicio_semana, tema, sigla_tipo);

-- Tabela de proposições: relevantes apresentadas nos últimos 90 dias ou em pauta
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_proposicoes_recentes AS
SELECT p.id_proposicao, p.sigla_tipo, p.numero, p.ano, p.data_apresentacao, p.ementa,
       p.tema_ia, p.tema_ia_score, p.tema_ia_segundo, p.temas_oficiais, p.resumo_executivo,
       p.nivel_impacto, p.setores_afetados, p.relevancia_score, p.situacao,
       coalesce(o.sigla, sp.orgao_situacao) AS orgao,          -- dim_orgao só tem os órgãos atuais
       p.regime, p.link_camara, p.em_pauta_proximos_7d AS em_pauta, p.qtd_autores,
       p.dias_em_tramitacao, p.data_ultima_tramitacao
FROM gold.fato_proposicao p
LEFT JOIN gold.dim_orgao o ON o.id_orgao = p.id_orgao_situacao
LEFT JOIN silver.proposicoes sp ON sp.id_proposicao = p.id_proposicao
CROSS JOIN gold.vw_data_referencia r
WHERE p.tema_ia IS NOT NULL
  AND (p.data_apresentacao BETWEEN r.data_ref - 89 AND r.data_ref OR p.em_pauta_proximos_7d);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_prop_recentes ON gold.mart_proposicoes_recentes (id_proposicao);

-- Tempo de tramitação por tema (proposições relevantes classificadas)
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_tramitacao_tema AS
SELECT p.tema_ia AS tema, count(*)::int AS qtd,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY p.dias_em_tramitacao)::int AS mediana_dias,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY p.dias_em_tramitacao)::int AS p90_dias,
       round(100.0 * avg(p.em_pauta_proximos_7d::int), 1) AS pct_em_pauta
FROM gold.fato_proposicao p
WHERE p.tema_ia IS NOT NULL AND p.dias_em_tramitacao IS NOT NULL
GROUP BY 1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_tramitacao_tema ON gold.mart_tramitacao_tema (tema);

-- Setores mais citados nos resumos da IA (extra ao M5: gráfico de setores)
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_setores AS
SELECT s.setor, coalesce(p.tema_ia, 'Outros') AS tema, count(*)::int AS qtd,
       count(*) FILTER (WHERE p.nivel_impacto = 'alto')::int AS qtd_alto
FROM gold.fato_proposicao p, unnest(p.setores_afetados) AS s(setor)
GROUP BY 1, 2;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_setores ON gold.mart_setores (setor, tema);

-- Projetos apresentados (últimas 26 semanas) por partido × tema × deputado: o painel soma por partido
-- respeitando o filtro de tema e acha o maior autor. Mesmo critério de mart_partidos.projetos: só o
-- autor principal (1º signatário) e só PL, PLP, PEC e PDL; partido atual do deputado.
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_projetos_partido AS
SELECT d.sigla_partido, coalesce(p.tema_ia, 'Outros') AS tema, d.id_deputado, d.nome,
       count(DISTINCT a.id_proposicao)::int AS qtd
FROM gold.ponte_proposicao_autor a
JOIN gold.dim_deputado d ON d.id_deputado = a.id_deputado AND d.atual
JOIN gold.fato_proposicao p USING (id_proposicao)
CROSS JOIN gold.vw_data_referencia r
WHERE a.ordem_assinatura = 1 AND p.sigla_tipo IN ('PL', 'PLP', 'PEC', 'PDL')
  AND p.data_apresentacao > r.data_ref - 182 AND d.sigla_partido IS NOT NULL
GROUP BY 1, 2, 3, 4;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_projetos_partido ON gold.mart_projetos_partido (sigla_partido, tema, id_deputado);

-- Top 5 dos últimos 7 dias por relevância
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_top_relevantes AS
SELECT p.id_proposicao, p.sigla_tipo, p.numero, p.ano, p.data_apresentacao, p.tema_ia,
       p.nivel_impacto, p.relevancia_score, p.resumo_executivo, p.ementa, p.link_camara,
       row_number() OVER (ORDER BY p.relevancia_score DESC NULLS LAST, p.data_apresentacao DESC, p.id_proposicao)::int AS posicao
FROM gold.fato_proposicao p CROSS JOIN gold.vw_data_referencia r
WHERE p.resumo_executivo IS NOT NULL AND p.data_apresentacao BETWEEN r.data_ref - 6 AND r.data_ref
ORDER BY posicao
LIMIT 5;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_top_relevantes ON gold.mart_top_relevantes (id_proposicao);

-- ------------------------------------------------------------------ Votações & Partidos
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_votacoes_dia AS
SELECT v.data, count(*)::int AS total,
       count(*) FILTER (WHERE v.aprovacao = 1)::int AS aprovadas,
       count(*) FILTER (WHERE v.aprovacao = 0)::int AS rejeitadas,
       count(*) FILTER (WHERE v.nominal)::int AS nominais
FROM gold.fato_votacao v CROSS JOIN gold.vw_data_referencia r
WHERE v.data BETWEEN r.data_ref - 89 AND r.data_ref
GROUP BY 1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_votacoes_dia ON gold.mart_votacoes_dia (data);

-- Indicadores por partido (deputados em exercício). Participação = média, entre os deputados em
-- exercício do partido, da presença nas votações nominais do Plenário; fidelidade e governismo usam
-- todos os votos registrados com a sigla do momento (inclui comissões).
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_partidos AS
WITH dep AS (
    SELECT sigla_partido, count(*) AS deputados FROM silver.deputados
    WHERE situacao = 'Exercício' AND sigla_partido IS NOT NULL GROUP BY 1
),
nominais AS (SELECT count(*) AS n FROM gold.fato_votacao WHERE nominal AND sigla_orgao = 'PLEN'),
plenario AS (                         -- presença: votos nas votações nominais do Plenário
    SELECT v.id_deputado, v.sigla_partido FROM gold.fato_voto v
    JOIN gold.fato_votacao f USING (id_votacao) WHERE f.sigla_orgao = 'PLEN'
),
votos AS (
    SELECT sigla_partido, count(*) AS votos,
           round(100.0 * avg(seguiu_partido::int), 1) AS fidelidade_pct,
           round(100.0 * avg(seguiu_governo::int), 1) AS governismo_pct
    FROM gold.fato_voto GROUP BY 1
),
autorias AS (
    SELECT d.sigla_partido, count(DISTINCT a.id_proposicao) AS autorias
    FROM gold.ponte_proposicao_autor a JOIN gold.dim_deputado d ON d.id_deputado = a.id_deputado AND d.atual
    GROUP BY 1
),
-- projetos apresentados nas últimas 26 semanas: só o autor principal (1º signatário, sem dupla contagem
-- de coautorias) e só PL, PLP, PEC e PDL (requerimentos e indicações ficam de fora)
projetos_dep AS (
    SELECT d.sigla_partido, d.nome, count(DISTINCT a.id_proposicao) AS qtd
    FROM gold.ponte_proposicao_autor a
    JOIN gold.dim_deputado d ON d.id_deputado = a.id_deputado AND d.atual
    JOIN gold.fato_proposicao p USING (id_proposicao)
    CROSS JOIN gold.vw_data_referencia r
    WHERE a.ordem_assinatura = 1 AND p.sigla_tipo IN ('PL', 'PLP', 'PEC', 'PDL')
      AND p.data_apresentacao > r.data_ref - 182
    GROUP BY 1, 2
),
projetos AS (
    SELECT sigla_partido, sum(qtd) AS projetos,
           (array_agg(nome ORDER BY qtd DESC, nome))[1] AS projetos_maior_autor,
           max(qtd) AS projetos_maior_autor_qtd
    FROM projetos_dep GROUP BY 1
),
discursos AS (SELECT sigla_partido, count(*) AS discursos FROM gold.fato_discurso GROUP BY 1),
gastos AS (SELECT sigla_partido, sum(valor_liquido) AS gasto_total FROM gold.fato_despesa GROUP BY 1),
presenca AS (                         -- média da presença de cada deputado em exercício (partido atual)
    SELECT d.sigla_partido,
           round(avg(100.0 * (SELECT count(*) FROM plenario pl WHERE pl.id_deputado = d.id_deputado)
                     / nullif((SELECT n FROM nominais), 0)), 1) AS participacao_pct
    FROM silver.deputados d WHERE d.situacao = 'Exercício' GROUP BY 1
)
SELECT dep.sigla_partido, dep.deputados::int,
       coalesce(votos.votos, 0)::int AS votos,
       presenca.participacao_pct,
       votos.fidelidade_pct, votos.governismo_pct,
       coalesce(autorias.autorias, 0)::int AS autorias,
       coalesce(projetos.projetos, 0)::int AS projetos,
       projetos.projetos_maior_autor, coalesce(projetos.projetos_maior_autor_qtd, 0)::int AS projetos_maior_autor_qtd,
       coalesce(discursos.discursos, 0)::int AS discursos,
       coalesce(gastos.gasto_total, 0)::numeric(14,2) AS gasto_total,
       round(coalesce(gastos.gasto_total, 0) / dep.deputados, 2) AS gasto_por_deputado
FROM dep CROSS JOIN nominais n
LEFT JOIN votos USING (sigla_partido) LEFT JOIN autorias USING (sigla_partido)
LEFT JOIN projetos USING (sigla_partido)
LEFT JOIN discursos USING (sigla_partido) LEFT JOIN gastos USING (sigla_partido)
LEFT JOIN presenca USING (sigla_partido);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_partidos ON gold.mart_partidos (sigla_partido);

-- Concordância entre partidos: voto majoritário (Sim/Não) de cada partido por votação
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_similaridade_partidos AS
WITH majoritario AS (                 -- partido × votação → voto mais frequente entre Sim/Não
    SELECT id_votacao, sigla_partido, mode() WITHIN GROUP (ORDER BY tipo_voto) AS voto
    FROM gold.fato_voto
    WHERE tipo_voto IN ('Sim', 'Não') AND sigla_partido IS NOT NULL
    GROUP BY 1, 2
),
grandes AS (                          -- só partidos com pelo menos 5 deputados em exercício
    SELECT sigla_partido FROM silver.deputados
    WHERE situacao = 'Exercício' GROUP BY 1 HAVING count(*) >= 5
)
SELECT a.sigla_partido AS partido_a, b.sigla_partido AS partido_b,
       count(*)::int AS votacoes_comuns,
       round(100.0 * avg((a.voto = b.voto)::int), 1) AS concordancia_pct
FROM majoritario a
JOIN majoritario b ON b.id_votacao = a.id_votacao
WHERE a.sigla_partido IN (SELECT sigla_partido FROM grandes)
  AND b.sigla_partido IN (SELECT sigla_partido FROM grandes)
GROUP BY 1, 2;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_similaridade ON gold.mart_similaridade_partidos (partido_a, partido_b);

-- ------------------------------------------------------------------ Deputados
-- score_atividade (0–100): média dos percentis de autorias, presença em votações, presenças em
-- eventos e discursos entre os deputados em exercício (ADR-027).
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_deputados AS
WITH dep AS (
    SELECT id_deputado, nome, sigla_partido, sigla_uf, url_foto, sexo
    FROM silver.deputados WHERE situacao = 'Exercício'
),
nominais AS (SELECT count(*) AS n FROM gold.fato_votacao WHERE nominal AND sigla_orgao = 'PLEN'),
plenario AS (                         -- presença: votos nas votações nominais do Plenário
    SELECT v.id_deputado, v.sigla_partido FROM gold.fato_voto v
    JOIN gold.fato_votacao f USING (id_votacao) WHERE f.sigla_orgao = 'PLEN'
),
votos AS (
    SELECT id_deputado, count(*) AS votos,
           round(100.0 * avg(seguiu_partido::int), 1) AS fidelidade_pct,
           round(100.0 * avg(seguiu_governo::int), 1) AS governismo_pct
    FROM gold.fato_voto GROUP BY 1
),
autorias AS (SELECT id_deputado, count(DISTINCT id_proposicao) AS autorias FROM gold.ponte_proposicao_autor WHERE id_deputado IS NOT NULL GROUP BY 1),
presencas AS (SELECT id_deputado, count(*) AS presencas_eventos FROM gold.fato_presenca_evento GROUP BY 1),
discursos AS (SELECT id_deputado, count(*) AS discursos FROM gold.fato_discurso GROUP BY 1),
gastos AS (SELECT id_deputado, sum(valor_liquido) AS gasto_total FROM gold.fato_despesa GROUP BY 1),
frentes AS (SELECT id_deputado, count(DISTINCT id_frente) AS qtd_frentes FROM gold.ponte_frente_membro GROUP BY 1),
orgaos AS (SELECT id_deputado, count(DISTINCT id_orgao) AS qtd_orgaos FROM gold.ponte_orgao_membro WHERE data_fim IS NULL OR data_fim >= current_date GROUP BY 1),
base AS (
    SELECT dep.*, coalesce(autorias.autorias, 0) AS autorias, coalesce(votos.votos, 0) AS votos,
           CASE WHEN n.n > 0 THEN round(100.0 * (SELECT count(*) FROM plenario pl WHERE pl.id_deputado = dep.id_deputado)
                                        / n.n, 1) END AS presenca_votacoes_pct,
           coalesce(presencas.presencas_eventos, 0) AS presencas_eventos,
           coalesce(discursos.discursos, 0) AS discursos,
           votos.fidelidade_pct, votos.governismo_pct,
           coalesce(gastos.gasto_total, 0)::numeric(14,2) AS gasto_total,
           coalesce(frentes.qtd_frentes, 0) AS qtd_frentes, coalesce(orgaos.qtd_orgaos, 0) AS qtd_orgaos
    FROM dep CROSS JOIN nominais n
    LEFT JOIN votos USING (id_deputado) LEFT JOIN autorias USING (id_deputado)
    LEFT JOIN presencas USING (id_deputado) LEFT JOIN discursos USING (id_deputado)
    LEFT JOIN gastos USING (id_deputado) LEFT JOIN frentes USING (id_deputado)
    LEFT JOIN orgaos USING (id_deputado)
)
SELECT b.id_deputado, b.nome, b.sigla_partido, b.sigla_uf, b.url_foto, b.sexo,
       b.autorias::int, b.votos::int, b.presenca_votacoes_pct, b.presencas_eventos::int, b.discursos::int,
       b.fidelidade_pct, b.governismo_pct, b.gasto_total, b.qtd_frentes::int, b.qtd_orgaos::int,
       round(100 * (percent_rank() OVER (ORDER BY b.autorias)
                    + percent_rank() OVER (ORDER BY coalesce(b.presenca_votacoes_pct, 0))
                    + percent_rank() OVER (ORDER BY b.presencas_eventos)
                    + percent_rank() OVER (ORDER BY b.discursos))::numeric / 4, 1) AS score_atividade
FROM base b;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_deputados ON gold.mart_deputados (id_deputado);

CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_deputados_uf AS
SELECT sigla_uf, count(*)::int AS deputados, sum(gasto_total)::numeric(14,2) AS gasto_total,
       round(sum(gasto_total) / count(*), 2) AS gasto_por_deputado,
       sum(autorias)::int AS autorias, round(avg(score_atividade), 1) AS score_atividade_medio,
       round(avg(presenca_votacoes_pct), 1) AS presenca_votacoes_media
FROM gold.mart_deputados
WHERE sigla_uf IS NOT NULL
GROUP BY 1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_deputados_uf ON gold.mart_deputados_uf (sigla_uf);

-- ------------------------------------------------------------------ Despesas
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_despesas AS
SELECT ano, mes, coalesce(sigla_partido, '—') AS sigla_partido, coalesce(sigla_uf, '—') AS sigla_uf,
       coalesce(tipo_despesa, 'Não informado') AS tipo_despesa,
       count(*)::int AS qtd, sum(valor_liquido)::numeric(14,2) AS valor_liquido
FROM gold.fato_despesa
GROUP BY 1, 2, 3, 4, 5;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_despesas ON gold.mart_despesas (ano, mes, sigla_partido, sigla_uf, tipo_despesa);

CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_fornecedores AS
SELECT cnpj_cpf_fornecedor, max(nome_fornecedor) AS nome, sum(valor_liquido)::numeric(14,2) AS valor,
       count(*)::int AS qtd, count(DISTINCT id_deputado)::int AS deputados
FROM gold.fato_despesa
WHERE cnpj_cpf_fornecedor IS NOT NULL AND length(cnpj_cpf_fornecedor) = 14   -- só CNPJ (sem CPF de pessoa física)
GROUP BY 1
ORDER BY valor DESC
LIMIT 100;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_fornecedores ON gold.mart_fornecedores (cnpj_cpf_fornecedor);

-- Gasto de um deputado num tipo de despesa muito acima dos demais (z-score > 2 dentro do tipo)
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_despesas_outliers AS
WITH por_dep AS (
    SELECT id_deputado, tipo_despesa, sum(valor_liquido) AS total
    FROM gold.fato_despesa WHERE tipo_despesa IS NOT NULL GROUP BY 1, 2
),
z AS (
    SELECT *, (total - avg(total) OVER w) / nullif(stddev_pop(total) OVER w, 0) AS z_score,
           count(*) OVER w AS n
    FROM por_dep WINDOW w AS (PARTITION BY tipo_despesa)
)
SELECT z.id_deputado, d.nome, d.sigla_partido, d.sigla_uf, z.tipo_despesa,
       z.total::numeric(14,2) AS total, round(z.z_score::numeric, 2) AS z_score
FROM z LEFT JOIN silver.deputados d USING (id_deputado)
WHERE z.z_score > 2 AND z.n >= 10;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_despesas_outliers ON gold.mart_despesas_outliers (id_deputado, tipo_despesa);

-- ------------------------------------------------------------------ Agenda & Órgãos
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_agenda AS
SELECT e.id_evento, e.data, to_char(e.data_hora_inicio AT TIME ZONE 'America/Sao_Paulo', 'HH24:MI') AS hora,
       e.sigla_orgao AS orgao, o.nome AS orgao_nome, e.tipo_evento AS tipo, e.situacao, e.descricao,
       e.local, coalesce(e.qtd_itens_pauta, 0) AS itens_pauta, coalesce(e.qtd_itens_criticos, 0) AS itens_criticos,
       coalesce(e.qtd_presentes, 0) AS presentes, e.url_registro
FROM gold.fato_evento e
LEFT JOIN gold.dim_orgao o ON o.id_orgao = e.id_orgao_principal
CROSS JOIN gold.vw_data_referencia r
WHERE e.data BETWEEN r.data_ref - 30 AND r.data_ref + 7;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_agenda ON gold.mart_agenda (id_evento);

-- Itens de pauta com tema crítico nos próximos 7 dias
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_pauta_critica AS
SELECT DISTINCT ON (pi.id_evento, pi.id_proposicao)
       pi.id_evento, pi.id_proposicao, pi.data, e.sigla_orgao AS orgao,
       p.sigla_tipo || ' ' || p.numero || '/' || p.ano AS proposicao, p.tema_ia AS tema,
       p.resumo_executivo AS resumo, p.relevancia_score, p.link_camara
FROM gold.fato_pauta_item pi
JOIN gold.fato_proposicao p ON p.id_proposicao = pi.id_proposicao
JOIN gold.dim_tema t ON t.nome = p.tema_ia AND t.critico
LEFT JOIN gold.fato_evento e ON e.id_evento = pi.id_evento
CROSS JOIN gold.vw_data_referencia r
WHERE pi.id_proposicao > 0 AND pi.data BETWEEN r.data_ref AND r.data_ref + 7
ORDER BY pi.id_evento, pi.id_proposicao, pi.ordem;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_pauta_critica ON gold.mart_pauta_critica (id_evento, id_proposicao);

-- ------------------------------------------------------------------ Articulação Política
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_articulacao AS
WITH membros AS (
    SELECT m.id_frente, m.id_deputado, d.sigla_partido
    FROM gold.ponte_frente_membro m
    JOIN silver.deputados d ON d.id_deputado = m.id_deputado AND d.situacao = 'Exercício'
),
top AS (
    SELECT DISTINCT ON (id_frente) id_frente, sigla_partido AS top_partido, count(*) AS qtd_top
    FROM membros WHERE sigla_partido IS NOT NULL
    GROUP BY id_frente, sigla_partido ORDER BY id_frente, count(*) DESC, sigla_partido
)
SELECT f.id_frente, f.titulo, count(m.id_deputado)::int AS membros,
       count(DISTINCT m.sigla_partido)::int AS partidos_distintos,
       c.nome AS coordenador, top.top_partido
FROM gold.dim_frente f
JOIN membros m ON m.id_frente = f.id_frente
LEFT JOIN silver.deputados c ON c.id_deputado = f.id_coordenador
LEFT JOIN top ON top.id_frente = f.id_frente
GROUP BY f.id_frente, f.titulo, c.nome, top.top_partido;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_articulacao ON gold.mart_articulacao (id_frente);

CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_blocos_partidos AS
SELECT b.nome AS bloco, pb.sigla_partido AS partido, coalesce(count(d.id_deputado), 0)::int AS membros
FROM gold.ponte_bloco_partido pb
JOIN gold.dim_bloco b ON b.id_bloco = pb.id_bloco
LEFT JOIN silver.deputados d ON d.sigla_partido = pb.sigla_partido AND d.situacao = 'Exercício'
GROUP BY 1, 2;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_blocos_partidos ON gold.mart_blocos_partidos (bloco, partido);

-- Líderes e Mesa Diretora vigentes (legislatura atual)
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_liderancas AS
WITH leg AS (SELECT max(id_legislatura) AS id FROM silver.legislaturas_mesa)
SELECT 'Mesa Diretora' AS tipo, m.titulo, m.id_deputado, m.nome, m.sigla_partido, m.sigla_uf,
       NULL::text AS bancada, m.data_inicio, d.url_foto
FROM silver.legislaturas_mesa m
JOIN leg ON m.id_legislatura = leg.id
LEFT JOIN silver.deputados d USING (id_deputado)
WHERE m.data_fim IS NULL OR m.data_fim >= current_date
UNION ALL
SELECT 'Liderança', l.titulo, l.id_deputado, l.nome, l.sigla_partido, l.sigla_uf,
       l.bancada_nome, l.data_inicio, d.url_foto
FROM silver.legislaturas_lideres l
JOIN leg ON l.id_legislatura = leg.id
LEFT JOIN silver.deputados d USING (id_deputado)
WHERE (l.data_fim IS NULL OR l.data_fim >= current_date) AND l.titulo IN ('Líder', 'Líder do Governo', 'Líder da Oposição', 'Líder da Maioria', 'Líder da Minoria');
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_liderancas ON gold.mart_liderancas (tipo, titulo, id_deputado, coalesce(bancada, ''));

-- ------------------------------------------------------------------ Operação & Qualidade
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_operacao AS
SELECT e.id_execucao, e.modo, e.origem, e.status, e.iniciado_em, e.finalizado_em,
       extract(epoch FROM e.finalizado_em - e.iniciado_em)::int AS duracao_s,
       (SELECT coalesce(sum(custo_usd), 0) FROM ops.custos_ia c WHERE c.id_execucao = e.id_execucao)::numeric(10,4) AS custo_ia_usd,
       (SELECT jsonb_object_agg(k, v -> 'duracao_s') FROM jsonb_each(coalesce(e.etapas, '{}')) AS x(k, v)
        WHERE jsonb_typeof(v) = 'object' AND v ? 'duracao_s') AS etapas_s,
       (SELECT count(*) FROM ops.cobertura_endpoints c WHERE c.id_execucao = e.id_execucao)::int AS endpoints,
       e.erro
FROM ops.pipeline_execucoes e
WHERE e.status <> 'running'
ORDER BY e.id_execucao DESC
LIMIT 60;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_operacao ON gold.mart_operacao (id_execucao);

CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_cobertura AS
SELECT endpoint, grupo, frequencia, linhas_bronze_estimadas AS linhas_bronze, ultima_execucao AS ultima_carga,
       registros_ultima, erros_ultima, status, observacao
FROM ops.vw_cobertura_atual;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_cobertura ON gold.mart_cobertura (endpoint);

-- Um registro rejeitado de novo em execuções seguintes conta uma vez (data da primeira rejeição).
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_qualidade AS
WITH unicos AS (
    SELECT DISTINCT ON (entidade, regra, coalesce(chave, id::text)) entidade, regra, criado_em, registro
    FROM ops.qualidade_rejeicoes
    ORDER BY entidade, regra, coalesce(chave, id::text), criado_em
)
SELECT criado_em::date AS data, entidade, regra, count(*)::int AS qtd,
       sum(CASE WHEN registro ? 'valor_documento' THEN (registro ->> 'valor_documento')::numeric END)::numeric(14,2) AS valor
FROM unicos
GROUP BY 1, 2, 3;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_qualidade ON gold.mart_qualidade (data, entidade, regra);

CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_custos_ia AS
SELECT criado_em::date AS data, operacao, modelo, sum(itens)::int AS itens,
       sum(tokens_entrada)::bigint AS tokens_entrada, sum(tokens_saida)::bigint AS tokens_saida,
       sum(custo_usd)::numeric(10,4) AS custo_usd
FROM ops.custos_ia
GROUP BY 1, 2, 3;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_custos_ia ON gold.mart_custos_ia (data, operacao, modelo);

-- Funil Bronze → Silver → Gold das entidades principais (contagens exatas)
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.mart_funil_camadas AS
SELECT 'proposições' AS entidade,
       (SELECT count(*) FROM bronze.proposicoes)::int AS bronze,
       (SELECT count(*) FROM silver.proposicoes)::int AS silver,
       (SELECT count(*) FROM gold.fato_proposicao)::int AS gold,
       (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'proposicoes')::int AS rejeitados
UNION ALL SELECT 'votações', (SELECT count(*) FROM bronze.votacoes), (SELECT count(*) FROM silver.votacoes),
       (SELECT count(*) FROM gold.fato_votacao), (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'votacoes')
UNION ALL SELECT 'votos', (SELECT count(*) FROM bronze.votacoes_votos), (SELECT count(*) FROM silver.votos),
       (SELECT count(*) FROM gold.fato_voto), (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'votos')
UNION ALL SELECT 'despesas', (SELECT count(*) FROM bronze.deputados_despesas), (SELECT count(*) FROM silver.despesas),
       (SELECT count(*) FROM gold.fato_despesa), (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'despesas')
UNION ALL SELECT 'tramitações', (SELECT count(*) FROM bronze.proposicoes_tramitacoes), (SELECT count(*) FROM silver.proposicoes_tramitacoes),
       (SELECT count(*) FROM gold.fato_tramitacao), (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'proposicoes_tramitacoes')
UNION ALL SELECT 'eventos', (SELECT count(*) FROM bronze.eventos), (SELECT count(*) FROM silver.eventos),
       (SELECT count(*) FROM gold.fato_evento), (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'eventos')
UNION ALL SELECT 'discursos', (SELECT count(*) FROM bronze.deputados_discursos), (SELECT count(*) FROM silver.discursos),
       (SELECT count(*) FROM gold.fato_discurso), (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'discursos')
UNION ALL SELECT 'deputados', (SELECT count(*) FROM bronze.deputados_detalhe), (SELECT count(*) FROM silver.deputados),
       (SELECT count(DISTINCT id_deputado) FROM gold.dim_deputado), (SELECT count(*) FROM ops.qualidade_rejeicoes WHERE entidade = 'deputados');
CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_funil ON gold.mart_funil_camadas (entidade);

-- ------------------------------------------------------------------ alertas (view comum)
-- Tema crítico, relevância ≥ 0,50, apresentada nos últimos 3 dias ou em pauta nos próximos 7,
-- ainda sem alerta no Telegram (WF02 no M6).
CREATE OR REPLACE VIEW gold.mart_alertas_pendentes AS
SELECT p.id_proposicao, p.sigla_tipo, p.numero, p.ano, p.tema_ia, p.nivel_impacto,
       p.relevancia_score, p.resumo_executivo, p.link_camara, p.em_pauta_proximos_7d
FROM gold.fato_proposicao p
JOIN gold.dim_tema t ON t.nome = p.tema_ia AND t.critico
CROSS JOIN gold.vw_data_referencia r
WHERE p.relevancia_score >= 0.50
  AND (p.data_apresentacao >= r.data_ref - 2 OR p.em_pauta_proximos_7d)
  AND NOT EXISTS (SELECT 1 FROM ops.alertas_enviados a
                  WHERE a.id_proposicao = p.id_proposicao AND a.canal = 'telegram');
