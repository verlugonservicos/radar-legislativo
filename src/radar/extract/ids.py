"""Resolução dos `{id}` de detalhes e sub-recursos (SPEC V3 seção 5.4; ADR-020).

Fonte preferida: os arquivos da Landing gravados **nesta execução** pelo endpoint de origem.
Assim registros que não mudaram (e por isso não geram nova versão na Bronze) continuam
fornecendo IDs. Se a origem não rodou nesta execução (frequência), usa a versão corrente da
Bronze (`bronze.vw_<origem>_atual`).
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text

from radar.catalog.models import EndpointSpec
from radar.extract import landing
from radar.run_context import RunContext

log = logging.getLogger("radar.extract.ids")
_MIN, _MAX = date.min, date.max


def extrair_campo(registro: object, campo: str) -> list:
    """`id`, `parlamentar.id` ou `orgaos[].id` → lista de valores não nulos."""
    if not isinstance(registro, dict):
        return []
    if "[]." in campo:
        lista, resto = campo.split("[].", 1)
        return [v for item in registro.get(lista) or [] for v in extrair_campo(item, resto)]
    valor: object = registro
    for parte in campo.split("."):
        valor = valor.get(parte) if isinstance(valor, dict) else None
    return [] if valor in (None, "") else [valor]


def _registros(dados: object) -> list:
    return dados if isinstance(dados, list) else [dados] if isinstance(dados, dict) else []


def _da_landing(origem: str, campo: str, ctx: RunContext) -> list | None:
    ids: list = []
    achou = False
    for _, envelope in landing.iter_files(origem, _MIN, _MAX, id_execucao=ctx.id_execucao):
        achou = True
        for registro in _registros(envelope["resposta"].get("dados")):
            ids.extend(extrair_campo(registro, campo))
    return ids if achou else None


def _da_bronze(origem: str, campo: str, ctx: RunContext) -> list:
    with ctx.engine.connect() as conn:
        payloads = conn.execute(text(f"SELECT payload FROM bronze.vw_{origem}_atual")).scalars()
        return [v for p in payloads for v in extrair_campo(p, campo)]


def resolve_ids(spec: EndpointSpec, ctx: RunContext) -> list[str]:
    """IDs únicos (como texto), na ordem em que aparecem."""
    if spec.ids is None:
        return []
    vistos: dict[str, None] = {}
    for origem in spec.ids.de:
        ids = None if spec.ids.filtro == "todos" else _da_landing(origem, spec.ids.campo, ctx)
        if ids is None:
            ids = _da_bronze(origem, spec.ids.campo, ctx)
            log.debug("%s: IDs de %s vindos da Bronze (%d)", spec.nome, origem, len(ids))
        for valor in ids:
            vistos.setdefault(str(valor), None)
    resultado = list(vistos)
    if spec.ids.filtro == "legislaturas_recentes":
        minimo = ctx.settings.id_legislatura - 2
        resultado = [i for i in resultado if i.isdigit() and int(i) >= minimo]
    return resultado
