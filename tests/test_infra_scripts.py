"""Garantias sobre os scripts executados na VPS (infra/vps)."""

import re
import subprocess
from pathlib import Path

import pytest

from radar.config import RAIZ_PROJETO

INFRA = RAIZ_PROJETO / "infra" / "vps"
SCRIPTS = sorted(INFRA.glob("*.sh"))


def _sem_comentarios(caminho: Path) -> str:
    return "\n".join(
        linha
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if not linha.lstrip().startswith("#")
    )


def test_scripts_existem():
    nomes = {s.name for s in SCRIPTS}
    assert {
        "diagnostico.sh",
        "novo_projeto.sh",
        "backup_bancos.sh",
        "testar_restauracao.sh",
    } <= nomes


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_sintaxe_bash(script):
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_diagnostico_somente_leitura():
    codigo = _sem_comentarios(INFRA / "diagnostico.sh")
    proibidos = [
        r"\b(DROP|CREATE|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE)\s",
        r"\brm\s+-",
        r"docker\s+(stop|rm|kill|restart|compose\s+(up|down)|service\s+(update|rm)|stack\s+(deploy|rm))",
        r"ufw\s+(allow|deny|enable|disable|delete)",
        r"\b(chmod|chown|mkfs|systemctl\s+(start|stop|restart|enable|disable))\b",
        r">\s*/(etc|opt|var)/",
    ]
    for padrao in proibidos:
        assert not re.search(padrao, codigo, re.IGNORECASE), padrao


def test_diagnostico_nao_le_valores_de_env():
    codigo = _sem_comentarios(INFRA / "diagnostico.sh")
    assert 'cat "$envf"' not in codigo and "source" not in codigo
    # de arquivos .env só extrai nomes (grep -o até o '=')
    assert re.search(r"grep -oE '\^\[A-Za-z_\]\[A-Za-z0-9_\]\*='", codigo)
    assert "docker inspect" not in codigo or ".Config.Env" not in codigo


def test_diagnostico_nao_le_stdin_nos_comandos_internos():
    """O script chega por `bash -s`: docker exec -i consumiria o restante do script."""
    assert "docker exec -i" not in _sem_comentarios(INFRA / "diagnostico.sh")


def test_senhas_nao_vao_na_linha_de_comando():
    codigo = _sem_comentarios(INFRA / "novo_projeto.sh")
    assert not re.search(r"psql[^\n|]*-v\s+senha", codigo)
    assert "\\\\set senha_app" in codigo  # senhas enviadas pela entrada padrão do psql


def test_gateway_so_em_enderecos_internos():
    compose = (INFRA / "docker-compose.gateway.yml").read_text(encoding="utf-8")
    portas = re.findall(r'-\s*"([^"]+)"', compose)
    assert portas, "nenhuma porta encontrada"
    for porta in portas:
        assert porta.startswith(("127.0.0.1:", "172.18.0.1:")), porta
    assert "@sha256:" in compose  # imagem fixada por digest


def test_bancos_conf_sem_senhas():
    for linha in (INFRA / "bancos.conf").read_text(encoding="utf-8").splitlines():
        if linha.strip() and not linha.startswith("#"):
            assert len(linha.split()) == 3, linha
            assert "senha" not in linha.lower() and ":" not in linha
