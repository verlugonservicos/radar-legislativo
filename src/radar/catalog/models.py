"""Modelo do catálogo de endpoints (`config/endpoints.yaml`, SPEC V3 seção 3.4)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Tipo = Literal["lista", "detalhe", "subrecurso", "referencia"]
Frequencia = Literal["diaria", "semanal", "mensal"]
TipoJanela = Literal["nenhuma", "periodo", "mensal", "legislatura"]
FiltroIds = Literal["ultima_execucao", "janela", "todos", "legislaturas_recentes"]

PLACEHOLDERS = {
    "inicio",
    "fim",
    "ano",
    "mes",
    "id_legislatura",
    "inicio_legislatura",
    "hoje",
    "id",
    "id_pai",
}
_RE_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
NOME_VALIDO = re.compile(r"^[a-z][a-z0-9_]*$")


def placeholders_em(valor: object) -> set[str]:
    """Placeholders `{nome}` usados num valor (texto, lista ou dicionário)."""
    if isinstance(valor, str):
        return set(_RE_PLACEHOLDER.findall(valor))
    if isinstance(valor, dict):
        return set().union(*(placeholders_em(v) for v in valor.values())) if valor else set()
    if isinstance(valor, list | tuple):
        return set().union(*(placeholders_em(v) for v in valor)) if valor else set()
    return set()


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Janela(_Base):
    """Como o período entra nos parâmetros da chamada."""

    tipo: TipoJanela = "nenhuma"
    params: dict[str, str] = Field(default_factory=dict)
    particao: Literal["diaria", "ano"] | None = None
    passes: list[dict[str, str]] = Field(default_factory=list)
    reprocessar_meses: int = Field(default=0, ge=0)


class OrigemIds(_Base):
    """De onde vêm os `{id}` de um detalhe ou sub-recurso."""

    de: list[str]
    campo: str = "id"
    filtro: FiltroIds = "ultima_execucao"
    # soma os deputados órfãos da Silver (SPEC 9.5) aos IDs da origem
    incluir_orfaos: bool = False

    @field_validator("de", mode="before")
    @classmethod
    def _aceita_texto(cls, valor: object) -> object:
        return [valor] if isinstance(valor, str) else valor


class EndpointSpec(_Base):
    """Uma entrada do catálogo = uma tabela `bronze.<nome>`."""

    nome: str
    path: str
    grupo: str
    tipo: Tipo
    paginado: bool = False
    itens: int = Field(default=100, ge=1, le=100)
    params: dict[str, str] = Field(default_factory=dict)
    janela: Janela = Field(default_factory=Janela)
    ids: OrigemIds | None = None
    frequencia: Frequencia = "diaria"
    chave: list[str] | Literal["objeto_unico", "sha256"] = "sha256"
    observacao: str | None = None
    revisar: bool = False
    obsoleto: bool = False

    @field_validator("nome")
    @classmethod
    def _nome_snake(cls, valor: str) -> str:
        if not NOME_VALIDO.match(valor):
            raise ValueError(f"nome inválido (use snake_case): {valor}")
        return valor

    @model_validator(mode="after")
    def _coerencia(self) -> EndpointSpec:
        tem_id = "{id}" in self.path
        if tem_id and self.ids is None:
            raise ValueError(f"{self.nome}: path com {{id}} exige `ids`")
        if not tem_id and self.ids is not None:
            raise ValueError(f"{self.nome}: `ids` só faz sentido em path com {{id}}")
        usados = placeholders_em(self.params) | placeholders_em(self.janela.model_dump())
        if isinstance(self.chave, list):
            usados |= placeholders_em(self.chave)
        invalidos = usados - PLACEHOLDERS
        if invalidos:
            raise ValueError(f"{self.nome}: placeholders desconhecidos {sorted(invalidos)}")
        return self


class Catalogo(_Base):
    """Arquivo `config/endpoints.yaml` completo."""

    versao: int
    defaults: dict[str, object] = Field(default_factory=dict)
    endpoints: list[EndpointSpec]

    @model_validator(mode="after")
    def _nomes_unicos(self) -> Catalogo:
        vistos: set[str] = set()
        for spec in self.endpoints:
            for chave, rotulo in ((spec.nome, "nome"), (spec.path, "path")):
                if chave in vistos:
                    raise ValueError(f"{rotulo} duplicado no catálogo: {chave}")
                vistos.add(chave)
        nomes = {s.nome for s in self.endpoints}
        for spec in self.endpoints:
            if spec.ids:
                faltando = set(spec.ids.de) - nomes
                if faltando:
                    raise ValueError(f"{spec.nome}: ids.de aponta para {sorted(faltando)}")
        return self
