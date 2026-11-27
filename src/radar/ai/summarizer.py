"""Resumo executivo com LLM e saída JSON estrita (SPEC V3 10.6).

O resumo é refeito só quando a ementa (ou a ementa detalhada) muda: novos despachos de
tramitação entram no contexto do prompt, mas não disparam um novo resumo (ADR-026).
"""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import Engine, text

from radar.ai.cost import CostTracker, estimate_tokens
from radar.ai.openai_client import Cliente
from radar.ai.prompts import PROMPT_VERSAO, SCHEMA_RESUMO, SYSTEM_RESUMO, USER_RESUMO
from radar.config import get_settings

log = logging.getLogger("radar.ai.summarizer")
LOTE = 10
WORKERS = 4  # chamadas simultâneas dentro do lote (limite de taxa folgado no gpt-4o-mini)
SAIDA_ESTIMADA = 150  # tokens por resumo (medido no teste: ~90)

PENDENTES = """
SELECT f.id_proposicao, f.sigla_tipo, f.numero, f.ano, f.tema_ia, f.ementa, f.ementa_detalhada,
       f.keywords, o.sigla AS orgao_situacao, f.regime, f.ultimo_despacho, f.ia_texto_hash, f.ia_prompt_versao
FROM gold.fato_proposicao f
LEFT JOIN gold.dim_orgao o ON o.id_orgao = f.id_orgao_situacao
WHERE f.sigla_tipo = ANY(:tipos) AND f.tema_ia IS NOT NULL AND f.ementa IS NOT NULL
ORDER BY f.data_apresentacao DESC NULLS LAST, f.id_proposicao DESC
"""


def hash_resumo(ementa: str | None, ementa_detalhada: str | None) -> str:
    return hashlib.sha256(f"{ementa or ''}|{ementa_detalhada or ''}".encode()).hexdigest()


def montar_prompt(p: dict) -> str:
    return USER_RESUMO.format(
        sigla_tipo=p["sigla_tipo"], numero=p["numero"], ano=p["ano"], tema_ia=p["tema_ia"],
        ementa=p["ementa"], ementa_detalhada=p["ementa_detalhada"] or p["keywords"] or "-",
        orgao_situacao=p["orgao_situacao"] or "-", regime=p["regime"] or "-",
        ultimo_despacho=p["ultimo_despacho"] or "-",
    )  # fmt: skip


def pendentes(engine: Engine, limit: int | None = None) -> list[dict]:
    with engine.connect() as conn:
        linhas = (
            conn.execute(text(PENDENTES), {"tipos": get_settings().tipos_relevantes})
            .mappings()
            .all()
        )
    saida = []
    for r in linhas:
        h = hash_resumo(r["ementa"], r["ementa_detalhada"])
        # pendente se o texto mudou OU se o resumo foi feito com outra versão do prompt (ex.: v3 → v4)
        if h != r["ia_texto_hash"] or r.get("ia_prompt_versao") != PROMPT_VERSAO:
            saida.append({**r, "_hash": h})
            if limit is not None and len(saida) >= limit:
                break
    return saida


def _chamar(cliente: Cliente, user: str) -> tuple[dict, int, int] | Exception:
    try:
        return cliente.chat_json(SYSTEM_RESUMO, user, SCHEMA_RESUMO)
    except Exception as erro:
        return erro


def summarize(
    engine: Engine, cliente: Cliente, tracker: CostTracker, limit: int | None = None
) -> dict:
    """Resume as pendentes em lotes de 10, checando o teto antes de cada lote."""
    s = get_settings()
    if not s.ia_resumo_habilitado:
        return {"resumos": 0, "falhas": 0, "pendentes": 0}
    fila = pendentes(engine, limit)
    feitos = falhas = 0
    for i in range(0, len(fila), LOTE):
        lote = fila[i : i + LOTE]
        prompts = [montar_prompt(p) for p in lote]
        previsto = sum(estimate_tokens(SYSTEM_RESUMO + u) for u in prompts)
        tracker.check_projection(tracker.custo("resumo", previsto, SAIDA_ESTIMADA * len(lote)))
        gravar, t_in, t_out = [], 0, 0
        with ThreadPoolExecutor(WORKERS) as pool:
            respostas = list(pool.map(lambda u: _chamar(cliente, u), prompts))
        for p, resposta in zip(lote, respostas, strict=True):
            if isinstance(resposta, Exception):  # uma proposição nunca derruba as demais
                falhas += 1
                log.warning("resumo de %s falhou: %s", p["id_proposicao"], str(resposta)[:200])
                continue
            obj, ti, to = resposta
            t_in, t_out = t_in + ti, t_out + to
            gravar.append({
                "id": p["id_proposicao"], "resumo": obj["resumo_executivo"].strip()[:400],
                "impacto": obj["nivel_impacto"], "setores": list(dict.fromkeys(obj["setores_afetados"]))[:4],
                "modelo": s.llm_model, "versao": PROMPT_VERSAO, "hash": p["_hash"],
            })  # fmt: skip
        if gravar:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE gold.fato_proposicao SET resumo_executivo = :resumo, nivel_impacto = :impacto, "
                        "setores_afetados = :setores, ia_modelo_llm = :modelo, ia_prompt_versao = :versao, "
                        "ia_texto_hash = :hash WHERE id_proposicao = :id"
                    ),
                    gravar,
                )
            tracker.add("resumo", len(gravar), t_in, t_out)
            feitos += len(gravar)
        if (i // LOTE + 1) % 25 == 0:
            log.info("resumos: %d/%d · US$ %.4f até agora", feitos, len(fila), tracker.total_usd)
    restantes = len(fila) - feitos - falhas if limit is not None else 0
    if feitos or falhas:
        log.info("resumos: %d gravados, %d falhas", feitos, falhas)
    return {"resumos": feitos, "falhas": falhas, "pendentes": restantes}
