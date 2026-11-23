"""Silver (M3): tipagem, mapeamento, validações e cobertura das entidades."""

import json
from datetime import date

import pandas as pd
import pytest

from radar.catalog.loader import load_catalog
from radar.silver import base
from radar.silver.entities import entidades
from radar.silver.spec import Entidade, Fonte
from radar.silver.validators import (
    _json,
    deduplicate,
    in_set,
    non_negative,
    not_null,
    validate,
)

ENTIDADES = {e.nome: e for e in entidades()}


def _bronze(payloads, origem="x", id_pai=None):
    df = pd.json_normalize(payloads, sep=".")
    df["_chave"] = [str(i) for i in range(len(df))]
    df["_id_pai"] = id_pai
    df["_carregado_em"] = pd.Timestamp("2026-11-22", tz="UTC")
    df["_origem"] = origem
    df["_payload"] = payloads
    return df


def test_toda_tabela_bronze_alimenta_a_silver():
    usadas = {f.bronze for e in ENTIDADES.values() for f in e.fontes}
    assert {s.nome for s in load_catalog()} - usadas == set()


def test_ddl_tem_pk_e_colunas_de_linhagem():
    ddl = base.gerar_ddl(ENTIDADES["despesas"])
    assert "PRIMARY KEY (chave_despesa)" in ddl and "_carregado_em TIMESTAMPTZ" in ddl
    assert "valor_documento NUMERIC(14,2)" in ddl


def test_datas_em_formatos_mistos_nao_viram_nulas():
    df = pd.DataFrame({"d": ["2023-02-01T00:00", "2024-02-04", None, "lixo"]})
    assert base.tipar(df, {"d": "date"})["d"].tolist()[:2] == [date(2023, 2, 1), date(2024, 2, 4)]
    assert base.tipar(df, {"d": "date"})["d"].isna().tolist()[2:] == [True, True]


def test_id_from_uri_e_texto_limpo():
    s = pd.Series(["https://x/api/v2/deputados/204528", "https://x/orgaos/180/", None])
    assert base.id_from_uri(s).tolist()[:2] == [204528, 180]
    assert base.clean_text(pd.Series(["  Saúdé ", ""])).tolist()[1] is None


def test_mapeamento_com_id_pai_uri_constante_e_explosao():
    ent = Entidade("t", ["a", "b"], {"a": "int", "b": "int", "c": "text", "p": "text"},
                   [Fonte("x", {"a": "@id_pai", "b": "membros[].id", "c": "@const:objeto",
                                "p": "@id:membros[].uri"}, explodir="membros")])  # fmt: skip
    df = _bronze(
        [{"id": 9, "membros": [{"id": 1, "uri": "u/deputados/77"}, {"id": 2, "uri": None}]}],
        id_pai="5",
    )
    m = base.mapear(df, ent.fontes[0], ent)
    assert m["a"].tolist() == ["5", "5"] and m["b"].tolist() == [1, 2]
    assert m["c"].tolist() == ["objeto", "objeto"] and m["p"].tolist()[0] == 77


def test_referencias_agregadas_desmembram_todas_as_listas():
    ent = ENTIDADES["referencias"]
    fonte = next(f for f in ent.fontes if f.explodir == "*" and f.bronze == "referencias_eventos")
    df = _bronze([{"codTipoEvento": [{"cod": "1", "sigla": None, "nome": "Sessão", "descricao": None}],
                   "codSituacao": [{"cod": None, "sigla": "A", "nome": "Aberta", "descricao": None}]}],
                 origem="referencias_eventos")  # fmt: skip
    m = ent.transformar(base.tipar(base.mapear(df, fonte, ent), ent.tipos))
    assert sorted(m["dominio"]) == [
        "referencias_eventos.codSituacao",
        "referencias_eventos.codTipoEvento",
    ]
    assert (
        m.set_index("dominio").loc["referencias_eventos.codSituacao", "cod"] == "A"
    )  # sigla vira código


def test_validacao_quarentena_e_regra_so_de_aviso():
    df = pd.DataFrame({"id": [1, 2, None], "valor": [10.0, -5.0, 3.0], "uf": ["SP", "XX", "RJ"]})
    r = validate(
        df, [not_null("id"), non_negative("valor"), in_set("uf", {"SP", "RJ"}, rejeita=False)], "t"
    )
    assert r.validos["id"].tolist() == [1]
    assert r.resumo == {"not_null(id)": 1, "non_negative(valor)": 1}
    assert r.avisos == {"in_set(uf)": 1}  # aviso não rejeita


def test_deduplicacao_por_prioridade_e_recencia():
    df = pd.DataFrame({"id": [1, 1, 1], "v": ["lista", "detalhe", "lista_nova"], "_prioridade": [0, 1, 0],
                       "_carregado_em": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-02-01"], utc=True)})  # fmt: skip
    unico, dup = deduplicate(df, ["id"])
    assert unico["v"].tolist() == ["detalhe"] and dup == 2


def test_json_da_quarentena_e_valido():
    registro = {
        k: _json(v) for k, v in {"a": float("nan"), "b": pd.NaT, "c": pd.NA, "d": 1}.items()
    }
    assert json.loads(json.dumps(registro)) == {"a": None, "b": None, "c": None, "d": 1}


def test_despesa_negativa_vai_para_quarentena():
    ent = ENTIDADES["despesas"]
    df = pd.DataFrame([{c: None for c in ent.colunas} | {"id_deputado": 1, "ano": 2026, "mes": 10, "valor_documento": v}
                       for v in (100.0, -35.9)])  # fmt: skip
    df = ent.transformar(base.tipar(df, ent.tipos))
    r = validate(df, [not_null(*ent.pk), *ent.regras], "despesas")
    assert len(r.validos) == 1 and r.resumo == {"non_negative(valor_documento)": 1}


@pytest.mark.parametrize("nome", ["deputados_orgaos", "deputados_frentes", "eventos_orgaos", "eventos_deputados",
                                  "votacoes_proposicoes"])  # fmt: skip
def test_relacoes_espelhadas_sao_conformadas(nome):
    assert ENTIDADES[nome].conformada and len({f.bronze for f in ENTIDADES[nome].fontes}) >= 2
