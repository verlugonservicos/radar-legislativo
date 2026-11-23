"""Orquestração da IA (SPEC V3 10.7): temas → embeddings → classificação → resumos → relevância."""

from __future__ import annotations

import logging

from sqlalchemy import Engine

from radar.ai import classifier, embeddings, relevance, summarizer
from radar.ai.cost import BudgetExceeded, CostTracker
from radar.ai.openai_client import Cliente, ClienteIA
from radar.config import get_settings
from radar.logging_setup import log_contexto
from radar.run_context import finish_run, start_run

log = logging.getLogger("radar.ai")


def run_ai(
    engine: Engine,
    id_execucao: int | None = None,
    limit: int | None = None,
    orcamento_usd: float | None = None,
    cliente: Cliente | None = None,
) -> dict:
    """Executa a camada de IA. `BudgetExceeded` interrompe as chamadas pagas e marca `teto_atingido`."""
    s = get_settings()
    cliente = cliente or ClienteIA()
    tracker = CostTracker(
        engine, id_execucao, s.ia_orcamento_max_usd if orcamento_usd is None else orcamento_usd
    )
    r: dict = {
        "embeddings": 0,
        "classificadas": 0,
        "resumos": 0,
        "falhas_resumo": 0,
        "teto_atingido": False,
    }
    with log_contexto(run=id_execucao, camada="ia"):
        try:
            r["temas"] = embeddings.sync_temas(engine, cliente, tracker)
            r["embeddings"] = embeddings.embed_proposicoes(engine, cliente, tracker, limit)
            r["classificadas"] = classifier.classify(engine)
            resumos = summarizer.summarize(engine, cliente, tracker, limit)
            r["resumos"], r["falhas_resumo"] = resumos["resumos"], resumos["falhas"]
        except BudgetExceeded as aviso:
            r["teto_atingido"] = True
            log.warning(
                "%s — o que já foi feito está gravado; o resto fica para a próxima execução", aviso
            )
            r["classificadas"] += classifier.classify(engine)  # classifica o que já tem embedding
        r["relevancia"] = relevance.update_relevance(engine)
        r["pendentes"] = len(summarizer.pendentes(engine))
        por_item = tracker.por_operacao.get("resumo", {})
        medio = (por_item.get("usd", 0) / por_item["itens"]) if por_item.get("itens") else 0.0
        r["custo_usd"] = round(tracker.total_usd, 6)
        r["custo_medio_por_proposicao_usd"] = round(medio, 6)
        r["projecao_pendentes_usd"] = round(medio * r["pendentes"], 4)
        r["custos"] = {k: {**v, "usd": round(v["usd"], 6)} for k, v in tracker.por_operacao.items()}
        log.info(
            "IA: %d embeddings, %d classificadas, %d resumos (%d falhas), US$ %.4f; %d pendentes",
            r["embeddings"], r["classificadas"], r["resumos"], r["falhas_resumo"], r["custo_usd"], r["pendentes"],
        )  # fmt: skip
    return r


def executar_ia(
    engine: Engine, limit: int | None = None, orcamento_usd: float | None = None
) -> dict:
    """`radar ai`: a IA como execução própria (modo `ai`) em `ops.pipeline_execucoes`."""
    from datetime import date

    hoje = date.today()
    ctx = start_run(
        engine, "ai", hoje, hoje, "cli", {"limit": limit, "orcamento_usd": orcamento_usd}
    )
    try:
        r = run_ai(engine, ctx.id_execucao, limit, orcamento_usd)
        ctx.contagens["ia"] = r
        status, erro = (
            ("partial", "teto de custo atingido") if r["teto_atingido"] else ("success", None)
        )
    except Exception as falha:
        r, status, erro = {}, "failed", str(falha)[:500]
        log.exception("IA falhou")
    finish_run(ctx, status, erro)
    return {"id_execucao": ctx.id_execucao, "status": status, **r}
