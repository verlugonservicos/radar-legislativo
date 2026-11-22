"""Gera `docs/dicionario_de_dados.md` a partir do catálogo e das fixtures reais (M1).

Todos os campos vão para a Bronze (payload integral). O dicionário mostra, por endpoint,
os campos observados na amostra, o tipo, se vieram nulos e para quais tabelas Silver o
endpoint alimenta (`config/destino_silver.yaml`).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import yaml

from radar.catalog.amostras import FIXTURES
from radar.catalog.loader import load_catalog
from radar.catalog.models import EndpointSpec
from radar.config import RAIZ_PROJETO

DESTINO = RAIZ_PROJETO / "config" / "destino_silver.yaml"
SAIDA = RAIZ_PROJETO / "docs" / "dicionario_de_dados.md"
FREQ = {"diaria": "diária", "semanal": "semanal", "mensal": "mensal"}
TIPOS = {"str": "texto", "int": "inteiro", "float": "decimal", "bool": "booleano",
         "list": "lista", "dict": "objeto", "NoneType": "nulo"}  # fmt: skip
GRUPOS = ["referencias", "legislaturas", "partidos", "blocos", "deputados", "orgaos",
          "eventos", "frentes", "grupos", "proposicoes", "votacoes"]  # fmt: skip


def _achatar(registro: dict, prefixo: str = "") -> dict[str, object]:
    """Campos aninhados viram `pai.filho`; listas de objetos viram `lista[].campo`."""
    campos: dict[str, object] = {}
    for chave, valor in registro.items():
        nome = f"{prefixo}{chave}"
        if isinstance(valor, dict) and valor:
            campos.update(_achatar(valor, f"{nome}."))
        elif isinstance(valor, list) and valor and isinstance(valor[0], dict):
            campos[nome] = valor
            campos.update(_achatar(valor[0], f"{nome}[]."))
        else:
            campos[nome] = valor
    return campos


def perfil_campos(dados: object) -> list[tuple[str, str, int, int, str]]:
    """(campo, tipo, nulos, total, exemplo) a partir dos registros da amostra."""
    if isinstance(dados, dict) and all(isinstance(v, list) for v in dados.values()):
        # agregada de referências: {lista: [...]} → perfil de cada lista
        registros = [{k: v[0] if v else None} for k, v in dados.items()]
    else:
        registros = dados if isinstance(dados, list) else [dados]
    vistos: dict[str, list] = defaultdict(list)
    for r in registros:
        for campo, valor in _achatar(r).items():
            vistos[campo].append(valor)
    linhas = []
    for campo, valores in vistos.items():
        nao_nulos = [v for v in valores if v not in (None, "", [])]
        tipo = TIPOS.get(type(nao_nulos[0]).__name__, "?") if nao_nulos else "nulo"
        exemplo = (
            "" if not nao_nulos or isinstance(nao_nulos[0], list | dict) else str(nao_nulos[0])
        )
        exemplo = (exemplo[:40] + "…") if len(exemplo) > 41 else exemplo
        linhas.append((campo, tipo, len(valores) - len(nao_nulos), len(valores), exemplo))
    return linhas


def _md(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def _secao(spec: EndpointSpec, destinos: dict, somente_bronze: dict) -> list[str]:
    fx = json.loads((FIXTURES / f"{spec.nome}.json").read_text(encoding="utf-8"))
    meta = fx["_meta"]
    chave = spec.chave if isinstance(spec.chave, str) else ", ".join(spec.chave)
    destino = destinos.get(spec.nome) or (["referencias"] if spec.grupo == "referencias" else ["—"])
    linhas = [
        f"### `bronze.{spec.nome}`",
        "",
        f"`GET {spec.path}` · {spec.tipo} · {FREQ[spec.frequencia]}"
        f"{' · paginado' if spec.paginado else ''} · chave: `{chave}`",
        "",
        f"**Destino na Silver:** {', '.join(f'`silver.{d}`' for d in destino)}",
    ]
    if spec.nome in somente_bronze:
        campos = ", ".join(f"`{c}`" for c in somente_bronze[spec.nome])
        linhas.append(f"**Fica só na Bronze:** {campos} (dado pessoal sem uso no produto)")
    if spec.observacao:
        linhas.append(f"**Observação:** {_md(spec.observacao)}")
    linhas += [
        "",
        f"Amostra: {meta['registros_originais']} registro(s) na resposta de {meta['coletado_em']}"
        f" ({min(meta['registros_originais'], 5)} na fixture).",
        "",
        "| Campo | Tipo | Nulos na amostra | Exemplo |",
        "|-------|------|------------------|---------|",
    ]
    for campo, tipo, nulos, total, exemplo in perfil_campos(fx["dados"]):
        linhas.append(f"| `{campo}` | {tipo} | {nulos}/{total} | {_md(exemplo)} |")
    return linhas + [""]


def gerar(saida: Path = SAIDA) -> Path:
    specs = load_catalog()
    cfg = yaml.safe_load(DESTINO.read_text(encoding="utf-8"))
    destinos, somente_bronze = cfg["destinos"], cfg.get("somente_bronze", {})
    linhas = [
        "# Dicionário de dados — Bronze → Silver",
        "",
        "Gerado por `python -m radar catalog dicionario` a partir de `config/endpoints.yaml`, "
        "`config/destino_silver.yaml` e das respostas reais em `tests/fixtures/api/`. "
        "**Todos os campos vão para a Bronze** (payload JSONB integral); esta página mostra "
        "os campos observados na amostra e para onde cada endpoint segue na Silver. Campos "
        "aninhados aparecem como `pai.filho` e listas de objetos como `lista[].campo`.",
        "",
        f"Cobertura: **{len(specs)} endpoints**.",
        "",
        "## Resumo",
        "",
        "| Grupo | Endpoint (tabela Bronze) | Tipo | Frequência | Destino na Silver |",
        "|-------|--------------------------|------|------------|-------------------|",
    ]
    ordenados = sorted(specs, key=lambda s: (GRUPOS.index(s.grupo), "{id}" in s.path, s.path))
    for s in ordenados:
        destino = destinos.get(s.nome) or (["referencias"] if s.grupo == "referencias" else ["—"])
        linhas.append(
            f"| {s.grupo} | [`{s.nome}`](#bronze{s.nome.replace('_', '')}) | {s.tipo} | "
            f"{FREQ[s.frequencia]} | {', '.join(destino)} |"
        )
    grupo_atual = None
    for s in ordenados:
        if s.grupo != grupo_atual:
            grupo_atual = s.grupo
            linhas += ["", f"## {s.grupo.capitalize()}", ""]
        linhas += _secao(s, destinos, somente_bronze)
    saida.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")
    return saida
