"""Coletor de amostras (M1), sem rede: a API é simulada com `responses`."""

import json
from datetime import date

import responses

from radar.catalog import amostras
from radar.catalog.models import EndpointSpec

BASE = "https://dadosabertos.camara.leg.br/api/v2"


def test_extrai_caminhos():
    r = {"id": 1, "parlamentar": {"id": 7}, "orgaos": [{"id": 3}, {"id": 4}], "x": None}
    assert amostras._extrai(r, "id") == [1]
    assert amostras._extrai(r, "parlamentar.id") == [7]
    assert amostras._extrai(r, "orgaos[].id") == [3, 4]
    assert amostras._extrai(r, "x") == []


def test_mascarar_pessoais():
    dados = [{"cpf": "12345678901", "fornecedor": {"cnpjCpfFornecedor": "123.456.789-01"}},
             {"cnpjCpfFornecedor": "07810282000212"}]  # fmt: skip
    saida = amostras.mascarar_pessoais(dados)
    assert saida[0]["cpf"] == amostras.CPF_MASCARA
    assert saida[0]["fornecedor"]["cnpjCpfFornecedor"] == amostras.CPF_MASCARA
    assert saida[1]["cnpjCpfFornecedor"] == "07810282000212"  # CNPJ fica


def test_janela_nao_cruza_o_ano():
    v = amostras._valores(date(2027, 1, 3), dias=7)
    assert v["inicio"] == "2027-01-01" and v["fim"] == "2027-01-02"
    assert (v["ano"], v["mes"]) == ("2026", "12")


def test_ids_priorizam_plenario_e_legislaturas_recentes():
    spec = EndpointSpec(nome="votacoes_votos", path="/votacoes/{id}/votos", grupo="votacoes",
                        tipo="subrecurso", ids={"de": "votacoes"})  # fmt: skip
    respostas = {
        "votacoes": {"dados": [{"id": "a", "siglaOrgao": "CCJ"}, {"id": "b", "siglaOrgao": "PLEN"}]}
    }
    assert amostras._ids_candidatos(spec, respostas)[0] == "b"

    origem = {"de": "legislaturas", "filtro": "legislaturas_recentes"}
    leg = EndpointSpec(nome="legislaturas_detalhe", path="/legislaturas/{id}",
                       grupo="legislaturas", tipo="detalhe", ids=origem)  # fmt: skip
    respostas = {"legislaturas": {"dados": [{"id": 50}, {"id": 56}, {"id": 57}]}}
    assert amostras._ids_candidatos(leg, respostas) == [56, 57]


@responses.activate
def test_coletor_repete_em_erro_temporario(monkeypatch):
    monkeypatch.setattr(amostras.time, "sleep", lambda _: None)
    responses.get(f"{BASE}/partidos", status=503)
    responses.get(f"{BASE}/partidos", json={"dados": [{"id": 1}], "links": []})
    status, corpo, _ = amostras.Coletor().get("/partidos", {})
    assert status == 200 and corpo["dados"] == [{"id": 1}]


@responses.activate
def test_coletar_grava_fixture_cortada_e_mascarada(tmp_path, monkeypatch):
    monkeypatch.setattr(amostras.time, "sleep", lambda _: None)
    specs = [
        EndpointSpec(nome="deputados", path="/deputados", grupo="deputados", tipo="lista",
                     paginado=True),
        EndpointSpec(nome="deputados_detalhe", path="/deputados/{id}", grupo="deputados",
                     tipo="detalhe", ids={"de": "deputados"}),
    ]  # fmt: skip
    monkeypatch.setattr(amostras, "load_catalog", lambda: specs)
    lista = [{"id": i} for i in range(1, 9)]
    responses.get(f"{BASE}/deputados", json={"dados": lista, "links": [{"rel": "self"}]})
    responses.get(f"{BASE}/deputados/1", json={"dados": {}, "links": []})  # vazio: tenta o próximo
    responses.get(
        f"{BASE}/deputados/2", json={"dados": {"id": 2, "cpf": "12345678901"}, "links": []}
    )

    resultado = amostras.coletar(destino=tmp_path, hoje=date(2026, 11, 22))

    assert resultado == {"deputados": "ok (8)", "deputados_detalhe": "ok (1)"}
    lista_fx = json.loads((tmp_path / "deputados.json").read_text())
    assert (
        len(lista_fx["dados"]) == amostras.MAX_ITENS
        and lista_fx["_meta"]["registros_originais"] == 8
    )
    det = json.loads((tmp_path / "deputados_detalhe.json").read_text())
    assert det["_meta"]["id_pai"] == 2 and det["dados"]["cpf"] == amostras.CPF_MASCARA
