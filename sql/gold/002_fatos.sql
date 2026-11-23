-- =====================================================================
-- gold/002_fatos.sql — fatos (SPEC V3, seção 9.2). Idempotente.
-- As colunas de IA de fato_proposicao existem desde já e nunca são
-- sobrescritas pela carga do ETL (só pela camada de IA, no M4).
-- =====================================================================

CREATE TABLE IF NOT EXISTS gold.fato_proposicao (
    id_proposicao INTEGER PRIMARY KEY,
    sigla_tipo VARCHAR(10) NOT NULL, numero INTEGER, ano INTEGER,
    ementa TEXT NOT NULL, ementa_detalhada TEXT, keywords TEXT,
    data_apresentacao DATE REFERENCES gold.dim_tempo (data),
    situacao TEXT, cod_situacao INTEGER, id_orgao_situacao INTEGER, regime TEXT, apreciacao TEXT,
    ultimo_despacho TEXT, data_ultima_tramitacao TIMESTAMPTZ, qtd_tramitacoes INTEGER,
    dias_em_tramitacao INTEGER, qtd_autores INTEGER, temas_oficiais TEXT[],
    em_pauta_proximos_7d BOOLEAN DEFAULT false, url_inteiro_teor TEXT, link_camara TEXT,
    -- IA (M4)
    tema_ia VARCHAR(80), tema_ia_score NUMERIC(6,4), tema_ia_segundo VARCHAR(80),
    resumo_executivo TEXT,
    nivel_impacto VARCHAR(10) CHECK (nivel_impacto IN ('baixo', 'medio', 'alto')),
    setores_afetados TEXT[], relevancia_score NUMERIC(6,4),
    ia_modelo_llm TEXT, ia_prompt_versao TEXT, ia_texto_hash CHAR(64), ia_processado_em TIMESTAMPTZ,
    atualizado_em TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fprop_data ON gold.fato_proposicao (data_apresentacao);
CREATE INDEX IF NOT EXISTS ix_fprop_tema ON gold.fato_proposicao (tema_ia);
CREATE INDEX IF NOT EXISTS ix_fprop_tipo ON gold.fato_proposicao (sigla_tipo);

CREATE TABLE IF NOT EXISTS gold.fato_tramitacao (
    id_proposicao INTEGER, sequencia INTEGER, data DATE, data_hora TIMESTAMPTZ, id_orgao INTEGER,
    sigla_orgao TEXT, descricao_tramitacao TEXT, descricao_situacao TEXT, despacho TEXT, regime TEXT,
    PRIMARY KEY (id_proposicao, sequencia)
);
CREATE INDEX IF NOT EXISTS ix_ftram_data ON gold.fato_tramitacao (data);

CREATE TABLE IF NOT EXISTS gold.fato_votacao (
    id_votacao VARCHAR(40) PRIMARY KEY,
    data DATE REFERENCES gold.dim_tempo (data),
    data_hora_registro TIMESTAMPTZ, id_orgao INTEGER, sigla_orgao TEXT, id_evento INTEGER,
    id_proposicao_objeto INTEGER, aprovacao SMALLINT,
    -- calculados a partir dos votos nominais (a API não traz essas contagens; ADR-023)
    votos_sim INTEGER, votos_nao INTEGER, votos_outros INTEGER, total_votos_nominais INTEGER,
    descricao TEXT, nominal BOOLEAN
);
CREATE INDEX IF NOT EXISTS ix_fvotacao_data ON gold.fato_votacao (data);

CREATE TABLE IF NOT EXISTS gold.fato_voto (
    id_votacao VARCHAR(40), id_deputado INTEGER,
    sk_deputado BIGINT REFERENCES gold.dim_deputado,
    data DATE, sigla_partido VARCHAR(20), sigla_uf CHAR(2), tipo_voto VARCHAR(30),
    orientacao_partido VARCHAR(30), orientacao_governo VARCHAR(30),
    seguiu_partido BOOLEAN, seguiu_governo BOOLEAN,
    PRIMARY KEY (id_votacao, id_deputado)
);
CREATE INDEX IF NOT EXISTS ix_fvoto_data ON gold.fato_voto (data);
CREATE INDEX IF NOT EXISTS ix_fvoto_dep ON gold.fato_voto (id_deputado);
CREATE INDEX IF NOT EXISTS ix_fvoto_partido ON gold.fato_voto (sigla_partido);

CREATE TABLE IF NOT EXISTS gold.fato_orientacao (
    id_votacao VARCHAR(40), sigla_partido_bloco TEXT, orientacao_voto VARCHAR(30),
    tipo_lideranca TEXT, eh_governo BOOLEAN,
    PRIMARY KEY (id_votacao, sigla_partido_bloco)
);

CREATE TABLE IF NOT EXISTS gold.fato_despesa (
    chave_despesa CHAR(64) PRIMARY KEY, id_deputado INTEGER, sk_deputado BIGINT,
    data_documento DATE, ano SMALLINT, mes SMALLINT, sigla_partido VARCHAR(20), sigla_uf CHAR(2),
    tipo_despesa TEXT, nome_fornecedor TEXT, cnpj_cpf_fornecedor VARCHAR(20),
    valor_documento NUMERIC(14,2), valor_liquido NUMERIC(14,2), valor_glosa NUMERIC(14,2), url_documento TEXT
);
CREATE INDEX IF NOT EXISTS ix_fdesp_dep ON gold.fato_despesa (id_deputado);
CREATE INDEX IF NOT EXISTS ix_fdesp_data ON gold.fato_despesa (data_documento);
CREATE INDEX IF NOT EXISTS ix_fdesp_partido ON gold.fato_despesa (sigla_partido);

CREATE TABLE IF NOT EXISTS gold.fato_evento (
    id_evento INTEGER PRIMARY KEY, data DATE, data_hora_inicio TIMESTAMPTZ, data_hora_fim TIMESTAMPTZ,
    id_orgao_principal INTEGER, sigla_orgao TEXT, tipo_evento TEXT, situacao TEXT, descricao TEXT,
    local TEXT, qtd_itens_pauta INTEGER, qtd_itens_criticos INTEGER, qtd_presentes INTEGER, url_registro TEXT
);
CREATE INDEX IF NOT EXISTS ix_fevento_data ON gold.fato_evento (data);

CREATE TABLE IF NOT EXISTS gold.fato_pauta_item (
    id_evento INTEGER, ordem INTEGER, id_proposicao INTEGER, data DATE, regime TEXT, titulo TEXT,
    id_relator INTEGER, situacao_item TEXT, tema_ia VARCHAR(80), critico BOOLEAN,
    PRIMARY KEY (id_evento, ordem, id_proposicao)
);
CREATE INDEX IF NOT EXISTS ix_fpauta_data ON gold.fato_pauta_item (data);

CREATE TABLE IF NOT EXISTS gold.fato_presenca_evento (
    id_evento INTEGER, id_deputado INTEGER, data DATE, sigla_partido VARCHAR(20),
    PRIMARY KEY (id_evento, id_deputado)
);
CREATE INDEX IF NOT EXISTS ix_fpres_dep ON gold.fato_presenca_evento (id_deputado);

CREATE TABLE IF NOT EXISTS gold.fato_discurso (
    id_deputado INTEGER, data_hora_inicio TIMESTAMPTZ, tipo_discurso TEXT, hash_url CHAR(32),
    data DATE, sigla_partido VARCHAR(20), id_evento INTEGER, sumario TEXT, keywords TEXT, url_texto TEXT,
    PRIMARY KEY (id_deputado, data_hora_inicio, tipo_discurso, hash_url)
);
CREATE INDEX IF NOT EXISTS ix_fdisc_data ON gold.fato_discurso (data);
