"""Classificação temática por similaridade de cosseno (SPEC V3 10.4).

A similaridade proposição × tema é calculada no próprio PostgreSQL (pgvector, `<=>`), sem
trafegar os vetores; `cosine_matrix` é a versão NumPy usada nos testes e na avaliação.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from radar.config import get_settings

log = logging.getLogger("radar.ai.classifier")

SIMILARIDADES = """
SELECT e.id_proposicao, t.nome AS tema,
       1 - (e.embedding OPERATOR(extensions.<=>) t.embedding) AS sim
FROM gold.proposicao_embeddings e
JOIN gold.fato_proposicao f USING (id_proposicao)
CROSS JOIN gold.dim_tema t
WHERE t.embedding IS NOT NULL {filtro}
"""
PENDENTES = (
    "AND (f.tema_ia IS NULL OR f.ia_processado_em IS NULL OR e.criado_em > f.ia_processado_em)"
)


def cosine_matrix(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Normaliza as linhas e faz A @ B.T."""
    A = A / np.linalg.norm(A, axis=1, keepdims=True)
    B = B / np.linalg.norm(B, axis=1, keepdims=True)
    return A @ B.T


def escolher(sim: pd.DataFrame, limiar: float, fallback: str = "Outros") -> pd.DataFrame:
    """(id_proposicao, tema, sim) → tema_ia, tema_ia_score, tema_ia_segundo por proposição."""
    if sim.empty:
        return pd.DataFrame(
            columns=["id_proposicao", "tema_ia", "tema_ia_score", "tema_ia_segundo"]
        )
    ordenado = sim.sort_values(["id_proposicao", "sim"], ascending=[True, False])
    ordenado["pos"] = ordenado.groupby("id_proposicao").cumcount()
    primeiro = ordenado[ordenado.pos == 0].set_index("id_proposicao")
    segundo = ordenado[ordenado.pos == 1].set_index("id_proposicao")["tema"]
    saida = pd.DataFrame({
        "tema_ia": primeiro["tema"].where(primeiro["sim"] >= limiar, fallback),
        "tema_ia_score": primeiro["sim"].round(4),
        "tema_ia_segundo": segundo.reindex(primeiro.index),
    })  # fmt: skip
    return saida.reset_index()


def similaridades(engine: Engine, todas: bool = False) -> pd.DataFrame:
    sql = SIMILARIDADES.format(filtro="" if todas else PENDENTES)
    with engine.connect() as conn:
        return pd.DataFrame(conn.execute(text(sql)).all(), columns=["id_proposicao", "tema", "sim"])


def classify(engine: Engine, todas: bool = False, limiar: float | None = None) -> int:
    """Grava tema_ia/score/segundo. `todas=True` reclassifica tudo (útil ao mudar o limiar)."""
    limiar = get_settings().tema_limiar_minimo if limiar is None else limiar
    escolhas = escolher(similaridades(engine, todas), limiar)
    if escolhas.empty:
        return 0
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE gold.fato_proposicao SET tema_ia = :tema_ia, tema_ia_score = :tema_ia_score, "
                "tema_ia_segundo = :tema_ia_segundo, ia_processado_em = now() WHERE id_proposicao = :id_proposicao"
            ),
            [
                {
                    **r,
                    "tema_ia_score": float(r["tema_ia_score"]),
                    "id_proposicao": int(r["id_proposicao"]),
                }
                for r in escolhas.to_dict("records")
            ],
        )
    log.info("classificadas: %d (limiar %.2f)", len(escolhas), limiar)
    return len(escolhas)


def similares(engine: Engine, id_proposicao: int, k: int = 5) -> list[dict]:
    """As k proposições mais parecidas (busca semântica, pgvector com índice HNSW)."""
    with engine.connect() as conn:
        linhas = (
            conn.execute(
                text(
                    "SELECT o.id_proposicao, f.sigla_tipo, f.numero, f.ano, f.ementa, "
                    "1 - (o.embedding OPERATOR(extensions.<=>) b.embedding) AS similaridade "
                    "FROM gold.proposicao_embeddings b JOIN gold.proposicao_embeddings o "
                    "ON o.id_proposicao <> b.id_proposicao JOIN gold.fato_proposicao f ON f.id_proposicao = o.id_proposicao "
                    "WHERE b.id_proposicao = :id "
                    "ORDER BY o.embedding OPERATOR(extensions.<=>) b.embedding LIMIT :k"
                ),
                {"id": id_proposicao, "k": k},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in linhas]
