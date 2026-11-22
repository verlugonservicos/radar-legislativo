"""Contexto e registro de execuções no schema `ops` (SPEC V3 seções 7 e 11.1)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Engine, text

from radar.config import Settings, get_settings

log = logging.getLogger("radar.ops")


@dataclass
class RunContext:
    """O que uma execução precisa saber: período, data de referência e conexão."""

    id_execucao: int
    modo: str
    start: date
    end: date
    hoje: date
    engine: Engine
    settings: Settings = field(default_factory=get_settings)
    etapas: dict[str, Any] = field(default_factory=dict)
    contagens: dict[str, Any] = field(default_factory=dict)

    def placeholders(self) -> dict[str, object]:
        """Valores fixos da execução para `{id_legislatura}`, `{inicio_legislatura}`, `{hoje}`."""
        return {
            "id_legislatura": self.settings.id_legislatura,
            "inicio_legislatura": self.settings.inicio_legislatura.isoformat(),
            "hoje": self.hoje.isoformat(),
        }


def start_run(
    engine: Engine,
    modo: str,
    start: date,
    end: date,
    origem: str = "cli",
    parametros: dict | None = None,
) -> RunContext:
    with engine.begin() as conn:
        id_execucao = conn.execute(
            text(
                "INSERT INTO ops.pipeline_execucoes (modo, origem, parametros) "
                "VALUES (:modo, :origem, CAST(:parametros AS jsonb)) RETURNING id_execucao"
            ),
            {
                "modo": modo,
                "origem": origem,
                "parametros": json.dumps(parametros or {}, default=str),
            },
        ).scalar_one()
    log.info("execução %s iniciada (%s, %s a %s)", id_execucao, modo, start, end)
    return RunContext(id_execucao, modo, start, end, date.today(), engine)


def finish_run(ctx: RunContext, status: str, erro: str | None = None) -> None:
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ops.pipeline_execucoes SET status = :status, etapas = CAST(:etapas AS jsonb), "
                "contagens = CAST(:contagens AS jsonb), erro = :erro, finalizado_em = now() "
                "WHERE id_execucao = :id"
            ),
            {
                "status": status,
                "etapas": json.dumps(ctx.etapas, default=str),
                "contagens": json.dumps(ctx.contagens, default=str),
                "erro": erro,
                "id": ctx.id_execucao,
            },
        )
    log.info("execução %s finalizada: %s", ctx.id_execucao, status)


def registrar_cobertura(ctx: RunContext, endpoint: str, **valores: object) -> None:
    """Soma contagens em `ops.cobertura_endpoints` (extração e carga escrevem na mesma linha)."""
    campos = ["chamadas", "paginas", "registros", "inseridos", "erros"]
    numeros = {c: int(valores.get(c, 0) or 0) for c in campos}
    observacao = valores.get("observacao")
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ops.cobertura_endpoints "
                "(id_execucao, endpoint, chamadas, paginas, registros, inseridos, erros, observacao) "
                "VALUES (:id, :endpoint, :chamadas, :paginas, :registros, :inseridos, :erros, :obs) "
                "ON CONFLICT (id_execucao, endpoint) DO UPDATE SET "
                "chamadas = ops.cobertura_endpoints.chamadas + EXCLUDED.chamadas, "
                "paginas = ops.cobertura_endpoints.paginas + EXCLUDED.paginas, "
                "registros = ops.cobertura_endpoints.registros + EXCLUDED.registros, "
                "inseridos = ops.cobertura_endpoints.inseridos + EXCLUDED.inseridos, "
                "erros = ops.cobertura_endpoints.erros + EXCLUDED.erros, "
                "observacao = COALESCE(EXCLUDED.observacao, ops.cobertura_endpoints.observacao)"
            ),
            {"id": ctx.id_execucao, "endpoint": endpoint, "obs": observacao, **numeros},
        )


def atualizar_watermark(ctx: RunContext, endpoint: str, camada: str, data_ref: date) -> None:
    with ctx.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ops.controle_ingestao (endpoint, camada, ultima_data_ref, ultima_execucao) "
                "VALUES (:e, :c, :d, :id) ON CONFLICT (endpoint, camada) DO UPDATE SET "
                "ultima_data_ref = GREATEST(ops.controle_ingestao.ultima_data_ref, EXCLUDED.ultima_data_ref), "
                "ultima_execucao = EXCLUDED.ultima_execucao, atualizado_em = now()"
            ),
            {"e": endpoint, "c": camada, "d": data_ref, "id": ctx.id_execucao},
        )


def ler_watermarks(engine: Engine, camada: str) -> dict[str, date]:
    with engine.connect() as conn:
        linhas = conn.execute(
            text("SELECT endpoint, ultima_data_ref FROM ops.controle_ingestao WHERE camada = :c"),
            {"c": camada},
        ).all()
    return {e: d for e, d in linhas}


def agora() -> datetime:
    return datetime.now(UTC)
