"""As fixtures reais (M1) cobrem o catálogo e confirmam chaves e formatos."""

import json

import pytest

from radar.catalog.amostras import FIXTURES, _extrai
from radar.catalog.loader import load_catalog

SPECS = load_catalog()


def _fixture(nome: str) -> dict:
    return json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


def test_uma_fixture_por_endpoint():
    arquivos = {p.stem for p in FIXTURES.glob("*.json")}
    assert arquivos == {s.nome for s in SPECS}


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.nome)
def test_fixture_tem_dados_e_metadados(spec):
    fx = _fixture(spec.nome)
    assert fx["dados"], "fixture vazia"
    assert fx["_meta"]["endpoint"] == spec.nome
    assert fx["_meta"]["path"] == spec.path


@pytest.mark.parametrize(
    "spec", [s for s in SPECS if isinstance(s.chave, list)], ids=lambda s: s.nome
)
def test_campos_da_chave_existem_no_payload(spec):
    """Cada campo da chave existe no payload real (pode ser nulo; nunca ausente)."""
    dados = _fixture(spec.nome)["dados"]
    registros = dados if isinstance(dados, list) else [dados]
    for campo in (c for c in spec.chave if not c.startswith("{")):
        raiz = campo.split(".")[0].split("[]")[0]
        assert all(raiz in r for r in registros), f"{campo} ausente em {spec.nome}"
        assert any(_extrai(r, campo) for r in registros), f"{campo} sempre nulo em {spec.nome}"


def test_agregadas_sao_objetos():
    for s in SPECS:
        dados = _fixture(s.nome)["dados"]
        if s.chave == "objeto_unico" or s.tipo == "detalhe":
            assert isinstance(dados, dict), s.nome
        else:
            assert isinstance(dados, list), s.nome


def test_paginados_trazem_links():
    for s in SPECS:
        if s.paginado:
            rels = {link.get("rel") for link in _fixture(s.nome).get("links", [])}
            assert "self" in rels, s.nome


def test_fixtures_sem_cpf():
    """CPFs (deputados e fornecedores pessoa física) não vão para o repositório."""
    import re

    for arquivo in FIXTURES.glob("*.json"):
        texto = arquivo.read_text(encoding="utf-8")
        for campo, valor in re.findall(r'"(cpf|cnpjCpfFornecedor)":\s*"(\d+)"', texto):
            assert len(valor) == 14 or set(valor) == {"0"}, f"{campo} exposto em {arquivo.name}"
