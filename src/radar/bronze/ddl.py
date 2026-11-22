"""DDL da Bronze gerado a partir do catálogo (SPEC V3 seção 6.1)."""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

from radar.catalog.models import EndpointSpec

log = logging.getLogger("radar.bronze.ddl")

_MODELO = """
CREATE TABLE IF NOT EXISTS bronze.{nome} (
    id              BIGSERIAL PRIMARY KEY,
    endpoint        TEXT        NOT NULL,
    chave_registro  TEXT        NOT NULL,
    id_pai          TEXT,
    payload         JSONB       NOT NULL,
    payload_hash    CHAR(64)    NOT NULL,
    url             TEXT        NOT NULL,
    parametros      JSONB,
    pagina          INTEGER,
    arquivo_origem  TEXT        NOT NULL,
    id_execucao     BIGINT      NOT NULL,
    extraido_em     TIMESTAMPTZ NOT NULL,
    carregado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_{nome}_versao UNIQUE (chave_registro, payload_hash)
);
CREATE INDEX IF NOT EXISTS ix_{nome}_chave ON bronze.{nome} (chave_registro, carregado_em DESC);
CREATE INDEX IF NOT EXISTS ix_{nome}_exec  ON bronze.{nome} (id_execucao);
CREATE INDEX IF NOT EXISTS ix_{nome}_pai   ON bronze.{nome} (id_pai);
COMMENT ON TABLE bronze.{nome} IS 'GET {path} — payload integral, append-only, versionado por hash';
CREATE OR REPLACE VIEW bronze.vw_{nome}_atual AS
SELECT DISTINCT ON (chave_registro) *
FROM bronze.{nome}
ORDER BY chave_registro, carregado_em DESC, id DESC;
"""


def gerar_ddl(spec: EndpointSpec) -> str:
    return _MODELO.format(nome=spec.nome, path=spec.path)


def criar_tabelas(engine: Engine, specs: list[EndpointSpec]) -> int:
    """Cria (idempotente) uma tabela e uma view `_atual` por endpoint."""
    with engine.begin() as conn:
        driver = conn.connection.driver_connection
        with driver.cursor() as cur:
            cur.execute("\n".join(gerar_ddl(s) for s in specs))
    log.info("bronze: %d tabelas verificadas", len(specs))
    return len(specs)


def sincronizar_catalogo(engine: Engine, specs: list[EndpointSpec]) -> None:
    """Espelha o catálogo em `ops.catalogo_endpoints` (base de `ops.vw_cobertura_atual`)."""
    linhas = [
        {
            "endpoint": s.nome, "path": s.path, "tipo": s.tipo, "grupo": s.grupo,
            "pai": ",".join(s.ids.de) if s.ids else None, "frequencia": s.frequencia,
            "obsoleto": s.obsoleto,
        }
        for s in specs
    ]  # fmt: skip
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ops.catalogo_endpoints (endpoint, path, tipo, grupo, pai, frequencia, obsoleto) "
                "VALUES (:endpoint, :path, :tipo, :grupo, :pai, :frequencia, :obsoleto) "
                "ON CONFLICT (endpoint) DO UPDATE SET path = EXCLUDED.path, tipo = EXCLUDED.tipo, "
                "grupo = EXCLUDED.grupo, pai = EXCLUDED.pai, frequencia = EXCLUDED.frequencia, "
                "obsoleto = EXCLUDED.obsoleto, atualizado_em = now()"
            ),
            linhas,
        )
        nomes = [s.nome for s in specs]
        conn.execute(
            text(
                "UPDATE ops.catalogo_endpoints SET obsoleto = true WHERE NOT (endpoint = ANY(:n))"
            ),
            {"n": nomes},
        )
