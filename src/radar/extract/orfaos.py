"""Deputados órfãos (SPEC V3 9.5): citados na Silver (votos, autorias, presenças) sem cadastro.

Na execução seguinte, os endpoints com `ids.incluir_orfaos` (detalhe e histórico do deputado)
buscam esses IDs à força, para que a Gold consiga ligar o voto/autoria a `dim_deputado`.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

log = logging.getLogger("radar.extract.orfaos")

# (tabela Silver, coluna) que referenciam deputados
REFERENCIAS = [
    ("votos", "id_deputado"),
    ("proposicoes_autores", "id_deputado"),
    ("eventos_deputados", "id_deputado"),
]
LIMITE = 2000  # teto por execução; o restante fica para a próxima


def deputados_orfaos(engine: Engine, limite: int = LIMITE) -> list[str]:
    """IDs (texto) referenciados na Silver e ausentes de `silver.deputados`, mais recentes primeiro."""
    with engine.connect() as conn:
        if conn.execute(text("SELECT to_regclass('silver.deputados')")).scalar() is None:
            return []
        existentes = [
            (t, c)
            for t, c in REFERENCIAS
            if conn.execute(text(f"SELECT to_regclass('silver.{t}')")).scalar() is not None
        ]
        if not existentes:
            return []
        uniao = " UNION ".join(
            f"SELECT {c} AS id FROM silver.{t} WHERE {c} IS NOT NULL" for t, c in existentes
        )
        sql = (
            f"SELECT r.id FROM ({uniao}) r "
            "WHERE NOT EXISTS (SELECT 1 FROM silver.deputados d WHERE d.id_deputado = r.id) "
            "ORDER BY r.id DESC LIMIT :limite"
        )
        ids = [str(i) for i in conn.execute(text(sql), {"limite": limite}).scalars()]
    if ids:
        log.info("%d deputado(s) órfão(s) na Silver serão buscados nesta execução", len(ids))
    return ids
