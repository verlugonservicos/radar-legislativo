-- =====================================================================
-- gold/003_pontes.sql — tabelas-ponte (SPEC V3, seção 9.3). Idempotente.
-- =====================================================================

CREATE TABLE IF NOT EXISTS gold.ponte_proposicao_autor (
    id_proposicao INTEGER, nome_autor TEXT, id_deputado INTEGER, tipo_autor TEXT,
    ordem_assinatura INTEGER, proponente BOOLEAN,
    PRIMARY KEY (id_proposicao, nome_autor)
);
CREATE INDEX IF NOT EXISTS ix_pautor_dep ON gold.ponte_proposicao_autor (id_deputado);

CREATE TABLE IF NOT EXISTS gold.ponte_frente_membro (
    id_frente INTEGER, id_deputado INTEGER, titulo TEXT, data_inicio DATE, data_fim DATE,
    PRIMARY KEY (id_frente, id_deputado)
);
CREATE INDEX IF NOT EXISTS ix_pfrente_dep ON gold.ponte_frente_membro (id_deputado);

CREATE TABLE IF NOT EXISTS gold.ponte_orgao_membro (
    id_orgao INTEGER, id_deputado INTEGER, cod_titulo INTEGER, titulo TEXT, data_inicio DATE, data_fim DATE,
    PRIMARY KEY (id_orgao, id_deputado, cod_titulo, data_inicio)
);
CREATE INDEX IF NOT EXISTS ix_porgao_dep ON gold.ponte_orgao_membro (id_deputado);

CREATE TABLE IF NOT EXISTS gold.ponte_bloco_partido (
    id_bloco INTEGER, id_partido INTEGER, sigla_partido TEXT,
    PRIMARY KEY (id_bloco, id_partido)
);
