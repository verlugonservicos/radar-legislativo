"""Leitura do catálogo, ordem de dependência e frequência (SPEC V3 seção 4.3)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from radar.catalog.models import Catalogo, EndpointSpec
from radar.config import RAIZ_PROJETO

CATALOGO_PADRAO = RAIZ_PROJETO / "config" / "endpoints.yaml"


class CicloDeDependencia(ValueError):
    """`ids.de` forma um ciclo entre endpoints."""


def load_catalog(
    caminho: Path = CATALOGO_PADRAO, incluir_obsoletos: bool = False
) -> list[EndpointSpec]:
    """Lê e valida `endpoints.yaml`, aplicando `defaults` a cada entrada."""
    bruto = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    defaults = bruto.get("defaults") or {}
    bruto["endpoints"] = [{**defaults, **e} for e in bruto.get("endpoints") or []]
    catalogo = Catalogo.model_validate(bruto)
    return [s for s in catalogo.endpoints if incluir_obsoletos or not s.obsoleto]


def topological_levels(specs: list[EndpointSpec]) -> list[list[EndpointSpec]]:
    """Agrupa os endpoints em níveis: cada nível só depende dos anteriores."""
    por_nome = {s.nome: s for s in specs}
    deps = {s.nome: {d for d in (s.ids.de if s.ids else []) if d in por_nome} for s in specs}
    niveis: list[list[EndpointSpec]] = []
    resolvidos: set[str] = set()
    while len(resolvidos) < len(specs):
        prontos = sorted(n for n, d in deps.items() if n not in resolvidos and d <= resolvidos)
        if not prontos:
            pendentes = sorted(set(deps) - resolvidos)
            raise CicloDeDependencia(f"ciclo de dependência entre: {pendentes}")
        niveis.append([por_nome[n] for n in prontos])
        resolvidos.update(prontos)
    return niveis


def topological_order(specs: list[EndpointSpec]) -> list[EndpointSpec]:
    """Lista plana na ordem de execução."""
    return [s for nivel in topological_levels(specs) for s in nivel]


def due(
    spec: EndpointSpec, hoje: date, primeira_execucao: bool = False, force: bool = False
) -> bool:
    """O endpoint deve rodar hoje? Semanal = domingo; mensal = dia 1."""
    if force or primeira_execucao or spec.frequencia == "diaria":
        return True
    if spec.frequencia == "semanal":
        return hoje.weekday() == 6
    return hoje.day == 1
