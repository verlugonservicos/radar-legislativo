import pytest

from radar.__main__ import build_parser, main


def test_parser_db_init():
    args = build_parser().parse_args(["db", "init"])
    assert args.comando == "db" and args.acao == "init"


def test_parser_exige_comando():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


@pytest.mark.parametrize("acao", ["init", "check"])
def test_sem_database_url_sai_com_codigo_2(sem_env, tmp_path, acao, capsys):
    sem_env.setenv("LOG_DIR", str(tmp_path))
    assert main(["db", acao]) == 2
    assert "DATABASE_URL não está configurada" in capsys.readouterr().err


def test_sem_tunel_sugere_make_tunnel(sem_env, tmp_path, capsys):
    """Porta local do túnel fechada: código 3 e dica de abrir o túnel."""
    import socket

    with socket.socket() as s:  # porta livre e fechada
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    sem_env.setenv("LOG_DIR", str(tmp_path))
    sem_env.setenv("TUNNEL_PORTA_LOCAL", str(porta))
    sem_env.setenv(
        "DATABASE_URL", f"postgresql+psycopg://radar_app:x@127.0.0.1:{porta}/radar_legislativo"
    )
    assert main(["db", "check"]) == 3
    assert "make tunnel" in capsys.readouterr().err
