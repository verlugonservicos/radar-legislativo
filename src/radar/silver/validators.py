"""Regras de qualidade, deduplicação e quarentena da Silver (SPEC V3 8.1 e 8.3)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import Engine, text

from radar.config import get_settings

log = logging.getLogger("radar.silver.qualidade")

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
    "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}  # fmt: skip


@dataclass
class Rule:
    nome: str
    descricao: str
    fn: Callable[[pd.DataFrame], pd.Series]  # True = linha INVÁLIDA
    rejeita: bool = True  # False = só registra aviso


@dataclass
class ValidationResult:
    validos: pd.DataFrame
    rejeitados: pd.DataFrame  # uma linha por (registro, regra violada)
    resumo: dict[str, int] = field(default_factory=dict)
    avisos: dict[str, int] = field(default_factory=dict)


def not_null(*cols: str) -> Rule:
    return Rule(
        f"not_null({','.join(cols)})",
        f"obrigatórios: {', '.join(cols)}",
        lambda df: df[list(cols)].isna().any(axis=1),
    )


def date_between(col: str, minimo: date, maximo: date, allow_null: bool = True) -> Rule:
    def fn(df: pd.DataFrame) -> pd.Series:
        s = pd.to_datetime(df[col], errors="coerce", utc=True)
        fora = (s < pd.Timestamp(minimo, tz="UTC")) | (s > pd.Timestamp(maximo, tz="UTC"))
        return fora | (s.isna() if not allow_null else False)

    return Rule(f"date_between({col})", f"{col} entre {minimo} e {maximo}", fn)


def non_negative(col: str) -> Rule:
    return Rule(
        f"non_negative({col})",
        f"{col} >= 0",
        lambda df: pd.to_numeric(df[col], errors="coerce") < 0,
    )


def in_set(col: str, valores: set, allow_null: bool = True, rejeita: bool = True) -> Rule:
    def fn(df: pd.DataFrame) -> pd.Series:
        fora = ~df[col].isin(valores)
        return fora & df[col].notna() if allow_null else fora

    return Rule(f"in_set({col})", f"{col} em {sorted(map(str, valores))[:8]}", fn, rejeita)


def between(col: str, minimo: float, maximo: float) -> Rule:
    def fn(df: pd.DataFrame) -> pd.Series:
        s = pd.to_numeric(df[col], errors="coerce")
        return (s < minimo) | (s > maximo)

    return Rule(f"between({col})", f"{col} entre {minimo} e {maximo}", fn)


def validate(df: pd.DataFrame, rules: list[Rule], entidade: str) -> ValidationResult:
    """Aplica as regras: linha que falha em qualquer regra rejeitável sai do conjunto válido."""
    invalido = pd.Series(False, index=df.index)
    rejeitados, resumo, avisos = [], {}, {}
    for regra in rules:
        falhas = regra.fn(df).fillna(False).astype(bool)
        n = int(falhas.sum())
        if not n:
            continue
        if regra.rejeita:
            resumo[regra.nome] = n
            invalido |= falhas
            r = df[falhas].copy()
            r["_regra"] = regra.nome
            rejeitados.append(r)
        else:
            avisos[regra.nome] = n
            log.warning("%s: %d registros com aviso em %s", entidade, n, regra.nome)
    return ValidationResult(
        validos=df[~invalido],
        rejeitados=pd.concat(rejeitados) if rejeitados else df.iloc[0:0].assign(_regra=None),
        resumo=resumo,
        avisos=avisos,
    )


def deduplicate(df: pd.DataFrame, keys: list[str]) -> tuple[pd.DataFrame, int]:
    """Uma linha por chave: maior prioridade de fonte e, depois, a versão mais recente da Bronze."""
    if df.empty:
        return df, 0
    ordenado = df.sort_values(
        ["_prioridade", "_carregado_em"], ascending=[False, False], kind="stable"
    )
    unico = ordenado.drop_duplicates(subset=keys, keep="first")
    return unico, len(df) - len(unico)


def _json(v: object) -> object:
    """Valor serializável em JSON válido (NaN/NaT/NA viram null)."""
    if isinstance(v, list):
        return v
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool | int | float | str):
        return v
    if hasattr(v, "item"):
        return v.item()
    return str(v)


def quarantine(
    engine: Engine, result: ValidationResult, entidade: str, pk: list[str], run_id: int | None
) -> int:
    """CSV em data/rejected/ + uma linha por (registro, regra) em ops.qualidade_rejeicoes."""
    rej = result.rejeitados
    if rej.empty:
        return 0
    pasta = get_settings().rejected_dir
    pasta.mkdir(parents=True, exist_ok=True)
    rej.drop(columns=[c for c in rej.columns if c.startswith("_") and c != "_regra"]).to_csv(
        pasta / f"{entidade}_{date.today().isoformat()}.csv", index=False
    )
    linhas = [
        {
            "id": run_id,
            "entidade": entidade,
            "chave": "|".join("" if _json(r.get(c)) is None else str(r.get(c)) for c in pk),
            "regra": r["_regra"],
            "registro": json.dumps(
                {k: _json(r[k]) for k in r.index if not k.startswith("_")}, ensure_ascii=False
            ),
        }
        for _, r in rej.iterrows()
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ops.qualidade_rejeicoes (id_execucao, entidade, chave, regra, registro) "
                "VALUES (:id, :entidade, :chave, :regra, CAST(:registro AS jsonb))"
            ),
            linhas,
        )
    return len(linhas)
