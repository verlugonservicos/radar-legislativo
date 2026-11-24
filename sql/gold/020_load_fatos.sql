-- =====================================================================
-- gold/020_load_fatos.sql — carga dos fatos a partir da Silver (SPEC V3, seção 9.4).
-- Idempotente (UPSERT). Colunas de IA de fato_proposicao nunca são tocadas aqui.
-- =====================================================================

-- Versão do deputado vigente num instante (fallback: a versão mais antiga).
CREATE OR REPLACE FUNCTION gold.sk_deputado_em(p_id INTEGER, p_ts TIMESTAMPTZ)
RETURNS BIGINT LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        (SELECT sk_deputado FROM gold.dim_deputado
         WHERE id_deputado = p_id AND valido_de <= p_ts AND p_ts < coalesce(valido_ate, 'infinity')
         ORDER BY valido_de DESC LIMIT 1),
        (SELECT sk_deputado FROM gold.dim_deputado
         WHERE id_deputado = p_id ORDER BY valido_de LIMIT 1))
$$;

-- ---------------------------------------------------------------- fato_proposicao
WITH tram AS (
    SELECT id_proposicao, count(*) AS qtd,
           (array_agg(despacho ORDER BY sequencia DESC))[1] AS ultimo_despacho,
           (array_agg(id_orgao ORDER BY sequencia DESC))[1] AS id_orgao,
           max(data_hora) AS ultima
    FROM silver.proposicoes_tramitacoes GROUP BY id_proposicao
),
autores AS (SELECT id_proposicao, count(*) AS qtd FROM silver.proposicoes_autores GROUP BY id_proposicao),
temas AS (
    SELECT id_proposicao, array_agg(tema ORDER BY relevancia DESC NULLS LAST, tema) AS temas
    FROM silver.proposicoes_temas WHERE tema IS NOT NULL GROUP BY id_proposicao
),
pauta AS (
    SELECT DISTINCT p.id_proposicao
    FROM silver.eventos_pauta p JOIN silver.eventos e USING (id_evento)
    WHERE p.id_proposicao > 0 AND e.data_hora_inicio BETWEEN now() AND now() + interval '7 days'
)
INSERT INTO gold.fato_proposicao (
    id_proposicao, sigla_tipo, numero, ano, ementa, ementa_detalhada, keywords, data_apresentacao,
    situacao, cod_situacao, id_orgao_situacao, regime, apreciacao, ultimo_despacho,
    data_ultima_tramitacao, qtd_tramitacoes, dias_em_tramitacao, qtd_autores, temas_oficiais,
    em_pauta_proximos_7d, url_inteiro_teor, link_camara, atualizado_em)
SELECT p.id_proposicao, p.sigla_tipo, p.numero, p.ano, p.ementa, p.ementa_detalhada, p.keywords,
       (p.data_apresentacao AT TIME ZONE 'America/Sao_Paulo')::date,
       p.situacao, p.cod_situacao, t.id_orgao, p.regime, p.apreciacao,
       coalesce(t.ultimo_despacho, p.despacho),
       coalesce(t.ultima, p.data_ultima_tramitacao), coalesce(t.qtd, 0),
       (coalesce(t.ultima, p.data_ultima_tramitacao)::date - p.data_apresentacao::date),
       coalesce(a.qtd, 0), tm.temas, (pa.id_proposicao IS NOT NULL), p.url_inteiro_teor,
       'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=' || p.id_proposicao,
       now()
FROM silver.proposicoes p
LEFT JOIN tram t USING (id_proposicao)
LEFT JOIN autores a USING (id_proposicao)
LEFT JOIN temas tm USING (id_proposicao)
LEFT JOIN pauta pa USING (id_proposicao)
WHERE p.sigla_tipo IS NOT NULL AND p.ementa IS NOT NULL
ON CONFLICT (id_proposicao) DO UPDATE SET
    sigla_tipo = EXCLUDED.sigla_tipo, numero = EXCLUDED.numero, ano = EXCLUDED.ano,
    ementa = EXCLUDED.ementa, ementa_detalhada = EXCLUDED.ementa_detalhada, keywords = EXCLUDED.keywords,
    data_apresentacao = EXCLUDED.data_apresentacao, situacao = EXCLUDED.situacao,
    cod_situacao = EXCLUDED.cod_situacao, id_orgao_situacao = EXCLUDED.id_orgao_situacao,
    regime = EXCLUDED.regime, apreciacao = EXCLUDED.apreciacao, ultimo_despacho = EXCLUDED.ultimo_despacho,
    data_ultima_tramitacao = EXCLUDED.data_ultima_tramitacao, qtd_tramitacoes = EXCLUDED.qtd_tramitacoes,
    dias_em_tramitacao = EXCLUDED.dias_em_tramitacao, qtd_autores = EXCLUDED.qtd_autores,
    temas_oficiais = EXCLUDED.temas_oficiais, em_pauta_proximos_7d = EXCLUDED.em_pauta_proximos_7d,
    url_inteiro_teor = EXCLUDED.url_inteiro_teor, link_camara = EXCLUDED.link_camara, atualizado_em = now();
    -- tema_ia, resumo_executivo, relevancia_score e demais colunas de IA: intocadas

