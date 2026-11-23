"""Utilitários da Silver: leitura da Bronze, mapeamento, tipagem, DDL e UPSERT (SPEC V3 8.1)."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from radar.silver.spec import TIPOS_SQL, Entidade, Fonte

log = logging.getLogger("radar.silver")

_RE_ID_URI = re.compile(r"/(\d+)/?$")
_RE_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")


# ------------------------------------------------------------------ leitura
def read_bronze(engine: Engine, nome: str, desde: datetime | None = None) -> pd.DataFrame:
    """Versão atual de cada registro (`bronze.vw_<nome>_atual`), com payload achatado."""
    sql = f"SELECT chave_registro, id_pai, payload, carregado_em FROM bronze.vw_{nome}_atual"
    params: dict = {}
    if desde is not None:
        sql += " WHERE carregado_em > :desde"
        params["desde"] = desde
    with engine.connect() as conn:
        linhas = conn.execute(text(sql), params).all()
    if not linhas:
        return pd.DataFrame()
    payloads = [r.payload for r in linhas]
    df = pd.json_normalize(payloads, sep=".", max_level=3)
    df["_chave"] = [r.chave_registro for r in linhas]
    df["_id_pai"] = [r.id_pai for r in linhas]
    df["_carregado_em"] = pd.to_datetime([r.carregado_em for r in linhas], utc=True)
    df["_origem"] = nome
    # payload bruto preservado para fontes que precisam explodir listas
    df["_payload"] = payloads
    return df


# ------------------------------------------------------------------ transformações
def to_snake(nome: str) -> str:
    return _RE_SNAKE.sub("_", nome).lower()


def id_from_uri(serie: pd.Series) -> pd.Series:
    """Último segmento numérico da URI → Int64 (`.../deputados/204528` → 204528)."""
    return serie.astype("string").str.extract(_RE_ID_URI, expand=False).astype("Int64")


def _nulo(v: object) -> bool:
    if v is None or v is pd.NA or v is pd.NaT:
        return True
    return isinstance(v, float) and np.isnan(v)


def _texto(v: object) -> object:
    """Valor → texto: nulos continuam nulos; 1.0 (inteiro que o Pandas virou float) → "1"."""
    if _nulo(v):
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def clean_text(serie: pd.Series) -> pd.Series:
    """strip + normalização Unicode NFC; vazios e nulos viram None (nunca o texto 'nan')."""

    def _limpar(v: object) -> object:
        v = _texto(v)
        if v is None:
            return None
        v = unicodedata.normalize("NFC", v).strip()
        return v or None

    return pd.Series([_limpar(v) for v in serie], index=serie.index, dtype="object")


def _valor(df: pd.DataFrame, expressao: str) -> pd.Series:
    if expressao == "@id_pai":
        return df["_id_pai"]
    if expressao == "@endpoint":
        return df["_origem"]
    if expressao == "@endpoint.sublista":
        return df["_origem"] + "." + df["_sublista"]
    if expressao.startswith("@const:"):
        return pd.Series([expressao.split(":", 1)[1]] * len(df), index=df.index, dtype="object")
    if expressao.startswith("@id:"):
        coluna = expressao[4:]
        return id_from_uri(df[coluna]) if coluna in df else pd.Series(pd.NA, index=df.index)
    return df[expressao] if expressao in df else pd.Series(None, index=df.index, dtype="object")


def _explodir(df: pd.DataFrame, campo: str) -> pd.DataFrame:
    """Uma linha por item de `campo` (lista de objetos); campos do item com prefixo `campo[].`.

    `campo="*"` desmembra todas as listas do objeto (referências agregadas): os itens ficam
    com prefixo `*[].` e o nome da lista vai para `_sublista`.
    """
    linhas = []
    for _, r in df.iterrows():
        payload = r["_payload"] or {}
        listas = (
            [(k, v) for k, v in payload.items() if isinstance(v, list)]
            if campo == "*"
            else [(campo, payload.get(campo) or [])]
        )
        for nome_lista, itens in listas:
            for item in itens:
                if not isinstance(item, dict):
                    continue
                base = {k: r[k] for k in ("_chave", "_id_pai", "_carregado_em", "_origem")}
                base["_sublista"] = nome_lista
                base.update(
                    {
                        f"{campo}[].{k}": v
                        for k, v in pd.json_normalize(item, sep=".").iloc[0].items()
                    }
                )
                base.update({k: r[k] for k in df.columns if not k.startswith("_") and "." not in k})
                linhas.append(base)
    return pd.DataFrame(linhas)


def mapear(df: pd.DataFrame, fonte: Fonte, entidade: Entidade) -> pd.DataFrame:
    """Bronze achatada → colunas da entidade (as não mapeadas ficam nulas)."""
    if df.empty:
        return pd.DataFrame(columns=[*entidade.colunas, "_carregado_em", "_origem", "_prioridade"])
    if fonte.explodir:
        df = _explodir(df, fonte.explodir)
        if df.empty:
            return pd.DataFrame(
                columns=[*entidade.colunas, "_carregado_em", "_origem", "_prioridade"]
            )
    if fonte.filtro is not None:
        df = df[fonte.filtro(df)]
    saida = pd.DataFrame(index=df.index)
    for coluna in entidade.colunas:
        saida[coluna] = _valor(df, fonte.colunas[coluna]) if coluna in fonte.colunas else None
    saida["_carregado_em"] = df["_carregado_em"]
    saida["_origem"] = df["_origem"]
    saida["_prioridade"] = fonte.prioridade
    return saida.reset_index(drop=True)


def tipar(df: pd.DataFrame, tipos: dict[str, str]) -> pd.DataFrame:
    """Converte cada coluna para o tipo declarado (valores inválidos viram nulos)."""
    df = df.copy()
    for coluna, tipo in tipos.items():
        s = df[coluna]
        if tipo in ("int", "bigint"):
            df[coluna] = pd.to_numeric(s, errors="coerce").astype("Int64")
        elif tipo == "num":
            df[coluna] = pd.to_numeric(s, errors="coerce")
        elif tipo == "date":
            # ISO8601: a API mistura "2024-02-04" e "2023-02-01T00:00"; sem isso o Pandas fixa
            # o formato pelo primeiro valor e anula os demais.
            df[coluna] = pd.to_datetime(s, errors="coerce", utc=True, format="ISO8601").dt.date
        elif tipo == "ts":
            datas = pd.to_datetime(s, errors="coerce", utc=False, format="mixed")
            if getattr(datas.dt, "tz", None) is None:
                datas = datas.dt.tz_localize(
                    "America/Sao_Paulo", ambiguous="NaT", nonexistent="NaT"
                )
            df[coluna] = datas
        elif tipo == "bool":
            df[coluna] = s.map(
                lambda v: (
                    None if v is None or v is pd.NA else str(v).lower() in ("true", "1", "sim", "s")
                )
            )
        elif tipo == "text[]":
            df[coluna] = s.map(_para_lista)
        else:
            df[coluna] = clean_text(s)
    return df


def _para_lista(v: object) -> list[str] | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, list):
        return [str(x) for x in v if x not in (None, "")] or None
    partes = [p.strip() for p in str(v).replace(";", ",").split(",")]
    return [p for p in partes if p] or None


# ------------------------------------------------------------------ DDL e gravação
def gerar_ddl(entidade: Entidade) -> str:
    colunas = ",\n    ".join(f"{c} {TIPOS_SQL[t]}" for c, t in entidade.tipos.items())
    return (
        f"CREATE TABLE IF NOT EXISTS silver.{entidade.nome} (\n    {colunas},\n"
        f"    _origem TEXT,\n    _carregado_em TIMESTAMPTZ,\n"
        f"    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),\n"
        f"    PRIMARY KEY ({', '.join(entidade.pk)})\n);\n"
    )


def _para_banco(v: object) -> object:
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def upsert(engine: Engine, entidade: Entidade, df: pd.DataFrame) -> int:
    """INSERT … ON CONFLICT (pk) DO UPDATE; colunas nulas na carga não apagam valores existentes."""
    if df.empty:
        return 0
    colunas = [*entidade.colunas, "_origem", "_carregado_em"]
    nao_pk = [c for c in colunas if c not in entidade.pk]
    sets = ", ".join(f"{c} = COALESCE(EXCLUDED.{c}, silver.{entidade.nome}.{c})" for c in nao_pk)
    sql = (
        f"INSERT INTO silver.{entidade.nome} ({', '.join(colunas)}) VALUES "
        f"({', '.join('%s' for _ in colunas)}) ON CONFLICT ({', '.join(entidade.pk)}) "
        f"DO UPDATE SET {sets}, atualizado_em = now()"
    )
    registros = [
        tuple(_para_banco(v) for v in linha) for linha in df[colunas].itertuples(index=False)
    ]
    with engine.begin() as conn:
        driver = conn.connection.driver_connection
        with driver.cursor() as cur:
            cur.executemany(sql, registros)
    return len(registros)
