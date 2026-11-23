-- =====================================================================
-- gold/010_load_dimensoes.sql — carga das dimensões a partir da Silver.
-- Idempotente (UPSERT). gold.dim_tema é carregada pelo builder (config/temas.yaml).
-- =====================================================================

-- ---------------------------------------------------------------- dim_tempo
INSERT INTO gold.dim_tempo
SELECT d::date,
       extract(year FROM d)::smallint,
       extract(quarter FROM d)::smallint,
       extract(month FROM d)::smallint,
       (ARRAY['janeiro','fevereiro','março','abril','maio','junho','julho','agosto',
              'setembro','outubro','novembro','dezembro'])[extract(month FROM d)::int],
       extract(day FROM d)::smallint,
       extract(isodow FROM d)::smallint,
       (ARRAY['segunda-feira','terça-feira','quarta-feira','quinta-feira','sexta-feira',
              'sábado','domingo'])[extract(isodow FROM d)::int],
       extract(week FROM d)::smallint,
       date_trunc('week', d)::date,
       extract(isodow FROM d) IN (6, 7)
FROM generate_series('1946-01-01'::date, '2030-12-31'::date, interval '1 day') AS d
ON CONFLICT (data) DO NOTHING;

-- ---------------------------------------------------------------- dim_partido
INSERT INTO gold.dim_partido (id_partido, sigla, nome, situacao, total_membros, url_logo, atualizado_em)
SELECT id_partido, sigla, nome, situacao, total_membros, url_logo, now()
FROM silver.partidos
WHERE sigla IS NOT NULL
ON CONFLICT (id_partido) DO UPDATE SET
    sigla = EXCLUDED.sigla, nome = EXCLUDED.nome, situacao = EXCLUDED.situacao,
    total_membros = EXCLUDED.total_membros, url_logo = EXCLUDED.url_logo, atualizado_em = now();

-- ---------------------------------------------------------------- dim_deputado (SCD2)
-- 1) histórico: uma versão a cada mudança do hash dos atributos rastreados
-- 2) deputados sem histórico: versão única desde 1900-01-01
-- Merge por (id_deputado, valido_de): fecha/atualiza versões sem truncar (preserva as sk).
WITH hist_bruto AS (                         -- o mesmo instante pode aparecer em 2 legislaturas:
    SELECT h.*, row_number() OVER (           -- fica a linha da legislatura mais recente
               PARTITION BY h.id_deputado, h.data_hora ORDER BY h.id_legislatura DESC NULLS LAST) AS rn
    FROM silver.deputados_historico h
    WHERE h.data_hora IS NOT NULL
),
hist AS (
    SELECT h.id_deputado, h.data_hora,
           coalesce(h.nome, d.nome) AS nome, h.nome_eleitoral, h.sigla_partido, h.sigla_uf,
           h.situacao, h.condicao_eleitoral,
           md5(concat_ws('|', h.sigla_partido, h.situacao, h.condicao_eleitoral, h.sigla_uf, h.nome_eleitoral)) AS hash
    FROM hist_bruto h
    LEFT JOIN silver.deputados d USING (id_deputado)
    WHERE h.rn = 1
),
marcado AS (
    SELECT *, lag(hash) OVER (PARTITION BY id_deputado ORDER BY data_hora) AS hash_anterior
    FROM hist
),
versoes AS (                                   -- só as linhas em que algo mudou
    SELECT * FROM marcado WHERE hash_anterior IS DISTINCT FROM hash
),
vigencia AS (
    SELECT v.*, lead(data_hora) OVER (PARTITION BY id_deputado ORDER BY data_hora) AS valido_ate
    FROM versoes v
),
sem_historico AS (
    SELECT d.id_deputado, '1900-01-01 00:00:00-03'::timestamptz AS data_hora, d.nome, d.nome_eleitoral,
           d.sigla_partido, d.sigla_uf, d.situacao, d.condicao_eleitoral,
           md5(concat_ws('|', d.sigla_partido, d.situacao, d.condicao_eleitoral, d.sigla_uf, d.nome_eleitoral)) AS hash,
           NULL::text AS hash_anterior, NULL::timestamptz AS valido_ate
    FROM silver.deputados d
    WHERE NOT EXISTS (SELECT 1 FROM hist h WHERE h.id_deputado = d.id_deputado)
),
desejado AS (
    SELECT * FROM vigencia
    UNION ALL
    SELECT * FROM sem_historico
)
INSERT INTO gold.dim_deputado (
    id_deputado, nome, nome_eleitoral, sexo, sigla_uf, sigla_partido, id_partido, situacao,
    condicao_eleitoral, url_foto, email, valido_de, valido_ate, atual, hash_atributos)