-- ---------------------------------------------------------------- fato_tramitacao
INSERT INTO gold.fato_tramitacao
SELECT id_proposicao, sequencia, (data_hora AT TIME ZONE 'America/Sao_Paulo')::date, data_hora, id_orgao,
       sigla_orgao, descricao_tramitacao, descricao_situacao, despacho, regime
FROM silver.proposicoes_tramitacoes
ON CONFLICT (id_proposicao, sequencia) DO UPDATE SET
    data = EXCLUDED.data, data_hora = EXCLUDED.data_hora, id_orgao = EXCLUDED.id_orgao,
    sigla_orgao = EXCLUDED.sigla_orgao, descricao_tramitacao = EXCLUDED.descricao_tramitacao,
    descricao_situacao = EXCLUDED.descricao_situacao, despacho = EXCLUDED.despacho, regime = EXCLUDED.regime;

-- ---------------------------------------------------------------- fato_votacao
WITH objeto AS (                    -- prioridade: objeto > afetada > votada na tramitação > possível
    SELECT DISTINCT ON (id_votacao) id_votacao, id_proposicao
    FROM silver.votacoes_proposicoes
    ORDER BY id_votacao,
             CASE papel WHEN 'objeto' THEN 1 WHEN 'afetada' THEN 2 WHEN 'votada_na_tramitacao' THEN 3 ELSE 4 END,
             id_proposicao
),
contagem AS (
    SELECT id_votacao,
           count(*) FILTER (WHERE tipo_voto = 'Sim') AS sim,
           count(*) FILTER (WHERE tipo_voto = 'Não') AS nao,
           count(*) FILTER (WHERE tipo_voto NOT IN ('Sim', 'Não')) AS outros,
           count(*) AS total
    FROM silver.votos GROUP BY id_votacao
)
INSERT INTO gold.fato_votacao
SELECT v.id_votacao, v.data, v.data_hora_registro, v.id_orgao, v.sigla_orgao, v.id_evento,
       o.id_proposicao, v.aprovacao,
       coalesce(c.sim, 0), coalesce(c.nao, 0), coalesce(c.outros, 0), coalesce(c.total, 0),
       v.descricao, coalesce(c.total, 0) > 0
FROM silver.votacoes v
LEFT JOIN objeto o USING (id_votacao)
LEFT JOIN contagem c USING (id_votacao)
WHERE v.data IS NOT NULL
ON CONFLICT (id_votacao) DO UPDATE SET
    data = EXCLUDED.data, data_hora_registro = EXCLUDED.data_hora_registro, id_orgao = EXCLUDED.id_orgao,
    sigla_orgao = EXCLUDED.sigla_orgao, id_evento = EXCLUDED.id_evento,
    id_proposicao_objeto = EXCLUDED.id_proposicao_objeto, aprovacao = EXCLUDED.aprovacao,
    votos_sim = EXCLUDED.votos_sim, votos_nao = EXCLUDED.votos_nao, votos_outros = EXCLUDED.votos_outros,
    total_votos_nominais = EXCLUDED.total_votos_nominais, descricao = EXCLUDED.descricao,
    nominal = EXCLUDED.nominal;

-- ---------------------------------------------------------------- fato_orientacao
INSERT INTO gold.fato_orientacao
SELECT id_votacao, sigla_partido_bloco, orientacao_voto, cod_tipo_lideranca,
       sigla_partido_bloco ILIKE 'Governo%'
