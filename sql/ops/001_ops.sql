-- =====================================================================
-- ops/001_ops.sql — tabelas de controle do pipeline (SPEC V2, seção 7)
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.pipeline_execucoes (
    id_execucao   BIGSERIAL PRIMARY KEY,
    modo          VARCHAR(20) NOT NULL,          -- incremental|backfill|ai|dashboard|manual
    origem        VARCHAR(20) NOT NULL,          -- cli|runner|n8n|actions
    parametros    JSONB,
    status        VARCHAR(20) NOT NULL DEFAULT 'running',   -- running|success|partial|failed
    etapas        JSONB,      -- {etapa: {inicio, fim, status, duracao_s}}
    contagens     JSONB,      -- {camada: {entidade: {lidos, validos, rejeitados, carregados}}}
    custo_ia_usd  NUMERIC(10,5) DEFAULT 0,
    erro          TEXT,
    iniciado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizado_em TIMESTAMPTZ,
    CONSTRAINT ck_execucoes_status CHECK (status IN ('running','success','partial','failed'))
);
CREATE INDEX IF NOT EXISTS ix_execucoes_iniciado_em ON ops.pipeline_execucoes (iniciado_em DESC);

CREATE TABLE IF NOT EXISTS ops.controle_ingestao (
    endpoint        VARCHAR(80) NOT NULL,
    camada          VARCHAR(10) NOT NULL,         -- landing|bronze|silver
    ultima_data_ref DATE        NOT NULL,
    ultima_execucao BIGINT,
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (endpoint, camada)
);

-- Espelho do config/endpoints.yaml, sincronizado pelo `db init` a partir do M1.
CREATE TABLE IF NOT EXISTS ops.catalogo_endpoints (
    endpoint       VARCHAR(80) PRIMARY KEY,       -- nome snake_case = tabela bronze.<endpoint>
    path           TEXT        NOT NULL,          -- ex.: /proposicoes/{id}/autores
    tipo           VARCHAR(20) NOT NULL,          -- lista|detalhe|sub_recurso|referencia
    grupo          VARCHAR(40),
    pai            VARCHAR(80),
    frequencia     VARCHAR(20),
    obsoleto       BOOLEAN     NOT NULL DEFAULT false,
    atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.cobertura_endpoints (
    id_execucao   BIGINT      NOT NULL REFERENCES ops.pipeline_execucoes,
    endpoint      VARCHAR(80) NOT NULL,
    chamadas      INTEGER     NOT NULL DEFAULT 0,
    paginas       INTEGER     NOT NULL DEFAULT 0,
    registros     INTEGER     NOT NULL DEFAULT 0,
    inseridos     INTEGER     NOT NULL DEFAULT 0,
    erros         INTEGER     NOT NULL DEFAULT 0,
    observacao    TEXT,
    PRIMARY KEY (id_execucao, endpoint)
);

CREATE TABLE IF NOT EXISTS ops.qualidade_rejeicoes (
    id BIGSERIAL PRIMARY KEY,
    id_execucao BIGINT REFERENCES ops.pipeline_execucoes,
    entidade VARCHAR(60) NOT NULL,
    chave TEXT,
    regra VARCHAR(60) NOT NULL,
    registro JSONB,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_rejeicoes_execucao ON ops.qualidade_rejeicoes (id_execucao);

CREATE TABLE IF NOT EXISTS ops.custos_ia (
    id BIGSERIAL PRIMARY KEY,
    id_execucao BIGINT REFERENCES ops.pipeline_execucoes,
    operacao VARCHAR(30) NOT NULL,
    modelo TEXT NOT NULL,
    itens INTEGER NOT NULL,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_saida INTEGER NOT NULL DEFAULT 0,
    custo_usd NUMERIC(10,6) NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.alertas_enviados (
    id_proposicao INTEGER NOT NULL,
    canal VARCHAR(20) NOT NULL,
    enviado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id_proposicao, canal)
);
