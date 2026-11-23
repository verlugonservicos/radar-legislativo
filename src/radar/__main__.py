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


def _datas(args: argparse.Namespace) -> tuple:
    from datetime import date

    inicio = date.fromisoformat(args.start) if getattr(args, "start", None) else None
    fim = date.fromisoformat(args.end) if getattr(args, "end", None) else None
    return inicio, fim


def _executar_pipeline(args: argparse.Namespace, steps: frozenset[str]) -> int:
    from radar.pipeline import run_pipeline

    inicio, fim = _datas(args)
    modo = getattr(args, "mode", None) or "backfill"
    endpoints = set(args.endpoints.split(",")) if getattr(args, "endpoints", None) else None
    r = run_pipeline(modo, inicio, fim, steps=steps, endpoints=endpoints, force=args.force)
    log.info(
        "execução %s: %s · %d endpoints · %s a %s · %.0f s",
        r["id_execucao"],
        r["status"],
        r["endpoints"],
        r["start"],
        r["end"],
        r["duracao_s"],
    )
    if r["falhas"]:
        log.warning("endpoints com erro: %s", ", ".join(r["falhas"]))
    return {"success": 0, "partial": 0}.get(r["status"], 1)


def _cmd_extract(args: argparse.Namespace) -> int:
    return _executar_pipeline(args, frozenset({"extract"}))


def _cmd_bronze(args: argparse.Namespace) -> int:
    return _executar_pipeline(args, frozenset({"bronze"}))


def _cmd_run(args: argparse.Namespace) -> int:
    if args.mode == "backfill" and not (args.start and args.end):
        log.error("--mode backfill exige --start e --end")
        return 2
    return _executar_pipeline(args, frozenset({"extract", "bronze", "silver", "gold"}))


def _cmd_silver(args: argparse.Namespace) -> int:
    from radar import db
    from radar.silver.runner import run_silver

    nomes = set(args.entidades.split(",")) if args.entidades else None
    r = run_silver(db.get_engine(), None, nomes, completa=args.completa)
    falhas = [n for n, c in r.items() if "falha" in c]
    nao_reconc = [n for n, c in r.items() if "falha" not in c and not c.get("reconciliado")]
    total = {
        k: sum(c.get(k, 0) for c in r.values() if "falha" not in c)
        for k in ("lidos", "gravados", "rejeitados", "duplicados")
    }
    log.info(
        "silver: %d entidades · %s · falhas: %s · não reconciliadas: %s",
        len(r),
        total,
        falhas or "nenhuma",
        nao_reconc or "nenhuma",
    )
    return 1 if falhas else 0


def _cmd_gold(_: argparse.Namespace) -> int:
    from radar import db
    from radar.gold.builder import build

    r = build(db.get_engine())
    falhas = [a for a, c in r["arquivos"].items() if "falha" in c]
    log.info("gold: %s", ", ".join(f"{t}={n}" for t, n in r["contagens"].items()))
    log.info("integridade (órfãos): %s", r["integridade"])
    if falhas:
        log.error("arquivos com falha: %s", falhas)
    return 1 if falhas else 0


def _cmd_status(_: argparse.Namespace) -> int:
    from sqlalchemy import text

    from radar import db

    with db.get_engine().connect() as conn:
        execs = conn.execute(
            text(
                "SELECT id_execucao, modo, status, "
                "(iniciado_em AT TIME ZONE 'America/Sao_Paulo')::timestamp(0), "
                "extract(epoch FROM finalizado_em - iniciado_em)::int "
                "FROM ops.pipeline_execucoes ORDER BY id_execucao DESC LIMIT 5"
            )
        ).all()
        cob = conn.execute(
            text("SELECT status, count(*) FROM ops.vw_cobertura_atual GROUP BY 1 ORDER BY 1")
        ).all()
        tam = conn.execute(
            text("SELECT schema, tabelas, tamanho_mb FROM ops.vw_tamanho_schemas ORDER BY 1")
        ).all()
        banco = conn.execute(text("SELECT tamanho_mb FROM ops.vw_tamanho_banco")).scalar_one()
    log.info("últimas execuções:")
    for e in execs:
        log.info("  #%s %-11s %-8s %s (%s s)", *e)
    log.info("cobertura: %s", ", ".join(f"{s}={n}" for s, n in cob) or "sem dados")
    for schema, tabelas, mb in tam:
        log.info("  schema %-6s %3d tabelas %8.2f MB", schema, tabelas, mb)
    limite = get_settings().db_limite_mb
    log.info("banco: %.2f MB de %d MB (%.1f%%)", banco, limite, 100 * float(banco) / limite)
    return 0


def _args_periodo(p: argparse.ArgumentParser, obrigatorio: bool) -> None:
    p.add_argument("--start", required=obrigatorio, help="AAAA-MM-DD")
    p.add_argument("--end", required=obrigatorio, help="AAAA-MM-DD")
    p.add_argument("--endpoints", help="lista separada por vírgula (padrão: todos)")
    p.add_argument("--force", action="store_true", help="ignora a frequência dos endpoints")


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

    p_ext = sub.add_parser("extract", help="Só Landing (API → JSON em disco)")
    _args_periodo(p_ext, obrigatorio=True)
    p_ext.set_defaults(func=_cmd_extract)
    p_bro = sub.add_parser("bronze", help="Landing → Bronze (partições do período)")
    _args_periodo(p_bro, obrigatorio=True)
    p_bro.set_defaults(func=_cmd_bronze)
    p_run = sub.add_parser("run", help="Pipeline (no M2: extração + Bronze)")
    p_run.add_argument("--mode", choices=["incremental", "backfill"], required=True)
    _args_periodo(p_run, obrigatorio=False)
    p_run.set_defaults(func=_cmd_run)
    p_sil = sub.add_parser("silver", help="Bronze → Silver (incremental por entidade)")
    p_sil.add_argument("--entidades", help="lista separada por vírgula (padrão: todas)")
    p_sil.add_argument(
        "--completa", action="store_true", help="relê toda a Bronze (ignora watermark)"
    )
    p_sil.set_defaults(func=_cmd_silver)
    p_gold = sub.add_parser("gold", help="Silver → Gold")
    p_gold.add_argument("acao", choices=["build"])
    p_gold.set_defaults(func=_cmd_gold)
    sub.add_parser("status", help="Execuções, cobertura e tamanho do banco").set_defaults(
        func=_cmd_status
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
