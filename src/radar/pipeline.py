"""Orquestração do pipeline (SPEC V3 seção 11.1). No M2: extração → Landing → Bronze.

Os endpoints rodam por nível topológico do catálogo: primeiro todos os de um nível são
extraídos e carregados, depois o nível seguinte, cujos `{id}` dependem deles.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Literal

from radar.bronze.loader import aplicar_retencao, load_endpoint
from radar.catalog.loader import due, load_catalog, topological_levels
from radar.catalog.models import EndpointSpec
from radar.config import get_settings
from radar.db import get_engine
from radar.extract import landing
from radar.extract.client import CamaraClient
from radar.extract.generic import GenericExtractor
from radar.run_context import (
    RunContext,
    atualizar_watermark,
    finish_run,
    ler_watermarks,
    registrar_cobertura,
    start_run,
)

log = logging.getLogger("radar.pipeline")

ETAPAS_M2 = frozenset({"extract", "bronze"})


def janela_incremental(hoje: date, watermarks: dict[str, date]) -> tuple[date, date]:
    """Do menor watermark (menos a sobreposição) até hoje; primeira execução = últimos 7 dias."""
    dias = get_settings().janela_incremental_dias
    if not watermarks:
        return hoje - timedelta(days=7), hoje
    return min(watermarks.values()) - timedelta(days=dias - 1), hoje


def _selecionar(
    specs: list[EndpointSpec],
    endpoints: set[str] | None,
    hoje: date,
    ja_rodaram: set[str],
    force: bool,
) -> list[EndpointSpec]:
    escolhidos = [s for s in specs if not endpoints or s.nome in endpoints]
    return [
        s
        for s in escolhidos
        if due(s, hoje, primeira_execucao=s.nome not in ja_rodaram, force=force)
    ]


def _processar(
    spec: EndpointSpec, ctx: RunContext, steps: frozenset[str], extrator: GenericExtractor | None
) -> dict:
    """Extrai e/ou carrega um endpoint; falhas ficam registradas sem derrubar o pipeline."""
    resumo: dict = {}
    if "extract" in steps and extrator is not None:
        r = extrator.run(spec, ctx)
        resumo.update(
            chamadas=r.chamadas,
            paginas=r.paginas,
            registros=r.registros,
            ids=r.ids,
            erros=len(r.erros),
        )
        observacao = None
        if r.vazio:
            observacao = (
                f"sem IDs de origem ({', '.join(spec.ids.de)})" if spec.ids and r.ids == 0
                else f"API sem dados para {ctx.start}..{ctx.end}"
            )  # fmt: skip
        elif r.erros:
            observacao = f"{len(r.erros)} chamada(s) com erro; ex.: {r.erros[0]['erro'][:150]}"
        registrar_cobertura(ctx, spec.nome, chamadas=r.chamadas, paginas=r.paginas,
                            registros=r.registros, erros=len(r.erros), observacao=observacao)  # fmt: skip
        atualizar_watermark(ctx, spec.nome, "landing", ctx.end)
    if "bronze" in steps:
        bronze = get_engine("bronze_database_url")
        if "extract" in steps:  # arquivos desta execução
            arquivos = landing.iter_files(
                spec.nome, date.min, date.max, id_execucao=ctx.id_execucao
            )
        else:  # carga avulsa: partições do período
            arquivos = landing.iter_files(spec.nome, ctx.start, ctx.end)
        c = load_endpoint(spec, bronze, arquivos, ctx.id_execucao)
        resumo.update(lidos=c.lidos, inseridos=c.inseridos)
        registrar_cobertura(ctx, spec.nome, inseridos=c.inseridos)
        atualizar_watermark(ctx, spec.nome, "bronze", ctx.end)
        aplicar_retencao(bronze, spec, ctx.settings.bronze_retencao_versoes_dias)
    return resumo


def run_pipeline(
    modo: Literal["incremental", "backfill"],
    start: date | None = None,
    end: date | None = None,
    steps: frozenset[str] = ETAPAS_M2,
    endpoints: set[str] | None = None,
    force: bool = False,
    origem: str = "cli",
) -> dict:
    """Executa as etapas pedidas e devolve o resumo da execução."""
    engine = get_engine()
    hoje = date.today()
    watermarks = ler_watermarks(engine, "bronze")
    if modo == "incremental":
        start, end = janela_incremental(hoje, watermarks)
    if start is None or end is None:
        raise ValueError("backfill exige --start e --end")
    if start > end:
        raise ValueError(f"início ({start}) depois do fim ({end})")

    ctx = start_run(engine, modo, start, end, origem,
                    {"steps": sorted(steps), "endpoints": sorted(endpoints or []), "force": force})  # fmt: skip
    specs = _selecionar(load_catalog(), endpoints, hoje, set(watermarks), force)
    extrator = GenericExtractor(CamaraClient()) if "extract" in steps else None
    falhas: list[str] = []
    t0 = time.monotonic()
    try:
        for nivel, grupo in enumerate(topological_levels(specs)):
            inicio_nivel = time.monotonic()
            for spec in grupo:
                try:
                    ctx.contagens[spec.nome] = _processar(spec, ctx, steps, extrator)
                    if ctx.contagens[spec.nome].get("erros"):
                        falhas.append(spec.nome)
                except Exception as erro:  # um endpoint nunca derruba os demais
                    log.exception("%s: falha inesperada", spec.nome)
                    ctx.contagens[spec.nome] = {"falha": str(erro)[:300]}
                    falhas.append(spec.nome)
            ctx.etapas[f"nivel_{nivel}"] = {
                "endpoints": len(grupo), "duracao_s": round(time.monotonic() - inicio_nivel, 1),
            }  # fmt: skip
        status = "partial" if falhas else "success"
        erro_txt = f"endpoints com erro: {', '.join(falhas)}" if falhas else None
    except Exception as erro:
        status, erro_txt = "failed", str(erro)[:500]
        log.exception("pipeline falhou")
    ctx.etapas["total_s"] = round(time.monotonic() - t0, 1)
    finish_run(ctx, status, erro_txt)
    return {"id_execucao": ctx.id_execucao, "status": status, "endpoints": len(specs),
            "falhas": falhas, "duracao_s": ctx.etapas["total_s"], "start": start, "end": end}  # fmt: skip
