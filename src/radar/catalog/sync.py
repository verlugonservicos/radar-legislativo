"""Sincroniza o catálogo com o OpenAPI oficial da Câmara (SPEC V3 seção 4.3)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

from radar.catalog.loader import CATALOGO_PADRAO
from radar.config import RAIZ_PROJETO, get_settings

log = logging.getLogger("radar.catalog")

OPENAPI_PADRAO = RAIZ_PROJETO / "config" / "openapi_camara.json"

CABECALHO = """\
# =============================================================================
# Catálogo dos endpoints da API de Dados Abertos da Câmara (SPEC V3, seções 3.4 e 4)
# Cada entrada = uma tabela bronze.<nome>. Gerado por `radar catalog sync` e
# revisado à mão: ajustes manuais são preservados nas próximas sincronizações.
# Entradas novas da API chegam com `revisar: true`; removidas ficam `obsoleto: true`.
# =============================================================================
"""


# ------------------------------------------------------------------ nomes
def _snake(texto: str) -> str:
    texto = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", texto)
    texto = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", texto)
    return texto.lower()


def nome_do_path(path: str) -> str:
    """Regra da SPEC: sem `/` e `{id}`; `/`→`_`; camelCase→snake_case; `/x/{id}`→`x_detalhe`."""
    partes = [p for p in path.strip("/").split("/") if p]
    detalhe = len(partes) == 2 and partes[1] == "{id}"
    nome = "_".join(_snake(p) for p in partes if p != "{id}")
    return f"{nome}_detalhe" if detalhe else nome


def tipo_do_path(path: str) -> str:
    partes = [p for p in path.strip("/").split("/") if p]
    if partes[0] == "referencias":
        return "referencia"
    if "{id}" not in partes:
        return "lista"
    return "detalhe" if partes[-1] == "{id}" else "subrecurso"


# ------------------------------------------------------------------ OpenAPI
def baixar_openapi(destino: Path = OPENAPI_PADRAO, url: str | None = None) -> dict:
    """Baixa a especificação oficial e grava formatada (diff legível no Git)."""
    settings = get_settings()
    resposta = requests.get(
        url or settings.camara_openapi_url,
        headers={"User-Agent": settings.camara_user_agent, "Accept": "application/json"},
        timeout=(settings.camara_timeout_connect, settings.camara_timeout_read),
    )
    resposta.raise_for_status()
    spec = resposta.json()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return spec


def ler_openapi(caminho: Path = OPENAPI_PADRAO) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


def paths_get(openapi: dict) -> dict[str, list[str]]:
    """{path: [nomes dos parâmetros]} dos paths com GET."""
    resultado = {}
    for path, metodos in openapi.get("paths", {}).items():
        if "get" in metodos:
            params = [p.get("name") for p in metodos["get"].get("parameters", []) if p.get("name")]
            resultado[path] = params
    return dict(sorted(resultado.items()))


def entrada_sugerida(path: str, params: list[str]) -> dict:
    """Entrada mínima para um path novo, a ser revisada à mão."""
    partes = path.strip("/").split("/")
    entrada: dict = {
        "nome": nome_do_path(path),
        "path": path,
        "grupo": partes[0],
        "tipo": tipo_do_path(path),
        "paginado": "pagina" in params,
        "frequencia": "semanal",
    }
    if "dataInicio" in params:
        entrada["janela"] = {
            "tipo": "periodo",
            "params": {"dataInicio": "{inicio}", "dataFim": "{fim}"},
        }
    elif "ano" in params and "mes" in params:
        entrada["janela"] = {"tipo": "mensal", "params": {"ano": "{ano}", "mes": "{mes}"}}
    if "{id}" in path:
        pai = nome_do_path("/" + partes[0])
        entrada["ids"] = {"de": pai, "campo": "id", "filtro": "ultima_execucao"}
    entrada["revisar"] = True
    return entrada


# ------------------------------------------------------------------ sincronização
@dataclass
class RelatorioSync:
    total_api: int = 0
    mantidos: list[str] = field(default_factory=list)
    novos: list[str] = field(default_factory=list)
    obsoletos: list[str] = field(default_factory=list)
    reativados: list[str] = field(default_factory=list)

    def texto(self) -> str:
        linhas = [
            f"paths GET no OpenAPI: {self.total_api}",
            f"mantidos: {len(self.mantidos)}",
            f"novos (revisar): {len(self.novos)} {self.novos or ''}",
            f"marcados obsoletos: {len(self.obsoletos)} {self.obsoletos or ''}",
        ]
        if self.reativados:
            linhas.append(f"reativados: {self.reativados}")
        return "\n".join(linhas)


def mesclar(openapi: dict, existente: dict | None) -> tuple[dict, RelatorioSync]:
    """Preserva entradas existentes, acrescenta as novas e marca as removidas."""
    api = paths_get(openapi)
    rel = RelatorioSync(total_api=len(api))
    catalogo = existente or {
        "versao": 2,
        "defaults": {"paginado": False, "itens": 100},
        "endpoints": [],
    }
    por_path = {e["path"]: e for e in catalogo.get("endpoints", [])}

    for path, entrada in por_path.items():
        if path in api:
            if entrada.pop("obsoleto", False):
                rel.reativados.append(entrada["nome"])
            rel.mantidos.append(entrada["nome"])
        else:
            entrada["obsoleto"] = True
            rel.obsoletos.append(entrada["nome"])
    for path, params in api.items():
        if path not in por_path:
            nova = entrada_sugerida(path, params)
            catalogo["endpoints"].append(nova)
            rel.novos.append(nova["nome"])
    return catalogo, rel


def gravar_catalogo(catalogo: dict, destino: Path = CATALOGO_PADRAO) -> None:
    corpo = yaml.safe_dump(catalogo, allow_unicode=True, sort_keys=False, width=110)
    destino.write_text(CABECALHO + corpo, encoding="utf-8")


def sync(
    baixar: bool = True, destino: Path = CATALOGO_PADRAO, openapi_path: Path = OPENAPI_PADRAO
) -> RelatorioSync:
    """`radar catalog sync`: baixa o OpenAPI (opcional) e atualiza o catálogo."""
    openapi = baixar_openapi(openapi_path) if baixar else ler_openapi(openapi_path)
    existente = yaml.safe_load(destino.read_text(encoding="utf-8")) if destino.exists() else None
    catalogo, rel = mesclar(openapi, existente)
    gravar_catalogo(catalogo, destino)
    log.info("catálogo sincronizado\n%s", rel.texto())
    return rel


# ------------------------------------------------------------------ verificação
@dataclass
class Cobertura:
    api: set[str]
    catalogo: set[str]

    @property
    def faltando(self) -> set[str]:
        return self.api - self.catalogo

    @property
    def sobrando(self) -> set[str]:
        return self.catalogo - self.api

    @property
    def ok(self) -> bool:
        return not self.faltando and not self.sobrando


def cobertura(openapi: dict, specs: list) -> Cobertura:
    """Compara os paths GET do OpenAPI com os paths ativos do catálogo."""
    return Cobertura(
        api=set(paths_get(openapi)), catalogo={s.path for s in specs if not s.obsoleto}
    )
