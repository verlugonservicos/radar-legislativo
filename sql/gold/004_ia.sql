-- =====================================================================
-- gold/004_ia.sql — estruturas da camada de IA (M4, SPEC V3 seção 10).
-- Requer pgvector no schema "extensions" (000_schemas.sql). Idempotente.
-- =====================================================================

ALTER TABLE gold.dim_tema ADD COLUMN IF NOT EXISTS embedding extensions.vector(1536);
ALTER TABLE gold.dim_tema ADD COLUMN IF NOT EXISTS modelo_embedding TEXT;
ALTER TABLE gold.dim_tema ADD COLUMN IF NOT EXISTS texto_hash CHAR(64);

CREATE TABLE IF NOT EXISTS gold.proposicao_embeddings (
    id_proposicao INTEGER PRIMARY KEY REFERENCES gold.fato_proposicao ON DELETE CASCADE,
    embedding extensions.vector(1536) NOT NULL,
    modelo TEXT NOT NULL,
    texto_hash CHAR(64) NOT NULL,
    criado_em TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prop_emb ON gold.proposicao_embeddings
    USING hnsw (embedding extensions.vector_cosine_ops);

-- Avaliação da classificação contra os temas oficiais da Câmara (notebook 02 e `radar ai avaliar`)
CREATE TABLE IF NOT EXISTS ops.avaliacao_ia (
    id BIGSERIAL PRIMARY KEY,
    id_execucao BIGINT REFERENCES ops.pipeline_execucoes,
    limiar NUMERIC(4,3) NOT NULL,
    avaliadas INTEGER NOT NULL,
    acertos INTEGER NOT NULL,
    acuracia NUMERIC(5,4) NOT NULL,
    cobertura NUMERIC(5,4) NOT NULL,     -- fração classificada acima do limiar (não "Outros")
    detalhes JSONB,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
