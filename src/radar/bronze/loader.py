"""Landing → Bronze: payload integral, append-only, idempotente por hash (SPEC V3 seção 6.2)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, text

from radar.catalog.models import EndpointSpec
from radar.config import get_settings
from radar.extract.ids import extrair_campo
from radar.logging_setup import log_contexto

log = logging.getLogger("radar.bronze")

LOTE = 1000
COLUNAS = (
    "endpoint", "chave_registro", "id_pai", "payload", "payload_hash", "url",
    "parametros", "pagina", "arquivo_origem", "id_execucao", "extraido_em",
)  # fmt: skip


@dataclass
class LoadResult:
    endpoint: str
    arquivos: int = 0
    lidos: int = 0
    inseridos: int = 0

    @property
    def ignorados(self) -> int:
        return self.lidos - self.inseridos


def canonico(registro: object) -> str:
    return json.dumps(registro, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def payload_hash(registro: object) -> str:
    return hashlib.sha256(canonico(registro).encode("utf-8")).hexdigest()


def chave_registro(spec: EndpointSpec, registro: object, id_pai: str | None) -> str:
    """Aplica `spec.chave`: campos com `.`/`[]`, `{id_pai}`; nulos viram ''."""
    if spec.chave == "sha256":
        return payload_hash(registro)
    if spec.chave == "objeto_unico":
        return id_pai or "objeto_unico"
    partes = []
    for campo in spec.chave:
        if campo == "{id_pai}":
            partes.append(id_pai or "")
        else:
            valores = extrair_campo(registro, campo)
            partes.append(str(valores[0]) if valores else "")
    return "|".join(partes)


def linhas_do_envelope(
    spec: EndpointSpec, envelope: dict, arquivo: Path, raiz: Path
) -> Iterator[tuple]:
    """Uma linha por elemento de `dados` (lista) ou uma linha (objeto)."""
    meta = envelope["_meta"]
    dados = envelope["resposta"].get("dados")
    registros = dados if isinstance(dados, list) else ([dados] if dados else [])
    try:
        origem = str(arquivo.relative_to(raiz))
    except ValueError:
        origem = str(arquivo)
    parametros = json.dumps(meta.get("params"), ensure_ascii=False) if meta.get("params") else None
    for registro in registros:
        yield (
            spec.path, chave_registro(spec, registro, meta.get("id_pai")), meta.get("id_pai"),
            canonico(registro), payload_hash(registro), meta["url"], parametros,
            meta.get("pagina"), origem, meta["id_execucao"], meta["extraido_em"],
        )  # fmt: skip


def _inserir_lote(engine: Engine, tabela: str, linhas: list[tuple]) -> int:
    """COPY para uma tabela temporária + INSERT … ON CONFLICT DO NOTHING."""
    with engine.begin() as conn:
        driver = conn.connection.driver_connection
        with driver.cursor() as cur:
            cur.execute(
                f"CREATE TEMP TABLE IF NOT EXISTS _carga (LIKE bronze.{tabela} INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
            cur.execute("TRUNCATE _carga")
            with cur.copy(f"COPY _carga ({', '.join(COLUNAS)}) FROM STDIN") as copia:
                for linha in linhas:
                    copia.write_row(linha)
            cur.execute(
                f"INSERT INTO bronze.{tabela} ({', '.join(COLUNAS)}) "
                f"SELECT {', '.join(COLUNAS)} FROM _carga "
                f"ON CONFLICT ON CONSTRAINT uq_{tabela}_versao DO NOTHING"
            )
            return cur.rowcount


def load_endpoint(
    spec: EndpointSpec,
    engine: Engine,
    arquivos: Iterable[tuple[Path, dict]],
    id_execucao: int | None = None,
) -> LoadResult:
    """Carrega os arquivos da Landing informados na tabela `bronze.<nome>`."""
    resultado = LoadResult(spec.nome)
    raiz = get_settings().landing_dir
    lote: list[tuple] = []
    with log_contexto(run=id_execucao or "-", camada="bronze", endpoint=spec.nome):
        for arquivo, envelope in arquivos:
            resultado.arquivos += 1
            for linha in linhas_do_envelope(spec, envelope, arquivo, raiz):
                lote.append(linha)
                if len(lote) >= LOTE:
                    resultado.inseridos += _inserir_lote(engine, spec.nome, lote)
                    resultado.lidos += len(lote)
                    lote = []
        if lote:
            resultado.inseridos += _inserir_lote(engine, spec.nome, lote)
            resultado.lidos += len(lote)
        log.info(
            "%s: %d arquivos, %d registros lidos, %d versões novas, %d idênticas ignoradas",
            spec.nome, resultado.arquivos, resultado.lidos, resultado.inseridos, resultado.ignorados,
        )  # fmt: skip
    return resultado


def aplicar_retencao(engine: Engine, spec: EndpointSpec, dias: int) -> int:
    """Remove versões não correntes mais antigas que `dias` (0 = mantém todas)."""
    if dias <= 0:
        return 0
    with engine.begin() as conn:
        resultado = conn.execute(
            text(
                f"DELETE FROM bronze.{spec.nome} b WHERE b.carregado_em < now() - make_interval(days => :d) "
                f"AND b.id NOT IN (SELECT id FROM bronze.vw_{spec.nome}_atual)"
            ),
            {"d": dias},
        )
        return resultado.rowcount
