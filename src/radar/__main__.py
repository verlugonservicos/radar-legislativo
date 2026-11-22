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


def _cmd_catalog_sync(args: argparse.Namespace) -> int:
    from radar.catalog import sync

    rel = sync.sync(baixar=not args.offline)
    log.info("\n%s", rel.texto())
    if rel.novos:
        log.warning("revise as entradas novas em config/endpoints.yaml (revisar: true)")
    return 0


def _cmd_catalog_check(args: argparse.Namespace) -> int:
    from radar.catalog import sync
    from radar.catalog.loader import load_catalog, topological_levels

    specs = load_catalog()
    topological_levels(specs)  # falha se houver ciclo
    openapi = (
        sync.ler_openapi()
        if args.offline
        else sync.baixar_openapi(sync.OPENAPI_PADRAO.with_suffix(".tmp.json"))
    )
    cob = sync.cobertura(openapi, specs)
    pendentes = [s.nome for s in specs if s.revisar]
    log.info(
        "cobertura: %d/%d endpoints do OpenAPI no catálogo",
        len(cob.api & cob.catalogo),
        len(cob.api),
    )
    if cob.faltando:
        log.error("faltando no catálogo: %s", sorted(cob.faltando))
    if cob.sobrando:
        log.error("no catálogo mas não no OpenAPI: %s", sorted(cob.sobrando))
    if pendentes:
        log.warning("entradas aguardando revisão: %s", pendentes)
    if not args.offline:
        sync.OPENAPI_PADRAO.with_suffix(".tmp.json").unlink(missing_ok=True)
    return 0 if cob.ok else 1


def _cmd_catalog_amostras(args: argparse.Namespace) -> int:
    from radar.catalog.amostras import coletar

    resultado = coletar(
        apenas=set(args.endpoints.split(",")) if args.endpoints else None,
        dias=args.dias,
        id_pai=args.id,
    )
    falhas = {k: v for k, v in resultado.items() if not v.startswith(("ok", "vazio"))}
    vazios = sorted(k for k, v in resultado.items() if v == "vazio")
    log.info(
        "amostras: %d gravadas, %d vazias, %d falhas",
        len(resultado) - len(falhas),
        len(vazios),
        len(falhas),
    )
    if vazios:
        log.warning("vazios: %s", vazios)
    for nome, motivo in sorted(falhas.items()):
        log.error("%s: %s", nome, motivo)
    return 0 if not falhas else 1


def _cmd_catalog_dicionario(_: argparse.Namespace) -> int:
    from radar.catalog.dicionario import gerar

    log.info("dicionário gerado em %s", gerar())
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

    p_cat = sub.add_parser("catalog", help="Catálogo dos endpoints da API")
    sub_cat = p_cat.add_subparsers(dest="acao", required=True)
    p_sync = sub_cat.add_parser("sync", help="Sincroniza config/endpoints.yaml com o OpenAPI")
    p_sync.add_argument("--offline", action="store_true", help="usa config/openapi_camara.json")
    p_sync.set_defaults(func=_cmd_catalog_sync)
    p_check = sub_cat.add_parser("check", help="Valida a cobertura 78/78 (sai com 1 se faltar)")
    p_check.add_argument("--offline", action="store_true", help="usa config/openapi_camara.json")
    p_check.set_defaults(func=_cmd_catalog_check)
    p_amo = sub_cat.add_parser("amostras", help="Grava uma resposta real de cada endpoint")
    p_amo.add_argument("--endpoints", help="lista separada por vírgula (padrão: todos)")
    p_amo.add_argument("--dias", type=int, default=7, help="tamanho da janela (padrão: 7)")
    p_amo.add_argument(
        "--id", help="{id} a usar nos endpoints de --endpoints (ex.: votação nominal)"
    )
    p_amo.set_defaults(func=_cmd_catalog_amostras)
    sub_cat.add_parser("dicionario", help="Gera docs/dicionario_de_dados.md").set_defaults(
        func=_cmd_catalog_dicionario
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
