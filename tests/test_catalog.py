"""Catálogo dos endpoints: cobertura 78/78, regras de nome, dependências e esquema."""

from datetime import date

import pytest
import yaml

from radar.catalog import sync
from radar.catalog.loader import (
    CATALOGO_PADRAO,
    CicloDeDependencia,
    due,
    load_catalog,
    topological_levels,
    topological_order,
)
from radar.catalog.models import EndpointSpec


@pytest.fixture(scope="module")
def openapi():
    return sync.ler_openapi()


@pytest.fixture(scope="module")
def specs():
    return load_catalog()


def test_catalogo_cobre_openapi(openapi, specs):
    """78/78: nenhum path GET do OpenAPI fora do catálogo e nenhum extra sem `obsoleto`."""
    cob = sync.cobertura(openapi, specs)
    assert not cob.faltando, f"faltando no catálogo: {sorted(cob.faltando)}"
    assert not cob.sobrando, f"no catálogo mas não no OpenAPI: {sorted(cob.sobrando)}"
    assert len(cob.api) == 78


def test_nenhuma_entrada_pendente_de_revisao(specs):
    assert [s.nome for s in specs if s.revisar] == []


@pytest.mark.parametrize(
    ("path", "nome"),
    [
        ("/deputados", "deputados"),
        ("/deputados/{id}", "deputados_detalhe"),
        ("/deputados/{id}/mandatosExternos", "deputados_mandatos_externos"),
        ("/referencias/deputados/siglaUF", "referencias_deputados_sigla_uf"),
        (
            "/referencias/proposicoes/codTipoTramitacao",
            "referencias_proposicoes_cod_tipo_tramitacao",
        ),
        ("/votacoes/{id}/orientacoes", "votacoes_orientacoes"),
    ],
)
def test_regra_de_nomes(path, nome):
    assert sync.nome_do_path(path) == nome


def test_nomes_do_catalogo_seguem_a_regra(specs):
    for s in specs:
        assert s.nome == sync.nome_do_path(s.path), s.path


def test_tipos_coerentes_com_o_path(specs):
    for s in specs:
        assert s.tipo == sync.tipo_do_path(s.path), s.nome


def test_contagem_por_grupo(specs):
    por_grupo: dict[str, int] = {}
    for s in specs:
        por_grupo[s.grupo] = por_grupo.get(s.grupo, 0) + 1
    assert por_grupo == {
        "referencias": 27, "legislaturas": 4, "partidos": 4, "blocos": 3, "deputados": 11,
        "orgaos": 5, "eventos": 6, "frentes": 3, "grupos": 4, "proposicoes": 7, "votacoes": 4,
    }  # fmt: skip


def test_ordem_topologica_sem_ciclos(specs):
    niveis = topological_levels(specs)
    vistos: set[str] = set()
    for nivel in niveis:
        for s in nivel:
            assert set(s.ids.de if s.ids else []) <= vistos, s.nome
        vistos |= {s.nome for s in nivel}
    assert len(topological_order(specs)) == 78


def test_ciclo_e_detectado():
    a = EndpointSpec(
        nome="a_detalhe", path="/a/{id}", grupo="a", tipo="detalhe", ids={"de": "b_detalhe"}
    )
    b = EndpointSpec(
        nome="b_detalhe", path="/b/{id}", grupo="b", tipo="detalhe", ids={"de": "a_detalhe"}
    )
    with pytest.raises(CicloDeDependencia):
        topological_levels([a, b])


def test_votacoes_nunca_cruzam_o_ano(specs):
    por_nome = {s.nome: s for s in specs}
    for nome in ("votacoes", "orgaos_votacoes"):
        assert por_nome[nome].janela.particao == "ano"


def test_proposicoes_tem_dois_passes(specs):
    janela = {s.nome: s for s in specs}["proposicoes"].janela
    assert len(janela.passes) == 2
    assert "dataApresentacaoInicio" in janela.passes[0] and "dataInicio" in janela.passes[1]


def test_detalhes_de_votacao_unem_quatro_origens(specs):
    origem = {s.nome: s for s in specs}["votacoes_detalhe"].ids.de
    assert set(origem) == {
        "votacoes",
        "eventos_votacoes",
        "orgaos_votacoes",
        "proposicoes_votacoes",
    }


@pytest.mark.parametrize(
    ("entrada", "erro"),
    [
        ({"nome": "X", "path": "/x", "grupo": "x", "tipo": "lista"}, "snake_case"),
        ({"nome": "x_detalhe", "path": "/x/{id}", "grupo": "x", "tipo": "detalhe"}, "exige `ids`"),
        (
            {"nome": "x", "path": "/x", "grupo": "x", "tipo": "lista", "params": {"a": "{amanha}"}},
            "placeholders",
        ),
        ({"nome": "x", "path": "/x", "grupo": "x", "tipo": "lista", "campo_novo": 1}, "extra"),
    ],
)
def test_esquema_rejeita_entradas_invalidas(entrada, erro):
    with pytest.raises(ValueError, match=erro):
        EndpointSpec.model_validate(entrada)


def test_sync_preserva_ajustes_e_marca_mudancas(openapi):
    existente = yaml.safe_load(CATALOGO_PADRAO.read_text(encoding="utf-8"))
    existente["endpoints"][0]["observacao"] = "ajuste manual"
    existente["endpoints"].append(
        {"nome": "antigo", "path": "/antigo", "grupo": "antigo", "tipo": "lista"}
    )
    removido = existente["endpoints"].pop(1)

    catalogo, rel = sync.mesclar(openapi, existente)

    assert catalogo["endpoints"][0]["observacao"] == "ajuste manual"
    assert rel.obsoletos == ["antigo"]
    assert rel.novos == [removido["nome"]]
    nova = next(e for e in catalogo["endpoints"] if e["nome"] == removido["nome"])
    assert nova["revisar"] is True


@pytest.mark.parametrize(
    ("frequencia", "dia", "esperado"),
    [
        ("diaria", date(2026, 11, 18), True),
        ("semanal", date(2026, 11, 22), True),  # domingo
        ("semanal", date(2026, 11, 18), False),
        ("mensal", date(2026, 12, 1), True),
        ("mensal", date(2026, 11, 18), False),
    ],
)
def test_due(frequencia, dia, esperado):
    spec = EndpointSpec(nome="x", path="/x", grupo="x", tipo="lista", frequencia=frequencia)
    assert due(spec, dia) is esperado
    assert due(spec, dia, force=True) is True