SELECT x.id_deputado, coalesce(x.nome, d.nome, 'sem nome'), x.nome_eleitoral, left(d.sexo, 1),
       left(x.sigla_uf, 2), x.sigla_partido,
       (SELECT p.id_partido FROM gold.dim_partido p WHERE p.sigla = x.sigla_partido ORDER BY p.id_partido DESC LIMIT 1),
       x.situacao, x.condicao_eleitoral, d.url_foto, d.email,
       x.data_hora, x.valido_ate, x.valido_ate IS NULL, x.hash
FROM desejado x
LEFT JOIN silver.deputados d USING (id_deputado)
ON CONFLICT (id_deputado, valido_de) DO UPDATE SET
    nome = EXCLUDED.nome, nome_eleitoral = EXCLUDED.nome_eleitoral, sexo = EXCLUDED.sexo,
    sigla_uf = EXCLUDED.sigla_uf, sigla_partido = EXCLUDED.sigla_partido, id_partido = EXCLUDED.id_partido,
    situacao = EXCLUDED.situacao, condicao_eleitoral = EXCLUDED.condicao_eleitoral,
    url_foto = EXCLUDED.url_foto, email = EXCLUDED.email, valido_ate = EXCLUDED.valido_ate,
    atual = EXCLUDED.atual, hash_atributos = EXCLUDED.hash_atributos;

-- Versão provisória (1900) de quem ganhou histórico depois: fecha no início da primeira versão real.
UPDATE gold.dim_deputado p
SET atual = false,
    valido_ate = (SELECT min(r.valido_de) FROM gold.dim_deputado r
                  WHERE r.id_deputado = p.id_deputado AND r.valido_de > '1900-01-01 00:00:00-03')
WHERE p.valido_de = '1900-01-01 00:00:00-03'
  AND EXISTS (SELECT 1 FROM gold.dim_deputado r
              WHERE r.id_deputado = p.id_deputado AND r.valido_de > '1900-01-01 00:00:00-03');

-- ---------------------------------------------------------------- demais dimensões
INSERT INTO gold.dim_orgao (id_orgao, sigla, nome, apelido, tipo_orgao, cod_tipo_orgao, data_inicio, data_fim, casa)
SELECT id_orgao, sigla, nome, apelido, tipo_orgao, cod_tipo_orgao, data_inicio, data_fim, casa
FROM silver.orgaos
ON CONFLICT (id_orgao) DO UPDATE SET
    sigla = EXCLUDED.sigla, nome = EXCLUDED.nome, apelido = EXCLUDED.apelido, tipo_orgao = EXCLUDED.tipo_orgao,
    cod_tipo_orgao = EXCLUDED.cod_tipo_orgao, data_inicio = EXCLUDED.data_inicio,
    data_fim = EXCLUDED.data_fim, casa = EXCLUDED.casa;

-- Peso de relevância por tipo (SPEC 10.7): PEC 1.0 · MPV 0.9 · PLP 0.8 · PL 0.6 · PDL 0.5 · demais 0.2.
INSERT INTO gold.dim_tipo_proposicao (sigla_tipo, nome, descricao, peso_relevancia)
SELECT DISTINCT ON (sigla) sigla, nome, descricao,
       CASE sigla WHEN 'PEC' THEN 1.00 WHEN 'MPV' THEN 0.90 WHEN 'PLP' THEN 0.80
                  WHEN 'PL' THEN 0.60 WHEN 'PDL' THEN 0.50 ELSE 0.20 END
FROM silver.referencias
WHERE dominio = 'referencias_proposicoes_sigla_tipo' AND sigla IS NOT NULL
ORDER BY sigla, cod
ON CONFLICT (sigla_tipo) DO UPDATE SET nome = EXCLUDED.nome, descricao = EXCLUDED.descricao,
    peso_relevancia = EXCLUDED.peso_relevancia;

INSERT INTO gold.dim_frente (id_frente, titulo, id_legislatura, situacao, keywords, id_coordenador)
SELECT id_frente, titulo, id_legislatura, situacao, keywords, id_coordenador
FROM silver.frentes
ON CONFLICT (id_frente) DO UPDATE SET
    titulo = EXCLUDED.titulo, id_legislatura = EXCLUDED.id_legislatura, situacao = EXCLUDED.situacao,
    keywords = EXCLUDED.keywords, id_coordenador = EXCLUDED.id_coordenador;

INSERT INTO gold.dim_bloco (id_bloco, nome, id_legislatura)
SELECT id_bloco, nome, id_legislatura FROM silver.blocos
ON CONFLICT (id_bloco) DO UPDATE SET nome = EXCLUDED.nome, id_legislatura = EXCLUDED.id_legislatura;
