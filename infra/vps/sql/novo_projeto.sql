-- =============================================================================
-- novo_projeto.sql — banco + papéis de um projeto do portfólio (SPEC V3, 23.2)
--
-- Executado por novo_projeto.sh, que define antes (pela entrada padrão):
--   \set banco ...  \set app ...  \set leitura ...  \set senha_app ...  \set senha_leitura ...
-- Roda com um papel que tem CREATEDB e CREATEROLE (no Supabase: postgres).
-- Não exige superusuário. Idempotente.
-- =============================================================================
\set ON_ERROR_STOP on
\set QUIET on
SELECT current_user AS prov \gset

-- 1. Papéis ------------------------------------------------------------------
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app', :'senha_app')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L CONNECTION LIMIT 5', :'leitura', :'senha_leitura')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'leitura') \gexec

-- Rotação de senhas (novo_projeto.sh --rotacionar-senhas define :rotacionar = 1)
SELECT format('ALTER ROLE %I PASSWORD %L', :'app', :'senha_app') WHERE :'rotacionar' = '1' \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'leitura', :'senha_leitura') WHERE :'rotacionar' = '1' \gexec

ALTER ROLE :"leitura" SET statement_timeout = '15s';
ALTER ROLE :"leitura" SET default_transaction_read_only = on;

-- No PostgreSQL 16+, quem cria um papel só recebe ADMIN sobre ele. Para criar o banco
-- com esse dono e preparar o schema de extensões, o provisionador precisa poder
-- assumir o papel (SET), sem herdar seus privilégios (INHERIT FALSE).
SELECT format('GRANT %I TO %I WITH INHERIT FALSE, SET TRUE', :'app', :'prov')
 WHERE NOT pg_has_role(:'prov', :'app', 'SET') \gexec

-- 2. Banco ---------------------------------------------------------------------
-- template0: banco limpo, sem herdar objetos do Supabase.
SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template0 ENCODING %L', :'banco', :'app', 'UTF8')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'banco') \gexec

-- Isolamento: só os papéis do projeto conectam.
SET ROLE :"app";
REVOKE CONNECT, TEMPORARY ON DATABASE :"banco" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"banco" TO :"app", :"leitura", :"prov";
RESET ROLE;

-- 3. Dentro do banco ---------------------------------------------------------------
\connect :"banco"
SET ROLE :"app";
CREATE SCHEMA IF NOT EXISTS extensions;
GRANT USAGE ON SCHEMA extensions TO :"leitura";
GRANT USAGE, CREATE ON SCHEMA extensions TO :"prov";
RESET ROLE;

-- pgvector: no Supabase o papel postgres pode criá-la (supautils, extensão "privilegiada").
-- Tolerante: em servidores sem a extensão, só avisa.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'vector não instalada: %', SQLERRM;
END
$$;

-- 4. Resultado -------------------------------------------------------------------
\unset QUIET
\echo '--- resultado'
SELECT current_database() AS banco,
       pg_get_userbyid(d.datdba) AS dono,
       (SELECT string_agg(extname || ' ' || extversion, ', ') FROM pg_extension WHERE extname <> 'plpgsql') AS extensoes,
       has_database_privilege('public', current_database(), 'CONNECT') AS publico_conecta
FROM pg_database d WHERE d.datname = current_database();
