"""CLI do Radar Legislativo: `python -m radar <comando>`.

No M0 existem `db init` e `db check`; os demais comandos da SPEC (seção 11.2)
entram nos marcos seguintes.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.exc import OperationalError

from radar import __version__
from radar.config import ConfiguracaoAusente, get_settings
from radar.logging_setup import setup_logging

log = logging.getLogger("radar.cli")


def _cmd_db_init(_: argparse.Namespace) -> int:
    from radar import db

    log.info("destino: %s", db.descrever_destino())
    db.db_init(db.get_engine())
    info = db.verificar_conexao(db.get_engine())
    faltando = [c for c, ok in info["camadas"].items() if not ok]
    if faltando:
        log.error("camadas não criadas: %s", ", ".join(faltando))
        return 1
    log.info("camadas prontas: bronze, silver, gold, ops")
    return 0


def _cmd_db_check(_: argparse.Namespace) -> int:
    from radar import db

    log.info("destino: %s", db.descrever_destino())
    info = db.verificar_conexao(db.get_engine())
    log.info("conectado — PostgreSQL %s", info["servidor"])
    for camada, ok in info["camadas"].items():
        log.info("schema %-6s %s", camada, "ok" if ok else "ausente (rode `db init`)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar", description="Radar Legislativo — pipeline ETL")
    parser.add_argument("--version", action="version", version=f"radar {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_db = sub.add_parser("db", help="Operações no banco")
    sub_db = p_db.add_subparsers(dest="acao", required=True)
    sub_db.add_parser("init", help="Cria schemas e objetos de controle").set_defaults(
        func=_cmd_db_init
    )
    sub_db.add_parser("check", help="Testa a conexão e lista as camadas").set_defaults(
        func=_cmd_db_check
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    try:
        return args.func(args)
    except ConfiguracaoAusente as erro:
        log.error("%s", erro)
        return 2
    except OperationalError as erro:
        from radar.db import dica_conexao

        log.error("falha de conexão com o banco: %s", erro.orig or erro)
        if dica := dica_conexao(erro):
            log.error("%s", dica)
        return 3
    except Exception as erro:  # erro inesperado: registra sem segredos e sai com código 1
        log.exception("falha: %s", erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