FROM silver.votacoes_orientacoes
ON CONFLICT (id_votacao, sigla_partido_bloco) DO UPDATE SET
    orientacao_voto = EXCLUDED.orientacao_voto, tipo_lideranca = EXCLUDED.tipo_lideranca,
    eh_governo = EXCLUDED.eh_governo;

-- ---------------------------------------------------------------- fato_voto
-- Orientação do partido: a do próprio partido; se não houver, a do bloco que o contém
-- (casando pelo código do bloco em cod_partido_bloco). "Liberado"/ausente ficam fora do denominador.
WITH base AS (
    SELECT vt.id_votacao, vt.id_deputado, vt.tipo_voto, vt.sigla_partido, vt.sigla_uf,
           coalesce(vt.data_registro_voto, fv.data_hora_registro, fv.data::timestamptz) AS instante,
           fv.data
    FROM silver.votos vt
    JOIN gold.fato_votacao fv USING (id_votacao)
),
orientado AS (
    SELECT b.*,
           (SELECT o.orientacao_voto FROM silver.votacoes_orientacoes o
            WHERE o.id_votacao = b.id_votacao
              AND (upper(o.sigla_partido_bloco) = upper(b.sigla_partido)
                   OR o.cod_partido_bloco IN (
                       SELECT bp.id_bloco FROM silver.blocos_partidos bp
                       WHERE upper(bp.sigla_partido) = upper(b.sigla_partido)))
            ORDER BY (upper(o.sigla_partido_bloco) = upper(b.sigla_partido)) DESC
            LIMIT 1) AS orientacao_partido,
           (SELECT o.orientacao_voto FROM silver.votacoes_orientacoes o
            WHERE o.id_votacao = b.id_votacao AND o.sigla_partido_bloco ILIKE 'Governo%'
            LIMIT 1) AS orientacao_governo
    FROM base b
)
INSERT INTO gold.fato_voto
SELECT id_votacao, id_deputado, gold.sk_deputado_em(id_deputado, instante), data, sigla_partido,
       left(sigla_uf, 2), tipo_voto, orientacao_partido, orientacao_governo,
       CASE WHEN orientacao_partido IS NULL OR orientacao_partido ILIKE 'Liberado' THEN NULL
            ELSE tipo_voto = orientacao_partido END,
       CASE WHEN orientacao_governo IS NULL OR orientacao_governo ILIKE 'Liberado' THEN NULL
            ELSE tipo_voto = orientacao_governo END
FROM orientado
ON CONFLICT (id_votacao, id_deputado) DO UPDATE SET
    sk_deputado = EXCLUDED.sk_deputado, data = EXCLUDED.data, sigla_partido = EXCLUDED.sigla_partido,
    sigla_uf = EXCLUDED.sigla_uf, tipo_voto = EXCLUDED.tipo_voto,
    orientacao_partido = EXCLUDED.orientacao_partido, orientacao_governo = EXCLUDED.orientacao_governo,
    seguiu_partido = EXCLUDED.seguiu_partido, seguiu_governo = EXCLUDED.seguiu_governo;

-- ---------------------------------------------------------------- fato_despesa
INSERT INTO gold.fato_despesa
SELECT d.chave_despesa, d.id_deputado, dd.sk_deputado, d.data_documento, d.ano, d.mes,
       dd.sigla_partido, dd.sigla_uf, gold.titulo(d.tipo_despesa), gold.titulo(d.nome_fornecedor),  -- iniciais maiúsculas
       left(d.cnpj_cpf_fornecedor, 20),
       d.valor_documento, d.valor_liquido, d.valor_glosa, d.url_documento
FROM silver.despesas d
LEFT JOIN gold.dim_deputado dd
       ON dd.sk_deputado = gold.sk_deputado_em(
              d.id_deputado, coalesce(d.data_documento, make_date(d.ano, d.mes, 1))::timestamptz)
ON CONFLICT (chave_despesa) DO UPDATE SET
    sk_deputado = EXCLUDED.sk_deputado, sigla_partido = EXCLUDED.sigla_partido, sigla_uf = EXCLUDED.sigla_uf,
    tipo_despesa = EXCLUDED.tipo_despesa, nome_fornecedor = EXCLUDED.nome_fornecedor,
    valor_documento = EXCLUDED.valor_documento, valor_liquido = EXCLUDED.valor_liquido,
    valor_glosa = EXCLUDED.valor_glosa, url_documento = EXCLUDED.url_documento;

