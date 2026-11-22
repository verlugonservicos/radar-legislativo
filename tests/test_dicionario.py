"""O dicionário de dados versionado está em dia com o catálogo e as fixtures."""

import yaml

from radar.catalog.dicionario import DESTINO, SAIDA, gerar, perfil_campos
from radar.catalog.loader import load_catalog


def test_dicionario_versionado_esta_atualizado(tmp_path):
    novo = gerar(tmp_path / "dicionario.md")
    assert novo.read_text(encoding="utf-8") == SAIDA.read_text(encoding="utf-8"), (
        "docs/dicionario_de_dados.md desatualizado: rode `python -m radar catalog dicionario`"
    )


def test_todo_endpoint_nao_referencia_tem_destino_silver():
    destinos = yaml.safe_load(DESTINO.read_text(encoding="utf-8"))["destinos"]
    sem_destino = [
        s.nome for s in load_catalog() if s.grupo != "referencias" and s.nome not in destinos
    ]
    assert sem_destino == []


def test_perfil_achata_aninhados_e_listas():
    dados = [{"id": 1, "status": {"sigla": "PL"}, "orgaos": [{"id": 9}], "x": None}]
    campos = {c[0]: c for c in perfil_campos(dados)}
    assert {"id", "status.sigla", "orgaos", "orgaos[].id", "x"} <= set(campos)
    assert campos["x"][1] == "nulo" and campos["status.sigla"][4] == "PL"
