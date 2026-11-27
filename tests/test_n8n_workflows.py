"""Workflows do n8n (M6): JSON válido, ligações apontam para nós existentes e runner sem porta pública."""

import json
from pathlib import Path

import pytest

PASTA = Path(__file__).parents[1] / "n8n" / "workflows"
ARQUIVOS = sorted(PASTA.glob("*.json"))


def test_os_cinco_workflows_existem():
    assert [a.stem[:4] for a in ARQUIVOS] == ["WF01", "WF02", "WF03", "WF04", "WF99"]


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.stem)
def test_ligacoes_e_credenciais(arquivo):
    w = json.loads(arquivo.read_text(encoding="utf-8"))
    nomes = {n["name"] for n in w["nodes"]}
    assert len(nomes) == len(w["nodes"]), "nomes de nós repetidos"
    for origem, saidas in w["connections"].items():
        assert origem in nomes
        for ramo in saidas["main"]:
            assert all(d["node"] in nomes for d in ramo)
    assert w["settings"]["timezone"] == "America/Sao_Paulo"
    for n in w["nodes"]:
        url = n["parameters"].get("url", "")
        if url:
            assert "radar_runner:8000" in url  # rede interna do Swarm, nunca porta publicada
            assert n["credentials"]["httpHeaderAuth"]["name"] == "Radar Runner Token"
        for cred in (n.get("credentials") or {}).values():
            assert cred["id"] == ""  # nenhum segredo/ID de credencial no arquivo versionado
