"""Avaliação da classificação contra os temas oficiais da Câmara (SPEC V3 10.7, notebook 02).

Atenção ao vazamento: o texto embutido das proposições inclui os temas oficiais (SPEC 10.3), então
a acurácia sobre a base inteira é otimista. `avaliar` mede também uma amostra **sem vazamento**
(texto sem os temas oficiais, embutido só para a avaliação) — é esse o número a reportar.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
import yaml
from sqlalchemy import Engine, text

from radar.ai.classifier import cosine_matrix, similaridades
from radar.ai.cost import CostTracker, estimate_tokens
from radar.ai.openai_client import Cliente
from radar.ai.prompts import texto_proposicao
from radar.config import RAIZ_PROJETO, get_settings

log = logging.getLogger("radar.ai.avaliacao")
MAPA = RAIZ_PROJETO / "config" / "mapa_temas_oficiais.yaml"
LIMIARES = [float(round(x, 3)) for x in np.arange(0.20, 0.61, 0.025)]


def carregar_mapa() -> dict[str, set[str]]:
    bruto = yaml.safe_load(MAPA.read_text(encoding="utf-8"))
    return {k: set(v if isinstance(v, list) else [v]) - {"Outros"} for k, v in bruto.items()}


def esperado(temas_oficiais, mapa: dict[str, set[str]]) -> set[str]:
    """Temas internos aceitos como acerto (vazio = proposição não avaliável)."""
    return set().union(*(mapa.get(t, set()) for t in (temas_oficiais or [])))


def top1(sim: pd.DataFrame) -> pd.DataFrame:
    idx = sim.groupby("id_proposicao")["sim"].idxmax()
    return sim.loc[idx].rename(columns={"tema": "tema_top", "sim": "score"}).reset_index(drop=True)


def curva(df: pd.DataFrame, limiares=LIMIARES) -> list[dict]:
    """df: tema_top, score, acerto (bool). Abaixo do limiar a proposição vira "Outros" (erro)."""
    linhas = []
    for t in limiares:
        acima = df["score"] >= t
        acertos = int((df["acerto"] & acima).sum())
        linhas.append({
            "limiar": t, "cobertura": round(float(acima.mean()), 4),
            "acuracia": round(acertos / len(df), 4),                      # Outros conta como erro
            "acuracia_classificadas": round(acertos / max(int(acima.sum()), 1), 4),
        })  # fmt: skip
    return linhas


def base_avaliavel(engine: Engine) -> pd.DataFrame:
    mapa = carregar_mapa()
    with engine.connect() as conn:
        props = pd.DataFrame(conn.execute(text(
            "SELECT id_proposicao, sigla_tipo, ementa, keywords, temas_oficiais FROM gold.fato_proposicao "
            "WHERE sigla_tipo = ANY(:t) AND cardinality(temas_oficiais) > 0"),
            {"t": get_settings().tipos_relevantes}).mappings().all())  # fmt: skip
    if props.empty:
        return props
    props["esperado"] = props["temas_oficiais"].map(lambda t: esperado(t, mapa))
    return props[props["esperado"].map(bool)].reset_index(drop=True)


def sem_vazamento(engine: Engine, cliente: Cliente, tracker: CostTracker, base: pd.DataFrame,
                  n: int) -> dict:  # fmt: skip
    """Embute `n` proposições sem os temas oficiais no texto e mede o top-1 contra os temas."""
    amostra = base.sample(min(n, len(base)), random_state=42)
    textos = [texto_proposicao(r.sigla_tipo, r.ementa, r.keywords) for r in amostra.itertuples()]
    with engine.connect() as conn:
        temas = conn.execute(text(
            "SELECT nome, embedding::text FROM gold.dim_tema WHERE embedding IS NOT NULL ORDER BY nome")).all()  # fmt: skip
    T = np.array([json.loads(v) for _, v in temas])
    nomes = [n for n, _ in temas]
    vetores = []
    for i in range(0, len(textos), 100):
        lote = textos[i : i + 100]
        tracker.check_projection(
            tracker.custo("embedding_avaliacao", sum(estimate_tokens(x) for x in lote))
        )
        v, tokens = cliente.embed(lote)
        tracker.add("embedding_avaliacao", len(lote), tokens)
        vetores += v
    S = cosine_matrix(np.array(vetores), T)
    df = pd.DataFrame({"tema_top": [nomes[j] for j in S.argmax(axis=1)], "score": S.max(axis=1)})
    df["acerto"] = [t in e for t, e in zip(df["tema_top"], amostra["esperado"], strict=True)]
    return {"n": len(df), "acuracia_top1": round(float(df["acerto"].mean()), 4), "curva": curva(df)}


def avaliar(engine: Engine, cliente: Cliente | None = None, tracker: CostTracker | None = None,
            id_execucao: int | None = None, limiar: float | None = None,
            amostra_sem_vazamento: int = 300, gravar: bool = True) -> dict:  # fmt: skip
    limiar = get_settings().tema_limiar_minimo if limiar is None else limiar
    base = base_avaliavel(engine)
    sim = similaridades(engine, todas=True)
    df = top1(sim).merge(base[["id_proposicao", "esperado"]], on="id_proposicao")
    if df.empty:
        return {"avaliadas": 0}
    df["acerto"] = [t in e for t, e in zip(df["tema_top"], df["esperado"], strict=True)]
    pontos = curva(df)
    no_limiar = curva(df, [limiar])[0]
    resultado = {
        "limiar": limiar, "avaliadas": len(df), "acertos": int((df["acerto"] & (df["score"] >= limiar)).sum()),
        "acuracia": no_limiar["acuracia"], "cobertura": no_limiar["cobertura"],
        "acuracia_top1_com_vazamento": round(float(df["acerto"].mean()), 4), "curva": pontos,
    }  # fmt: skip
    if cliente is not None and tracker is not None and amostra_sem_vazamento:
        resultado["sem_vazamento"] = sem_vazamento(
            engine, cliente, tracker, base, amostra_sem_vazamento
        )
    if gravar:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ops.avaliacao_ia (id_execucao, limiar, avaliadas, acertos, acuracia, cobertura, detalhes) "
                    "VALUES (:r, :l, :a, :h, :ac, :c, CAST(:d AS jsonb))"
                ),
                {"r": id_execucao, "l": limiar, "a": resultado["avaliadas"], "h": resultado["acertos"],
                 "ac": resultado["acuracia"], "c": resultado["cobertura"], "d": json.dumps(resultado)},
            )  # fmt: skip
    return resultado
