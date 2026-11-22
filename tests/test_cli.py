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
