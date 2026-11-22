-- =====================================================================
-- 000_schemas.sql — camadas da arquitetura medalhão + extensões
-- Idempotente: pode ser executado quantas vezes for preciso.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS bronze;   -- payload integral da API (JSONB, append-only)
CREATE SCHEMA IF NOT EXISTS silver;   -- dados limpos e conformados (Pandas)
CREATE SCHEMA IF NOT EXISTS gold;     -- modelo estrela, marts e colunas de IA
CREATE SCHEMA IF NOT EXISTS ops;      -- controle: execuções, cobertura, custos, rejeições

COMMENT ON SCHEMA bronze IS 'Medalhão — Bronze: respostas integrais da API da Câmara, versionadas por hash';
COMMENT ON SCHEMA silver IS 'Medalhão — Silver: entidades limpas, validadas e conformadas';
COMMENT ON SCHEMA gold   IS 'Medalhão — Gold: dimensões, fatos, pontes e marts para os dashboards';
COMMENT ON SCHEMA ops    IS 'Operação: execuções do pipeline, cobertura dos endpoints, qualidade e custos';

-- pgvector (embeddings da IA, M4). No Supabase as extensões ficam no schema "extensions".
-- Tolerante: se a extensão não estiver disponível, o init segue e o M4 avisa.
CREATE SCHEMA IF NOT EXISTS extensions;
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector indisponível neste servidor (%). Necessário só a partir do M4.', SQLERRM;
END
$$;
