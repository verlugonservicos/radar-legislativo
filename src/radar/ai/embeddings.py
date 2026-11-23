"""Embeddings de temas e proposições (SPEC V3 10.3), com cache por hash do texto."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import Engine, text

from radar.ai.cost import CostTracker, estimate_tokens
from radar.ai.openai_client import Cliente
from radar.ai.prompts import texto_proposicao, texto_tema
from radar.config import get_settings

log = logging.getLogger("radar.ai.embeddings")


def hash_texto(texto: str, modelo: str) -> str:
    return hashlib.sha256(f"{modelo}|{texto}".encode()).hexdigest()


def vetor_sql(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def sync_temas(
    engine: Engine, cliente: Cliente, tracker: CostTracker, fallback: str = "Outros"
) -> int:
    """Embedding dos temas cujo texto (ou modelo) mudou. O tema de fallback fica sem vetor."""
    modelo = get_settings().embedding_model
    with engine.connect() as conn:
        temas = conn.execute(
            text(
                "SELECT nome, descricao, texto_hash FROM gold.dim_tema WHERE nome <> :f ORDER BY nome"
            ),
            {"f": fallback},
        ).all()
    pendentes = []
    for nome, descricao, h_atual in temas:
        t = texto_tema(nome, descricao)
        if (h := hash_texto(t, modelo)) != h_atual:
            pendentes.append((nome, t, h))
    if not pendentes:
        return 0
    tracker.check_projection(
        tracker.custo("embedding_tema", sum(estimate_tokens(p[1]) for p in pendentes))
    )
    vetores, tokens = cliente.embed([p[1] for p in pendentes])
    with engine.begin() as conn:
        for (nome, _, h), v in zip(pendentes, vetores, strict=True):
            conn.execute(
                text(
                    "UPDATE gold.dim_tema SET embedding = CAST(:v AS extensions.vector), modelo_embedding = :m, "
                    "texto_hash = :h, atualizado_em = now() WHERE nome = :n"
                ),
                {"v": vetor_sql(v), "m": modelo, "h": h, "n": nome},
            )
    tracker.add("embedding_tema", len(pendentes), tokens)
    log.info("temas: %d embedding(s) atualizados", len(pendentes))
    return len(pendentes)


def pendentes_proposicoes(engine: Engine, limit: int | None = None) -> list[tuple[int, str, str]]:
    """(id, texto, hash) das proposições relevantes sem embedding ou com texto alterado."""
    s = get_settings()
    with engine.connect() as conn:
        linhas = conn.execute(
            text(
                "SELECT f.id_proposicao, f.sigla_tipo, f.ementa, f.keywords, f.temas_oficiais, e.texto_hash "
                "FROM gold.fato_proposicao f LEFT JOIN gold.proposicao_embeddings e USING (id_proposicao) "
                "WHERE f.sigla_tipo = ANY(:tipos) AND f.ementa IS NOT NULL "
                "ORDER BY f.data_apresentacao DESC NULLS LAST, f.id_proposicao DESC"
            ),
            {"tipos": s.tipos_relevantes},
        ).all()
    saida = []
    for id_, tipo, ementa, keywords, temas, h_atual in linhas:
        t = texto_proposicao(tipo, ementa, keywords, temas)
        if (h := hash_texto(t, s.embedding_model)) != h_atual:
            saida.append((id_, t, h))
            if limit is not None and len(saida) >= limit:
                break
    return saida


def embed_proposicoes(
    engine: Engine, cliente: Cliente, tracker: CostTracker, limit: int | None = None
) -> int:
    s = get_settings()
    pendentes = pendentes_proposicoes(engine, limit)
    feitos = 0
    for i in range(0, len(pendentes), s.embedding_batch):
        lote = pendentes[i : i + s.embedding_batch]
        tracker.check_projection(
            tracker.custo("embedding", sum(estimate_tokens(p[1]) for p in lote))
        )
        vetores, tokens = cliente.embed([p[1] for p in lote])
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO gold.proposicao_embeddings (id_proposicao, embedding, modelo, texto_hash) "
                    "VALUES (:id, CAST(:v AS extensions.vector), :m, :h) ON CONFLICT (id_proposicao) DO UPDATE "
                    "SET embedding = EXCLUDED.embedding, modelo = EXCLUDED.modelo, "
                    "texto_hash = EXCLUDED.texto_hash, criado_em = now()"
                ),
                [{"id": id_, "v": vetor_sql(v), "m": s.embedding_model, "h": h}
                 for (id_, _, h), v in zip(lote, vetores, strict=True)],
            )  # fmt: skip
        tracker.add("embedding", len(lote), tokens)
        feitos += len(lote)
    if feitos:
        log.info("proposições: %d embedding(s) gravados", feitos)
    return feitos
