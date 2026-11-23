-- =====================================================================
-- gold/001_dimensoes.sql — dimensões (SPEC V3, seção 9.1). Idempotente.
-- Colunas de embedding (pgvector) entram no M4 (gold/004_ia.sql).
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS gold;

-- Calendário em pt-BR. Começa em 1946: proposições antigas voltam a tramitar.
CREATE TABLE IF NOT EXISTS gold.dim_tempo (
    data DATE PRIMARY KEY,
    ano SMALLINT, trimestre SMALLINT, mes SMALLINT, nome_mes TEXT,
    dia SMALLINT, dia_semana SMALLINT, nome_dia_semana TEXT, semana_iso SMALLINT,
    inicio_semana DATE, fim_de_semana BOOLEAN
);

CREATE TABLE IF NOT EXISTS gold.dim_partido (
    id_partido INTEGER PRIMARY KEY,
    sigla VARCHAR(20) NOT NULL,
    nome TEXT, situacao TEXT, total_membros INTEGER, url_logo TEXT,
    atualizado_em TIMESTAMPTZ DEFAULT now()
);
-- Sigla não é única por regra (a API pode reaproveitar siglas entre legislaturas): índice comum.
CREATE INDEX IF NOT EXISTS ix_dim_partido_sigla ON gold.dim_partido (sigla);

-- SCD tipo 2: uma versão por mudança de partido/situação/UF/condição/nome eleitoral.
CREATE TABLE IF NOT EXISTS gold.dim_deputado (
    sk_deputado BIGSERIAL PRIMARY KEY,
    id_deputado INTEGER NOT NULL,
    nome TEXT NOT NULL, nome_eleitoral TEXT, sexo CHAR(1), sigla_uf CHAR(2),
    sigla_partido VARCHAR(20), id_partido INTEGER, situacao TEXT, condicao_eleitoral TEXT,
    url_foto TEXT, email TEXT,
    valido_de TIMESTAMPTZ NOT NULL, valido_ate TIMESTAMPTZ, atual BOOLEAN NOT NULL,
    hash_atributos CHAR(32) NOT NULL,
    UNIQUE (id_deputado, valido_de)
);
CREATE INDEX IF NOT EXISTS ix_dimdep_atual ON gold.dim_deputado (id_deputado) WHERE atual;
CREATE INDEX IF NOT EXISTS ix_dimdep_vigencia ON gold.dim_deputado (id_deputado, valido_de, valido_ate);

CREATE TABLE IF NOT EXISTS gold.dim_orgao (
    id_orgao INTEGER PRIMARY KEY,
    sigla TEXT, nome TEXT, apelido TEXT, tipo_orgao TEXT, cod_tipo_orgao INTEGER,
    data_inicio DATE, data_fim DATE, casa TEXT
);

CREATE TABLE IF NOT EXISTS gold.dim_tema (
    id_tema SERIAL PRIMARY KEY,
    nome VARCHAR(80) UNIQUE NOT NULL, descricao TEXT NOT NULL,
    critico BOOLEAN NOT NULL DEFAULT false, cor_hex CHAR(7),
    atualizado_em TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gold.dim_tipo_proposicao (
    sigla_tipo VARCHAR(10) PRIMARY KEY,
    nome TEXT, descricao TEXT, peso_relevancia NUMERIC(3,2)
);

CREATE TABLE IF NOT EXISTS gold.dim_frente (
    id_frente INTEGER PRIMARY KEY,
    titulo TEXT, id_legislatura INTEGER, situacao TEXT, keywords TEXT, id_coordenador INTEGER
);

CREATE TABLE IF NOT EXISTS gold.dim_bloco (
    id_bloco INTEGER PRIMARY KEY,
    nome TEXT, id_legislatura INTEGER
);
