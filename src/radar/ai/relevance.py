"""Score de relevância das proposições (SPEC V3 10.7). Não chama a API: custo zero."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

log = logging.getLogger("radar.ai.relevance")

PESOS = {"tipo": 0.30, "tema": 0.25, "impacto": 0.20, "urgencia": 0.10, "pauta": 0.15}
IMPACTO = {"alto": 1.0, "medio": 0.5, "baixo": 0.1}
IMPACTO_DESCONHECIDO = 0.4
PESO_TIPO_PADRAO = 0.2


def compute_relevance(df: pd.DataFrame, temas_criticos: set[str]) -> pd.Series:
    """Colunas: peso_tipo, tema_ia, nivel_impacto, regime, em_pauta_proximos_7d → score 0..1."""
    tipo = pd.to_numeric(df["peso_tipo"], errors="coerce").fillna(PESO_TIPO_PADRAO).astype(float)
    tema = df["tema_ia"].isin(temas_criticos).astype(float)
    impacto = df["nivel_impacto"].map(IMPACTO).fillna(IMPACTO_DESCONHECIDO).astype(float)
    urgencia = df["regime"].fillna("").str.contains("urg", case=False).astype(float)
    pauta = df["em_pauta_proximos_7d"].fillna(False).astype(bool).astype(float)
    score = (
        PESOS["tipo"] * tipo + PESOS["tema"] * tema + PESOS["impacto"] * impacto
        + PESOS["urgencia"] * urgencia + PESOS["pauta"] * pauta
    )  # fmt: skip
    return score.round(4)


def update_relevance(engine: Engine) -> int:
    """Recalcula para todas as proposições e grava só os valores que mudaram."""
    with engine.connect() as conn:
        df = pd.DataFrame(
            conn.execute(text(
                "SELECT f.id_proposicao, t.peso_relevancia AS peso_tipo, f.tema_ia, f.nivel_impacto, "
                "f.regime, f.em_pauta_proximos_7d, f.relevancia_score "
                "FROM gold.fato_proposicao f LEFT JOIN gold.dim_tipo_proposicao t USING (sigla_tipo)"
            )).mappings().all()
        )  # fmt: skip
        criticos = set(conn.execute(text("SELECT nome FROM gold.dim_tema WHERE critico")).scalars())
    if df.empty:
        return 0
    df["novo"] = compute_relevance(df, criticos)
    atual = pd.to_numeric(df["relevancia_score"], errors="coerce").astype(float)
    mudou = df[~np.isclose(atual.fillna(-1), df["novo"])]
    if not mudou.empty:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE gold.fato_proposicao SET relevancia_score = :s WHERE id_proposicao = :id"
                ),
                [
                    {"s": float(s), "id": int(i)}
                    for i, s in zip(mudou["id_proposicao"], mudou["novo"], strict=True)
                ],
            )
    log.info("relevância: %d proposições atualizadas", len(mudou))
    return len(mudou)
