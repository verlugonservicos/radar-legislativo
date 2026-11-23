"""Motor da Silver: Bronze (versão atual) → entidades limpas (SPEC V3 seção 8).

Por entidade: lê só as versões novas desde a última watermark (`ops.controle_ingestao`,
camada `silver`), mapeia cada fonte, tipa, aplica a transformação, valida (com quarentena),
deduplica pela PK e grava por UPSERT. Devolve a reconciliação
`lidos = gravados + rejeitados + duplicados`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass

import pandas as pd
from sqlalchemy import Engine, text

from radar.logging_setup import log_contexto
from radar.silver.base import gerar_ddl, mapear, read_bronze, tipar, upsert
from radar.silver.entities import entidades as todas_entidades
from radar.silver.spec import Entidade
from radar.silver.validators import deduplicate, not_null, quarantine, validate

log = logging.getLogger("radar.silver")


@dataclass
class SilverResult:
    entidade: str
    lidos: int = 0
    gravados: int = 0
    rejeitados: int = 0  # registros distintos rejeitados
    duplicados: int = 0
    incremental: bool = False
    duracao_s: float = 0.0
    regras: dict | None = None
    avisos: dict | None = None

    @property
    def reconciliado(self) -> bool:
        return self.lidos == self.gravados + self.rejeitados + self.duplicados


def criar_tabelas(engine: Engine, entidades: list[Entidade] | None = None) -> int:
    entidades = entidades or todas_entidades()
    ddl = "CREATE SCHEMA IF NOT EXISTS silver;\n" + "\n".join(gerar_ddl(e) for e in entidades)
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cur:
        cur.execute(ddl)
    log.info("silver: %d tabelas verificadas", len(entidades))
    return len(entidades)


def _watermark(engine: Engine, entidade: str):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT ultimo_carregado_em FROM ops.controle_ingestao WHERE endpoint = :e AND camada = 'silver'"
            ),
            {"e": entidade},
        ).scalar_one_or_none()


def _gravar_watermark(engine: Engine, entidade: str, instante, id_execucao: int | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ops.controle_ingestao (endpoint, camada, ultima_data_ref, ultima_execucao, ultimo_carregado_em) "
                "VALUES (:e, 'silver', CAST(:t AS date), :id, :t) ON CONFLICT (endpoint, camada) DO UPDATE SET "
                "ultima_data_ref = EXCLUDED.ultima_data_ref, ultima_execucao = EXCLUDED.ultima_execucao, "
                "ultimo_carregado_em = GREATEST(ops.controle_ingestao.ultimo_carregado_em, EXCLUDED.ultimo_carregado_em), "
                "atualizado_em = now()"
            ),
            {"e": entidade, "t": instante, "id": id_execucao},
        )


def processar(
    engine: Engine,
    entidade: Entidade,
    id_execucao: int | None = None,
    completa: bool = False,
    cache: dict[str, pd.DataFrame] | None = None,
) -> SilverResult:
    """Processa uma entidade de ponta a ponta."""
    t0 = time.monotonic()
    desde = None if (completa or entidade.completa) else _watermark(engine, entidade.nome)
    resultado = SilverResult(entidade.nome, incremental=desde is not None)
    cache = cache if cache is not None else {}
    with log_contexto(run=id_execucao or "-", camada="silver", endpoint=entidade.nome):
        partes, maximo = [], None
        for fonte in entidade.fontes:
            chave_cache = f"{fonte.bronze}|{desde}"
            if chave_cache not in cache:
                cache[chave_cache] = read_bronze(engine, fonte.bronze, desde)
            bruto = cache[chave_cache]
            if not bruto.empty:
                m = bruto["_carregado_em"].max()
                maximo = m if maximo is None or m > maximo else maximo
            partes.append(mapear(bruto, fonte, entidade))
        df = (
            pd.concat([p for p in partes if not p.empty], ignore_index=True)
            if any(not p.empty for p in partes)
            else pd.DataFrame()
        )
        resultado.lidos = len(df)
        if df.empty:
            log.info("%s: nada novo na Bronze", entidade.nome)
            resultado.duracao_s = round(time.monotonic() - t0, 2)
            return resultado

        df = tipar(df, entidade.tipos)
        if entidade.transformar is not None:
            df = entidade.transformar(df)
        regras = [not_null(*entidade.pk), *entidade.regras]
        validacao = validate(df, regras, entidade.nome)
        quarantine(engine, validacao, entidade.nome, entidade.pk, id_execucao)
        resultado.rejeitados = len(df) - len(validacao.validos)
        validos, resultado.duplicados = deduplicate(validacao.validos, entidade.pk)
        resultado.gravados = upsert(engine, entidade, validos)
        resultado.regras, resultado.avisos = validacao.resumo or None, validacao.avisos or None
        if maximo is not None:
            _gravar_watermark(engine, entidade.nome, maximo.to_pydatetime(), id_execucao)
        resultado.duracao_s = round(time.monotonic() - t0, 2)
        log.info(
            "%s: %d lidos → %d gravados, %d rejeitados, %d duplicados%s (%.1f s)",
            entidade.nome, resultado.lidos, resultado.gravados, resultado.rejeitados, resultado.duplicados,
            " [incremental]" if resultado.incremental else "", resultado.duracao_s,
        )  # fmt: skip
        if resultado.regras:
            log.info("%s: rejeições por regra %s", entidade.nome, resultado.regras)
    return resultado


def run_silver(
    engine: Engine,
    id_execucao: int | None = None,
    nomes: set[str] | None = None,
    completa: bool = False,
) -> dict[str, dict]:
    """Todas as entidades (ou as pedidas). Falha numa entidade não derruba as outras."""
    cache: dict[str, pd.DataFrame] = {}
    contagens: dict[str, dict] = {}
    for entidade in todas_entidades():
        if nomes and entidade.nome not in nomes:
            continue
        try:
            r = processar(engine, entidade, id_execucao, completa, cache)
            contagens[entidade.nome] = {**asdict(r), "reconciliado": r.reconciliado}
        except Exception as erro:
            log.exception("%s: falha na Silver", entidade.nome)
            contagens[entidade.nome] = {"falha": str(erro)[:300]}
    return contagens