-- ---------------------------------------------------------------- fato_evento
WITH orgao AS (
    SELECT DISTINCT ON (id_evento) id_evento, id_orgao, sigla_orgao
    FROM silver.eventos_orgaos ORDER BY id_evento, id_orgao
),
pauta AS (SELECT id_evento, count(*) AS qtd FROM silver.eventos_pauta GROUP BY id_evento),
presentes AS (SELECT id_evento, count(*) AS qtd FROM silver.eventos_deputados GROUP BY id_evento)
INSERT INTO gold.fato_evento
SELECT e.id_evento, (e.data_hora_inicio AT TIME ZONE 'America/Sao_Paulo')::date, e.data_hora_inicio,
       e.data_hora_fim, o.id_orgao, o.sigla_orgao, e.descricao_tipo, e.situacao, e.descricao,
       coalesce(e.local_camara_nome, e.local_externo), coalesce(p.qtd, 0), 0, coalesce(pr.qtd, 0),
       e.url_registro
FROM silver.eventos e
LEFT JOIN orgao o USING (id_evento)
LEFT JOIN pauta p USING (id_evento)
LEFT JOIN presentes pr USING (id_evento)
ON CONFLICT (id_evento) DO UPDATE SET
    data = EXCLUDED.data, data_hora_inicio = EXCLUDED.data_hora_inicio, data_hora_fim = EXCLUDED.data_hora_fim,
    id_orgao_principal = EXCLUDED.id_orgao_principal, sigla_orgao = EXCLUDED.sigla_orgao,
    tipo_evento = EXCLUDED.tipo_evento, situacao = EXCLUDED.situacao, descricao = EXCLUDED.descricao,
    local = EXCLUDED.local, qtd_itens_pauta = EXCLUDED.qtd_itens_pauta,
    qtd_presentes = EXCLUDED.qtd_presentes, url_registro = EXCLUDED.url_registro;
    -- qtd_itens_criticos é recalculada depois da IA (M4)

-- ---------------------------------------------------------------- fato_pauta_item
INSERT INTO gold.fato_pauta_item
SELECT p.id_evento, p.ordem, p.id_proposicao, (e.data_hora_inicio AT TIME ZONE 'America/Sao_Paulo')::date,
       p.regime, p.titulo, p.id_relator, p.situacao_item, fp.tema_ia, t.critico
FROM silver.eventos_pauta p
LEFT JOIN silver.eventos e USING (id_evento)
LEFT JOIN gold.fato_proposicao fp USING (id_proposicao)
LEFT JOIN gold.dim_tema t ON t.nome = fp.tema_ia
ON CONFLICT (id_evento, ordem, id_proposicao) DO UPDATE SET
    data = EXCLUDED.data, regime = EXCLUDED.regime, titulo = EXCLUDED.titulo, id_relator = EXCLUDED.id_relator,
    situacao_item = EXCLUDED.situacao_item, tema_ia = EXCLUDED.tema_ia, critico = EXCLUDED.critico;

-- ---------------------------------------------------------------- fato_presenca_evento
INSERT INTO gold.fato_presenca_evento
SELECT d.id_evento, d.id_deputado, (e.data_hora_inicio AT TIME ZONE 'America/Sao_Paulo')::date, d.sigla_partido
FROM silver.eventos_deputados d
LEFT JOIN silver.eventos e USING (id_evento)
ON CONFLICT (id_evento, id_deputado) DO UPDATE SET data = EXCLUDED.data, sigla_partido = EXCLUDED.sigla_partido;

-- ---------------------------------------------------------------- fato_discurso
INSERT INTO gold.fato_discurso
SELECT d.id_deputado, d.data_hora_inicio, coalesce(d.tipo_discurso, ''), d.hash_url,
       (d.data_hora_inicio AT TIME ZONE 'America/Sao_Paulo')::date, dd.sigla_partido, d.id_evento,
       d.sumario, d.keywords, d.url_texto
FROM silver.discursos d
LEFT JOIN gold.dim_deputado dd ON dd.sk_deputado = gold.sk_deputado_em(d.id_deputado, d.data_hora_inicio)
ON CONFLICT (id_deputado, data_hora_inicio, tipo_discurso, hash_url) DO UPDATE SET
    data = EXCLUDED.data, sigla_partido = EXCLUDED.sigla_partido, id_evento = EXCLUDED.id_evento,
    sumario = EXCLUDED.sumario, keywords = EXCLUDED.keywords, url_texto = EXCLUDED.url_texto;
