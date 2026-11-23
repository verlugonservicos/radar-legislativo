"""Modelo declarativo das entidades Silver.

Cada entidade diz de quais tabelas Bronze vem, como cada coluna é obtida do payload e quais
regras de qualidade valem. O motor (`silver/runner.py`) faz o resto: lê a versão atual da
Bronze, mapeia, tipa, une as fontes, valida, deduplica e grava por UPSERT.

Mapeamento de coluna (`Fonte.colunas`): `"alvo": "caminho"` com caminhos do payload achatado
(`ultimoStatus.siglaUf`, `deputado_.id`) ou expressões especiais:
- `@id_pai`  — ID do pai na Bronze (sub-recursos);
- `@id:<caminho>` — último segmento numérico de uma URI (`@id:uriPartido`);
- `@const:<valor>` — valor fixo (ex.: o papel da proposição numa votação);
- `@endpoint` — nome da tabela Bronze de origem.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

# Tipos Silver → tipo PostgreSQL
TIPOS_SQL = {
    "int": "INTEGER",
    "bigint": "BIGINT",
    "num": "NUMERIC(14,2)",
    "text": "TEXT",
    "date": "DATE",
    "ts": "TIMESTAMPTZ",
    "bool": "BOOLEAN",
    "text[]": "TEXT[]",
}


@dataclass
class Fonte:
    """Uma tabela Bronze que alimenta a entidade."""

    bronze: str
    colunas: dict[str, str]
    explodir: str | None = None  # lista de objetos a desmembrar (ex.: "membros")
    prioridade: int = 0  # maior vence quando duas fontes trazem a mesma chave
    filtro: Callable[[pd.DataFrame], pd.Series] | None = None


@dataclass
class Entidade:
    nome: str  # tabela silver.<nome>
    pk: list[str]
    tipos: dict[str, str]  # coluna → tipo (TIPOS_SQL); define a ordem das colunas
    fontes: list[Fonte]
    regras: list = field(default_factory=list)  # validators.Rule
    conformada: bool = False  # une relações espelhadas (documentação)
    transformar: Callable[[pd.DataFrame], pd.DataFrame] | None = None  # ajuste final opcional
    completa: bool = False  # sempre relê tudo (sem incremental)

    @property
    def colunas(self) -> list[str]:
        return list(self.tipos)

    def __post_init__(self) -> None:
        faltando = [c for c in self.pk if c not in self.tipos]
        if faltando:
            raise ValueError(f"{self.nome}: PK fora de `tipos`: {faltando}")
        for f in self.fontes:
            extras = set(f.colunas) - set(self.tipos)
            if extras:
                raise ValueError(f"{self.nome}/{f.bronze}: colunas sem tipo {sorted(extras)}")
