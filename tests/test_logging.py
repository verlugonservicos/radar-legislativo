import logging

import pytest

from radar.logging_setup import log_contexto, mascarar, setup_logging


@pytest.mark.parametrize(
    ("entrada", "proibido"),
    [
        ("postgresql+psycopg://postgres.abc:MinhaSenha123@host:6543/postgres", "MinhaSenha123"),
        ("chave sk-proj-AbCdEf1234567890xyz usada", "AbCdEf1234567890xyz"),
        (
            "bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw0",
            "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw0",
        ),
    ],
)
def test_mascarar_remove_segredos(entrada, proibido):
    saida = mascarar(entrada)
    assert proibido not in saida
    assert "***" in saida


def test_mascarar_preserva_texto_comum():
    assert mascarar("baixando /proposicoes página 3") == "baixando /proposicoes página 3"


def test_log_com_contexto_e_sem_segredo(tmp_path, capsys):
    setup_logging(tmp_path, "INFO")
    log = logging.getLogger("radar.teste")
    with log_contexto(run=42, camada="bronze", endpoint="proposicoes"):
        log.info("conectando em %s", "postgresql://u:SENHA_SECRETA@h/db")
    log.info("fora do contexto")
    for handler in logging.getLogger("radar").handlers:
        handler.flush()

    arquivo = (tmp_path / "radar.log").read_text(encoding="utf-8")
    console = capsys.readouterr().err
    for saida in (arquivo, console):
        assert "SENHA_SECRETA" not in saida
        assert "run=42 | camada=bronze | endpoint=proposicoes" in saida
        assert "run=- | camada=- | endpoint=- | fora do contexto" in saida


def test_traceback_tambem_e_mascarado(tmp_path, capsys):
    setup_logging(tmp_path, "INFO")
    log = logging.getLogger("radar.teste")
    try:
        raise RuntimeError("falha ao conectar postgresql://u:SENHA_NO_ERRO@h/db")
    except RuntimeError:
        log.exception("erro")
    assert "SENHA_NO_ERRO" not in capsys.readouterr().err
