"""Acesso ao PostgreSQL: engine, execução de scripts SQL e `db init`."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, text

from radar.config import RAIZ_PROJETO, Settings, get_settings
from radar.logging_setup import mascarar

log = logging.getLogger("radar.db")

SQL_DIR = RAIZ_PROJETO / "sql"

# Ordem do `db init`. Os marcos seguintes acrescentam silver → gold → bronze (catálogo).
SQL_INIT: tuple[str, ...] = (
    "000_schemas.sql",
    "ops/001_ops.sql",
    "ops/002_views_ops.sql",
    "ops/003_roles.sql",
)

CAMADAS = ("bronze", "silver", "gold", "ops")


def criar_engine(url: str) -> Engine:
    """Engine SQLAlchemy compatível com o pooler do Supabase (modo transação, porta 6543)."""
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # PgBouncer em modo transação não suporta prepared statements persistentes.
        connect_args={"prepare_threshold": None, "application_name": "radar-legislativo"},
    )


@lru_cache
def get_engine(campo: str = "database_url") -> Engine:
    """Engine para `database_url`, `bronze_database_url` ou `database_url_readonly`."""
    settings = get_settings()
    if campo == "bronze_database_url":
        segredo = settings.bronze_database_url
        url = segredo.get_secret_value() if segredo else ""
        if not url or "<senha>" in url:
            url = settings.exigir("database_url")
    else:
        url = settings.exigir(campo)
    return criar_engine(url)


def executar_script(engine: Engine, caminho: Path) -> list[str]:
    """Executa um arquivo SQL inteiro numa transação. Devolve os NOTICEs do servidor."""
    sql = caminho.read_text(encoding="utf-8")
    avisos: list[str] = []
    with engine.begin() as conn:
        driver = conn.connection.driver_connection
        handler = None
        if hasattr(driver, "add_notice_handler"):

            def handler(diag) -> None:  # noqa: ANN001
                avisos.append(diag.message_primary or "")

            driver.add_notice_handler(handler)
        try:
            # Direto no driver e sem parâmetros: o psycopg aceita vários comandos e não
            # interpreta o "%" de RAISE NOTICE como placeholder.
            with driver.cursor() as cur:
                cur.execute(sql)
        finally:
            if handler is not None:
                driver.remove_notice_handler(handler)
    return avisos


# Executados depois da Bronze (dependem das tabelas bronze.* e de ops.catalogo_endpoints).
SQL_POS_BRONZE: tuple[str, ...] = ("ops/004_views_cobertura.sql",)


def db_init(
    engine: Engine,
    arquivos: tuple[str, ...] = SQL_INIT,
    bronze: bool = True,
    bronze_engine: Engine | None = None,
) -> None:
    """Cria schemas, objetos de controle e as tabelas Bronze do catálogo. Idempotente."""
    _executar(engine, arquivos)
    if bronze:
        from radar.bronze.ddl import criar_tabelas, sincronizar_catalogo
        from radar.catalog.loader import load_catalog

        specs = load_catalog()
        destino = bronze_engine or engine
        if destino is not engine:
            _executar(destino, ("000_schemas.sql",))
        criar_tabelas(destino, specs)
        sincronizar_catalogo(engine, specs)
        _executar(engine, SQL_POS_BRONZE)
        _executar(engine, ("ops/003_roles.sql",))  # reaplica permissões nas tabelas novas
    log.info("db init concluído")


def _executar(engine: Engine, arquivos: tuple[str, ...]) -> None:
    for nome in arquivos:
        caminho = SQL_DIR / nome
        log.info("executando %s", nome)
        for aviso in executar_script(engine, caminho):
            # "already exists, skipping" é o esperado de IF NOT EXISTS: não é problema.
            nivel = logging.DEBUG if "already exists, skipping" in aviso else logging.WARNING
            log.log(nivel, "aviso do banco em %s: %s", nome, aviso)


def dica_conexao(erro: Exception, settings: Settings | None = None) -> str | None:
    """Sugestão amigável quando a conexão pelo túnel SSH falha."""
    settings = settings or get_settings()
    texto = str(erro).lower()
    porta = str(settings.tunnel_porta_local)
    if ("connection refused" in texto or "conexão recusada" in texto) and porta in texto:
        return (
            f"Nada escutando em localhost:{porta}. Abra o túnel SSH em outro terminal: make tunnel"
        )
    return None


def verificar_conexao(engine: Engine) -> dict[str, object]:
    """Testa a conexão e informa versão do servidor e quais camadas já existem."""
    with engine.connect() as conn:
        versao = conn.execute(text("SHOW server_version")).scalar_one()
        existentes = set(
            conn.execute(
                text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:s)"),
                {"s": list(CAMADAS)},
            ).scalars()
        )
    return {
        "servidor": versao,
        "camadas": {c: (c in existentes) for c in CAMADAS},
    }


def descrever_destino(settings: Settings | None = None) -> str:
    """Host/banco de destino, sem senha, para mensagens ao usuário."""
    settings = settings or get_settings()
    if settings.database_url is None:
        return "(DATABASE_URL não configurada)"
    return mascarar(settings.database_url.get_secret_value())
