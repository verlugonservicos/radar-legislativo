"""As entidades da Silver (SPEC V3 seção 8.2), mapeadas campo a campo a partir das fixtures reais.

Desvios conscientes em relação à SPEC (registrados no ADR-023):
- `votacoes` não tem votos_sim/nao/outros: a API não traz essas contagens; a Gold calcula a
  partir de `silver.votos`.
- Entidades sem chave natural confiável (ocupações, mandatos externos, histórico e membros de
  grupos) usam `chave` = md5 dos campos que identificam o registro.
- Itens de pauta sem proposição (comunicações, expedientes) recebem `id_proposicao = 0`.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import pandas as pd

from radar.catalog.loader import load_catalog
from radar.silver.spec import Entidade, Fonte
from radar.silver.validators import (
    UFS,
    Rule,
    between,
    date_between,
    in_set,
    non_negative,
    not_null,
)

HOJE = date.today()


# ------------------------------------------------------------------ auxiliares de transformação
def _md5(*valores: object) -> str:
    texto = "|".join(
        "" if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)) else str(v)
        for v in valores
    )
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def com_chave(alvo: str, campos: list[str], funcao=_md5):
    """Transformação que preenche `alvo` com o hash dos `campos` (chave sintética estável)."""

    def transformar(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df[alvo] = (
            [funcao(*linha) for linha in df[campos].itertuples(index=False)] if len(df) else []
        )
        return df

    return transformar


def _sha256(*valores: object) -> str:
    texto = "|".join("" if v is None or v is pd.NA else str(v) for v in valores)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


REGIOES = {
    "Norte": {"AC", "AP", "AM", "PA", "RO", "RR", "TO"},
    "Nordeste": {"AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"},
    "Centro-Oeste": {"DF", "GO", "MT", "MS"},
    "Sudeste": {"ES", "MG", "RJ", "SP"},
    "Sul": {"PR", "RS", "SC"},
}
_REGIAO_DA_UF = {uf: regiao for regiao, ufs in REGIOES.items() for uf in ufs}


def _regiao(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["regiao"] = df["sigla"].map(_REGIAO_DA_UF)
    return df


def _cod_ou_sigla(df: pd.DataFrame) -> pd.DataFrame:
    """Algumas referências (situação do deputado, por exemplo) não têm `cod`, só `sigla`."""
    df = df.copy()
    df["cod"] = df["cod"].fillna(df["sigla"])
    return df


def _so_deputados(df: pd.DataFrame) -> pd.DataFrame:
    """Autor com URI de deputado → id_deputado; demais autores (órgãos, Senado) ficam nulos."""
    df = df.copy()
    df.loc[~df["uri_autor"].fillna("").str.contains("/deputados/"), "id_deputado"] = pd.NA
    return df


def _pauta_sem_proposicao(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["id_proposicao"] = df["id_proposicao"].fillna(0)
    return df


def _despesas(df: pd.DataFrame) -> pd.DataFrame:
    """Chave da despesa + correção do sinal do valor líquido (ADR-024).

    A API devolve `valorLiquido` com sinal trocado em ~89% dos lançamentos: o módulo bate com
    `valorDocumento - valorGlosa`. Quando o documento é positivo e o módulo bate, o sinal é
    corrigido e a linha fica marcada (`_liquido_corrigido`) para a regra de aviso.
    """
    df = com_chave("chave_despesa", [
        "id_deputado", "ano", "mes", "cod_documento", "num_documento", "data_documento",
        "valor_documento", "cnpj_cpf_fornecedor", "parcela"], funcao=_sha256)(df)  # fmt: skip
    doc = pd.to_numeric(df["valor_documento"], errors="coerce")
    liq = pd.to_numeric(df["valor_liquido"], errors="coerce")
    glosa = pd.to_numeric(df["valor_glosa"], errors="coerce").fillna(0)
    trocado = ((doc >= 0) & (liq < 0) & ((liq.abs() - (doc - glosa)).abs() < 0.01)).fillna(False)
    df["valor_liquido"] = liq.where(~trocado, liq.abs())
    df["_liquido_corrigido"] = trocado
    return df


def _sinal_corrigido() -> Rule:
    return Rule(
        "sinal_valor_liquido_corrigido",
        "valor líquido negativo com módulo = documento - glosa (sinal corrigido; ADR-024)",
        lambda df: (
            df["_liquido_corrigido"]
            if "_liquido_corrigido" in df
            else pd.Series(False, index=df.index)
        ),
        rejeita=False,
    )


def _registro_vazio(*cols: str) -> Rule:
    return Rule(
        "registro_vazio",
        f"todos nulos: {', '.join(cols)}",
        lambda df: df[list(cols)].isna().all(axis=1),
    )


def _tem(campo: str):
    return lambda df: df[campo].notna() if campo in df else pd.Series(False, index=df.index)


# ------------------------------------------------------------------ referências
def _fontes_referencias() -> list[Fonte]:
    """23 listas + as 4 agregadas desmembradas por lista (dominio = endpoint[.lista])."""
    colunas = {"cod": "cod", "sigla": "sigla", "nome": "nome", "descricao": "descricao"}
    fontes = []
    for spec in load_catalog():
        if spec.grupo != "referencias":
            continue
        if spec.chave == "objeto_unico":
            fontes.append(
                Fonte(
                    spec.nome,
                    {
                        "dominio": "@endpoint.sublista",
                        **{k: f"*[].{v}" for k, v in colunas.items()},
                    },
                    explodir="*",
                )
            )
        else:
            fontes.append(Fonte(spec.nome, {"dominio": "@endpoint", **colunas}))
    return fontes


# ------------------------------------------------------------------ campos repetidos
_DEP_RESUMO = {"nome": "nome", "sigla_partido": "siglaPartido", "sigla_uf": "siglaUf"}
_EVENTO = {
    "id_evento": "id",
    "data_hora_inicio": "dataHoraInicio",
    "data_hora_fim": "dataHoraFim",
    "situacao": "situacao",
    "descricao_tipo": "descricaoTipo",
    "descricao": "descricao",
    "local_camara_nome": "localCamara.nome",
    "local_camara_predio": "localCamara.predio",
    "local_camara_sala": "localCamara.sala",
    "local_externo": "localExterno",
    "url_registro": "urlRegistro",
}
_VOTACAO = {
    "id_votacao": "id",
    "data": "data",
    "data_hora_registro": "dataHoraRegistro",
    "id_orgao": "@id:uriOrgao",
    "sigla_orgao": "siglaOrgao",
    "id_evento": "@id:uriEvento",
    "aprovacao": "aprovacao",
    "descricao": "descricao",
    "uri": "uri",
}
_OBJETO = {"id_votacao": "id", "id_proposicao": "@id:uriProposicaoObjeto", "papel": "@const:objeto"}


def entidades() -> list[Entidade]:
    """Todas as entidades na ordem de processamento."""
    return [
        # ---------------------------------------------------------- referências
        Entidade(
            "referencias", ["dominio", "cod"],
            {"dominio": "text", "cod": "text", "sigla": "text", "nome": "text", "descricao": "text"},
            _fontes_referencias(), completa=True, transformar=_cod_ou_sigla,
        ),
        Entidade(
            "ufs", ["sigla"], {"sigla": "text", "nome": "text", "regiao": "text"},
            [Fonte("referencias_uf", {"sigla": "sigla", "nome": "nome"})],
            regras=[in_set("sigla", UFS, rejeita=False)], transformar=_regiao, completa=True,
        ),
        # ---------------------------------------------------------- legislaturas
        Entidade(
            "legislaturas", ["id_legislatura"],
            {"id_legislatura": "int", "data_inicio": "date", "data_fim": "date", "uri": "text"},
            [
                Fonte("legislaturas", {"id_legislatura": "id", "data_inicio": "dataInicio", "data_fim": "dataFim", "uri": "uri"}),
                Fonte("legislaturas_detalhe", {"id_legislatura": "id", "data_inicio": "dataInicio", "data_fim": "dataFim", "uri": "uri"}, prioridade=1),
            ],
        ),
        Entidade(
            "legislaturas_lideres", ["id_legislatura", "id_deputado", "titulo", "data_inicio"],
            {"id_legislatura": "int", "id_deputado": "int", "titulo": "text", "data_inicio": "date",
             "nome": "text", "sigla_partido": "text", "sigla_uf": "text", "bancada_tipo": "text",
             "bancada_nome": "text", "data_fim": "date"},
            [Fonte("legislaturas_lideres", {
                "id_legislatura": "@id_pai", "id_deputado": "parlamentar.id", "titulo": "titulo",
                "data_inicio": "dataInicio", "nome": "parlamentar.nome",
                "sigla_partido": "parlamentar.siglaPartido", "sigla_uf": "parlamentar.siglaUf",
                "bancada_tipo": "bancada.tipo", "bancada_nome": "bancada.nome", "data_fim": "dataFim"})],
        ),
        Entidade(
            "legislaturas_mesa", ["id_legislatura", "id_deputado", "cod_titulo", "data_inicio"],
            {"id_legislatura": "int", "id_deputado": "int", "cod_titulo": "int", "data_inicio": "date",
             **dict.fromkeys(["nome", "sigla_partido", "sigla_uf", "titulo"], "text"), "data_fim": "date"},
            [Fonte("legislaturas_mesa", {
                "id_legislatura": "@id_pai", "id_deputado": "id", "cod_titulo": "codTitulo",
                "data_inicio": "dataInicio", **_DEP_RESUMO, "titulo": "titulo", "data_fim": "dataFim"})],
        ),
        # ---------------------------------------------------------- partidos e blocos
        Entidade(
            "partidos", ["id_partido"],
            {"id_partido": "int", "sigla": "text", "nome": "text", "situacao": "text",
             "total_membros": "int", "total_posse": "int", "id_legislatura": "int",
             "numero_eleitoral": "int", "url_logo": "text", "url_website": "text",
             "lider_id": "int", "lider_nome": "text", "uri": "text"},
            [
                Fonte("partidos", {"id_partido": "id", "sigla": "sigla", "nome": "nome", "uri": "uri"}),
                Fonte("partidos_detalhe", {
                    "id_partido": "id", "sigla": "sigla", "nome": "nome", "uri": "uri",
                    "situacao": "status.situacao", "total_membros": "status.totalMembros",
                    "total_posse": "status.totalPosse", "id_legislatura": "status.idLegislatura",
                    "numero_eleitoral": "numeroEleitoral", "url_logo": "urlLogo",
                    "url_website": "urlWebSite", "lider_id": "@id:status.lider.uri",
                    "lider_nome": "status.lider.nome"}, prioridade=1),
            ],
            regras=[not_null("sigla")],
        ),
        Entidade(
            "partidos_lideres", ["id_partido", "id_deputado", "cod_titulo", "data_inicio"],
            {"id_partido": "int", "id_deputado": "int", "cod_titulo": "int", "data_inicio": "date",
             "nome": "text", "sigla_uf": "text", "titulo": "text", "data_fim": "date"},
            [Fonte("partidos_lideres", {
                "id_partido": "@id_pai", "id_deputado": "id", "cod_titulo": "codTitulo",
                "data_inicio": "dataInicio", "nome": "nome", "sigla_uf": "siglaUf",
                "titulo": "titulo", "data_fim": "dataFim"})],
        ),
        Entidade(
            "partidos_membros", ["id_partido", "id_deputado"],
            {"id_partido": "int", "id_deputado": "int", "nome": "text", "sigla_uf": "text", "id_legislatura": "int"},
            [Fonte("partidos_membros", {"id_partido": "@id_pai", "id_deputado": "id", "nome": "nome",
                                        "sigla_uf": "siglaUf", "id_legislatura": "idLegislatura"})],
        ),
        Entidade(
            "blocos", ["id_bloco"],
            {"id_bloco": "int", "nome": "text", "id_legislatura": "int", "federacao": "bool", "uri": "text"},
            [
                Fonte("blocos", {"id_bloco": "id", "nome": "nome", "id_legislatura": "idLegislatura", "federacao": "federacao", "uri": "uri"}),
                Fonte("blocos_detalhe", {"id_bloco": "id", "nome": "nome", "id_legislatura": "idLegislatura", "federacao": "federacao", "uri": "uri"}, prioridade=1),
            ],
        ),
        Entidade(
            # a API repete o id do bloco no `id` de cada partido (ADR-028): chave = bloco + sigla;
            # o id_partido verdadeiro é resolvido pela sigla na Gold (dim_partido)
            "blocos_partidos", ["id_bloco", "sigla_partido"],
            {"id_bloco": "int", "id_partido": "int", "sigla_partido": "text", "nome_partido": "text"},
            [Fonte("blocos_partidos", {"id_bloco": "@id_pai", "sigla_partido": "sigla", "nome_partido": "nome"})],
        ),
        # ---------------------------------------------------------- deputados
        Entidade(
            "deputados", ["id_deputado"],
            {"id_deputado": "int", "nome": "text", "nome_civil": "text", "nome_eleitoral": "text",
             "sigla_partido": "text", "id_partido": "int", "sigla_uf": "text", "id_legislatura": "int",
             "sexo": "text", "data_nascimento": "date", "data_falecimento": "date", "uf_nascimento": "text",
             "municipio_nascimento": "text", "escolaridade": "text", "situacao": "text",
             "condicao_eleitoral": "text", "descricao_status": "text", "email": "text", "url_foto": "text",
             "url_website": "text", "gabinete_nome": "text", "gabinete_predio": "text",
             "gabinete_sala": "text", "gabinete_andar": "text", "gabinete_telefone": "text"},
            [
                Fonte("deputados", {
                    "id_deputado": "id", "nome": "nome", "sigla_partido": "siglaPartido",
                    "id_partido": "@id:uriPartido", "sigla_uf": "siglaUf",
                    "id_legislatura": "idLegislatura", "url_foto": "urlFoto", "email": "email"}),
                Fonte("deputados_detalhe", {  # `cpf` fica só na Bronze
                    "id_deputado": "id", "nome": "ultimoStatus.nome", "nome_civil": "nomeCivil",
                    "nome_eleitoral": "ultimoStatus.nomeEleitoral",
                    "sigla_partido": "ultimoStatus.siglaPartido", "id_partido": "@id:ultimoStatus.uriPartido",
                    "sigla_uf": "ultimoStatus.siglaUf", "id_legislatura": "ultimoStatus.idLegislatura",
                    "sexo": "sexo", "data_nascimento": "dataNascimento", "data_falecimento": "dataFalecimento",
                    "uf_nascimento": "ufNascimento", "municipio_nascimento": "municipioNascimento",
                    "escolaridade": "escolaridade", "situacao": "ultimoStatus.situacao",
                    "condicao_eleitoral": "ultimoStatus.condicaoEleitoral",
                    "descricao_status": "ultimoStatus.descricaoStatus", "email": "ultimoStatus.email",
                    "url_foto": "ultimoStatus.urlFoto", "url_website": "urlWebsite",
                    "gabinete_nome": "ultimoStatus.gabinete.nome", "gabinete_predio": "ultimoStatus.gabinete.predio",
                    "gabinete_sala": "ultimoStatus.gabinete.sala", "gabinete_andar": "ultimoStatus.gabinete.andar",
                    "gabinete_telefone": "ultimoStatus.gabinete.telefone"}, prioridade=1),
            ],
            regras=[not_null("nome"), in_set("sigla_uf", UFS),
                    date_between("data_nascimento", date(1900, 1, 1), HOJE - timedelta(days=18 * 365))],
        ),
        Entidade(
            "deputados_historico", ["id_deputado", "data_hora", "id_legislatura"],
            {"id_deputado": "int", "data_hora": "ts", "id_legislatura": "int", "nome": "text",
             "nome_eleitoral": "text", "sigla_partido": "text", "sigla_uf": "text", "situacao": "text",
             "condicao_eleitoral": "text", "descricao_status": "text"},
            [Fonte("deputados_historico", {
                "id_deputado": "@id_pai", "data_hora": "dataHora", "id_legislatura": "idLegislatura",
                "nome": "nome", "nome_eleitoral": "nomeEleitoral", "sigla_partido": "siglaPartido",
                "sigla_uf": "siglaUf", "situacao": "situacao", "condicao_eleitoral": "condicaoEleitoral",
                "descricao_status": "descricaoStatus"})],
        ),
        Entidade(
            "deputados_profissoes", ["id_deputado", "chave"],
            {"id_deputado": "int", "chave": "text", "cod_tipo_profissao": "int", "titulo": "text", "data_hora": "ts"},
            [Fonte("deputados_profissoes", {"id_deputado": "@id_pai", "cod_tipo_profissao": "codTipoProfissao",
                                            "titulo": "titulo", "data_hora": "dataHora"})],
            transformar=com_chave("chave", ["cod_tipo_profissao", "titulo"]),
            regras=[_registro_vazio("cod_tipo_profissao", "titulo")],
        ),
        Entidade(
            "deputados_ocupacoes", ["id_deputado", "chave"],
            {"id_deputado": "int", "chave": "text", "titulo": "text", "entidade": "text", "entidade_uf": "text",
             "entidade_pais": "text", "ano_inicio": "int", "ano_fim": "int"},
            [Fonte("deputados_ocupacoes", {"id_deputado": "@id_pai", "titulo": "titulo", "entidade": "entidade",
                                           "entidade_uf": "entidadeUF", "entidade_pais": "entidadePais",
                                           "ano_inicio": "anoInicio", "ano_fim": "anoFim"})],
            transformar=com_chave("chave", ["titulo", "entidade", "ano_inicio"]),
            regras=[_registro_vazio("titulo", "entidade")],
        ),
        Entidade(
            "deputados_mandatos_externos", ["id_deputado", "chave"],
            {"id_deputado": "int", "chave": "text", "cargo": "text", "sigla_uf": "text", "municipio": "text",
             "ano_inicio": "int", "ano_fim": "int", "sigla_partido_eleicao": "text"},
            [Fonte("deputados_mandatos_externos", {
                "id_deputado": "@id_pai", "cargo": "cargo", "sigla_uf": "siglaUf", "municipio": "municipio",
                "ano_inicio": "anoInicio", "ano_fim": "anoFim", "sigla_partido_eleicao": "siglaPartidoEleicao"})],
            transformar=com_chave("chave", ["cargo", "sigla_uf", "municipio", "ano_inicio"]),
            regras=[_registro_vazio("cargo", "ano_inicio")],
        ),
        Entidade(
            "deputados_orgaos", ["id_deputado", "id_orgao", "cod_titulo", "data_inicio"], conformada=True,
            tipos={"id_deputado": "int", "id_orgao": "int", "cod_titulo": "int", "data_inicio": "date",
                   "sigla_orgao": "text", "nome_orgao": "text", "titulo": "text", "data_fim": "date"},
            fontes=[
                Fonte("deputados_orgaos", {
                    "id_deputado": "@id_pai", "id_orgao": "idOrgao", "cod_titulo": "codTitulo",
                    "data_inicio": "dataInicio", "sigla_orgao": "siglaOrgao", "nome_orgao": "nomeOrgao",
                    "titulo": "titulo", "data_fim": "dataFim"}, prioridade=1),
                Fonte("orgaos_membros", {
                    "id_deputado": "id", "id_orgao": "@id_pai", "cod_titulo": "codTitulo",
                    "data_inicio": "dataInicio", "titulo": "titulo", "data_fim": "dataFim"}),
            ],
        ),
        Entidade(
            "orgaos_membros", ["id_orgao", "id_deputado", "cod_titulo", "data_inicio"], conformada=True,
            tipos={"id_orgao": "int", "id_deputado": "int", "cod_titulo": "int", "data_inicio": "date",
                   "nome": "text", "sigla_partido": "text", "sigla_uf": "text", "titulo": "text", "data_fim": "date"},
            fontes=[
                Fonte("orgaos_membros", {
                    "id_orgao": "@id_pai", "id_deputado": "id", "cod_titulo": "codTitulo",
                    "data_inicio": "dataInicio", **_DEP_RESUMO, "titulo": "titulo", "data_fim": "dataFim"}, prioridade=1),
                Fonte("deputados_orgaos", {
                    "id_orgao": "idOrgao", "id_deputado": "@id_pai", "cod_titulo": "codTitulo",
                    "data_inicio": "dataInicio", "titulo": "titulo", "data_fim": "dataFim"}),
            ],
        ),
        Entidade(
            "deputados_frentes", ["id_deputado", "id_frente"], conformada=True,
            tipos={"id_deputado": "int", "id_frente": "int", "titulo": "text", "id_legislatura": "int"},
            fontes=[
                Fonte("deputados_frentes", {"id_deputado": "@id_pai", "id_frente": "id", "titulo": "titulo",
                                            "id_legislatura": "idLegislatura"}, prioridade=1),
                Fonte("frentes_membros", {"id_deputado": "id", "id_frente": "@id_pai"}),
            ],
        ),
        Entidade(
            "discursos", ["id_deputado", "data_hora_inicio", "tipo_discurso", "hash_url"],
            {"id_deputado": "int", "data_hora_inicio": "ts", "tipo_discurso": "text", "hash_url": "text",
             "data_hora_fim": "ts", "id_evento": "int", "fase_titulo": "text", "sumario": "text",
             "keywords": "text", "transcricao": "text", "url_texto": "text", "url_audio": "text", "url_video": "text"},
            [Fonte("deputados_discursos", {
                "id_deputado": "@id_pai", "data_hora_inicio": "dataHoraInicio", "tipo_discurso": "tipoDiscurso",
                "data_hora_fim": "dataHoraFim", "id_evento": "@id:uriEvento", "fase_titulo": "faseEvento.titulo",
                "sumario": "sumario", "keywords": "keywords", "transcricao": "transcricao",
                "url_texto": "urlTexto", "url_audio": "urlAudio", "url_video": "urlVideo"})],
            transformar=com_chave("hash_url", ["url_texto"]),
        ),
        Entidade(
            "despesas", ["chave_despesa"],
            {"chave_despesa": "text", "id_deputado": "int", "ano": "int", "mes": "int", "tipo_despesa": "text",
             "cod_documento": "bigint", "tipo_documento": "text", "data_documento": "date", "num_documento": "text",
             "valor_documento": "num", "valor_liquido": "num", "valor_glosa": "num", "nome_fornecedor": "text",
             "cnpj_cpf_fornecedor": "text", "url_documento": "text", "parcela": "int",
             "num_ressarcimento": "text", "cod_lote": "bigint"},
            [Fonte("deputados_despesas", {
                "id_deputado": "@id_pai", "ano": "ano", "mes": "mes", "tipo_despesa": "tipoDespesa",
                "cod_documento": "codDocumento", "tipo_documento": "tipoDocumento",
                "data_documento": "dataDocumento", "num_documento": "numDocumento",
                "valor_documento": "valorDocumento", "valor_liquido": "valorLiquido", "valor_glosa": "valorGlosa",
                "nome_fornecedor": "nomeFornecedor", "cnpj_cpf_fornecedor": "cnpjCpfFornecedor",
                "url_documento": "urlDocumento", "parcela": "parcela", "num_ressarcimento": "numRessarcimento",
                "cod_lote": "codLote"})],
            transformar=_despesas,
            regras=[non_negative("valor_documento"), _sinal_corrigido(), between("mes", 1, 12),
                    date_between("data_documento", date(2000, 1, 1), HOJE + timedelta(days=1))],
        ),
        # ---------------------------------------------------------- órgãos e eventos
        Entidade(
            "orgaos", ["id_orgao"],
            {"id_orgao": "int", "sigla": "text", "nome": "text", "apelido": "text", "nome_resumido": "text",
             "nome_publicacao": "text", "cod_tipo_orgao": "int", "tipo_orgao": "text", "data_inicio": "date",
             "data_fim": "date", "data_instalacao": "date", "casa": "text", "sala": "text",
             "url_website": "text", "uri": "text"},
            [
                Fonte("orgaos", {
                    "id_orgao": "id", "sigla": "sigla", "nome": "nome", "apelido": "apelido",
                    "nome_resumido": "nomeResumido", "nome_publicacao": "nomePublicacao",
                    "cod_tipo_orgao": "codTipoOrgao", "tipo_orgao": "tipoOrgao", "uri": "uri"}),
                Fonte("orgaos_detalhe", {
                    "id_orgao": "id", "sigla": "sigla", "nome": "nome", "apelido": "apelido",
                    "nome_resumido": "nomeResumido", "nome_publicacao": "nomePublicacao",
                    "cod_tipo_orgao": "codTipoOrgao", "tipo_orgao": "tipoOrgao", "data_inicio": "dataInicio",
                    "data_fim": "dataFim", "data_instalacao": "dataInstalacao", "casa": "casa", "sala": "sala",
                    "url_website": "urlWebsite", "uri": "uri"}, prioridade=1),
            ],
        ),
        Entidade(
            "eventos", ["id_evento"],
            {"id_evento": "int", "data_hora_inicio": "ts", "data_hora_fim": "ts", "situacao": "text",
             "descricao_tipo": "text", "descricao": "text", "local_camara_nome": "text",
             "local_camara_predio": "text", "local_camara_sala": "text", "local_externo": "text",
             "url_registro": "text", "url_documento_pauta": "text"},
            [
                Fonte("eventos", _EVENTO, prioridade=1),
                Fonte("eventos_detalhe", {**_EVENTO, "url_documento_pauta": "urlDocumentoPauta"}, prioridade=2),
                Fonte("deputados_eventos", _EVENTO),
                Fonte("orgaos_eventos", _EVENTO),
            ],
            regras=[date_between("data_hora_inicio", date(2000, 1, 1), HOJE + timedelta(days=365))],
        ),
        Entidade(
            "eventos_orgaos", ["id_evento", "id_orgao"], conformada=True,
            tipos={"id_evento": "int", "id_orgao": "int", "sigla_orgao": "text", "nome_orgao": "text"},
            fontes=[
                Fonte("eventos_orgaos", {"id_evento": "@id_pai", "id_orgao": "id", "sigla_orgao": "sigla",
                                         "nome_orgao": "nome"}, prioridade=1),
                Fonte("eventos", {"id_evento": "id", "id_orgao": "orgaos[].id", "sigla_orgao": "orgaos[].sigla",
                                  "nome_orgao": "orgaos[].nome"}, explodir="orgaos"),
                Fonte("orgaos_eventos", {"id_evento": "id", "id_orgao": "@id_pai"}),
            ],
        ),
        Entidade(
            "eventos_deputados", ["id_evento", "id_deputado"], conformada=True,
            tipos={"id_evento": "int", "id_deputado": "int", "nome": "text", "sigla_partido": "text", "sigla_uf": "text"},
            fontes=[
                Fonte("eventos_deputados", {"id_evento": "@id_pai", "id_deputado": "id", **_DEP_RESUMO}, prioridade=1),
                Fonte("deputados_eventos", {"id_evento": "id", "id_deputado": "@id_pai"}),
            ],
        ),
        Entidade(
            "eventos_pauta", ["id_evento", "ordem", "id_proposicao"],
            {"id_evento": "int", "ordem": "int", "id_proposicao": "int", "topico": "text", "regime": "text",
             "titulo": "text", "id_relator": "int", "nome_relator": "text", "situacao_item": "text",
             "texto_parecer": "text", "id_proposicao_relacionada": "int", "uri_votacao": "text"},
            [Fonte("eventos_pauta", {
                "id_evento": "@id_pai", "ordem": "ordem", "id_proposicao": "proposicao_.id", "topico": "topico",
                "regime": "regime", "titulo": "titulo", "id_relator": "relator.id", "nome_relator": "relator.nome",
                "situacao_item": "situacaoItem", "texto_parecer": "textoParecer",
                "id_proposicao_relacionada": "proposicaoRelacionada_.id", "uri_votacao": "uriVotacao"})],
            transformar=_pauta_sem_proposicao,
        ),
        # ---------------------------------------------------------- frentes e grupos
        Entidade(
            "frentes", ["id_frente"],
            {"id_frente": "int", "titulo": "text", "id_legislatura": "int", "situacao": "text", "keywords": "text",
             "telefone": "text", "email": "text", "url_website": "text", "url_documento": "text",
             "id_coordenador": "int", "nome_coordenador": "text"},
            [
                Fonte("frentes", {"id_frente": "id", "titulo": "titulo", "id_legislatura": "idLegislatura"}),
                Fonte("frentes_detalhe", {
                    "id_frente": "id", "titulo": "titulo", "id_legislatura": "idLegislatura", "situacao": "situacao",
                    "keywords": "keywords", "telefone": "telefone", "email": "email", "url_website": "urlWebsite",
                    "url_documento": "urlDocumento", "id_coordenador": "coordenador.id",
                    "nome_coordenador": "coordenador.nome"}, prioridade=1),
            ],
        ),
        Entidade(
            "frentes_membros", ["id_frente", "id_deputado", "cod_titulo"],
            {"id_frente": "int", "id_deputado": "int", "cod_titulo": "int", **dict.fromkeys(
                ["nome", "sigla_partido", "sigla_uf", "titulo"], "text"), "data_inicio": "date", "data_fim": "date"},
            [Fonte("frentes_membros", {"id_frente": "@id_pai", "id_deputado": "id", "cod_titulo": "codTitulo",
                                       **_DEP_RESUMO, "titulo": "titulo", "data_inicio": "dataInicio",
                                       "data_fim": "dataFim"})],
        ),
        Entidade(
            "grupos", ["id_grupo"],
            {"id_grupo": "int", "nome": "text", "ano_criacao": "int", "resolucao_titulo": "text",
             "subvencionado": "bool", "grupo_misto": "bool", "ativo": "bool", "observacoes": "text",
             "id_legislatura_status": "int", "data_status": "date", "presidente_nome": "text", "uri": "text"},
            [
                Fonte("grupos", {
                    "id_grupo": "id", "nome": "nome", "ano_criacao": "anoCriacao", "resolucao_titulo": "resolucaoTitulo",
                    "subvencionado": "subvencionado", "grupo_misto": "grupoMisto", "ativo": "ativo",
                    "observacoes": "observacoes", "id_legislatura_status": "ultimoStatus.idLegislatura",
                    "data_status": "ultimoStatus.dataStatus", "presidente_nome": "ultimoStatus.presidenteNome",
                    "uri": "uri"}),
                Fonte("grupos_detalhe", {
                    "id_grupo": "id", "nome": "nome", "ano_criacao": "anoCriacao", "resolucao_titulo": "resolucaoTitulo",
                    "subvencionado": "subvencionado", "grupo_misto": "grupoMisto", "ativo": "ativo",
                    "observacoes": "observacoes", "id_legislatura_status": "ultimoStatusID.idLegislatura",
                    "data_status": "ultimoStatusID.dataStatus", "presidente_nome": "ultimoStatusID.presidenteNome",
                    "uri": "uri"}, prioridade=1),
            ],
        ),
        Entidade(
            "grupos_historico", ["id_grupo", "chave"],
            {"id_grupo": "int", "chave": "text", "id_legislatura": "int", "data_status": "date",
             "documento_sgm": "text", "oficio_titulo": "text", "oficio_autor_tipo": "text", "oficio_autor": "text",
             "data_apresentacao": "date", "data_publicacao": "date", "presidente": "text", "observacao": "text"},
            [Fonte("grupos_historico", {
                "id_grupo": "@id_pai", "id_legislatura": "idLegislatura", "data_status": "dataStatus",
                "documento_sgm": "documentoSGM", "oficio_titulo": "oficioTitulo", "oficio_autor_tipo": "oficioAutorTipo",
                "oficio_autor": "oficioAutor", "data_apresentacao": "oficioDataApresentacao",
                "data_publicacao": "oficioDataPublicacao", "presidente": "presidente", "observacao": "observacao"})],
            transformar=com_chave("chave", ["id_legislatura", "data_status", "documento_sgm"]),
        ),
        Entidade(
            "grupos_membros", ["id_grupo", "chave"],
            {"id_grupo": "int", "chave": "text", "id_membro": "int", "nome": "text", "tipo": "text", "cargo": "text",
             "id_legislatura": "int", "ordem_entrada": "int", "data_inicio": "date", "data_fim": "date"},
            [Fonte("grupos_membros", {
                "id_grupo": "id", "id_membro": "@id:membros[].uri", "nome": "membros[].nome", "tipo": "membros[].tipo",
                "cargo": "membros[].cargo", "id_legislatura": "membros[].idLegislatura",
                "ordem_entrada": "membros[].ordemEntrada", "data_inicio": "membros[].dataInicio",
                "data_fim": "membros[].dataFim"}, explodir="membros")],
            transformar=com_chave("chave", ["id_membro", "nome", "cargo", "data_inicio"]),
        ),
        # ---------------------------------------------------------- proposições
        Entidade(
            "proposicoes", ["id_proposicao"],
            {"id_proposicao": "int", "sigla_tipo": "text", "cod_tipo": "int", "descricao_tipo": "text",
             "numero": "int", "ano": "int", "ementa": "text", "ementa_detalhada": "text", "keywords": "text",
             "data_apresentacao": "ts", "cod_situacao": "int", "situacao": "text", "orgao_situacao": "text",
             "regime": "text", "apreciacao": "text", "despacho": "text", "data_ultima_tramitacao": "ts",
             "url_inteiro_teor": "text", "uri": "text"},
            [
                Fonte("proposicoes", {
                    "id_proposicao": "id", "sigla_tipo": "siglaTipo", "cod_tipo": "codTipo", "numero": "numero",
                    "ano": "ano", "ementa": "ementa", "data_apresentacao": "dataApresentacao", "uri": "uri"}),
                Fonte("proposicoes_detalhe", {
                    "id_proposicao": "id", "sigla_tipo": "siglaTipo", "cod_tipo": "codTipo",
                    "descricao_tipo": "descricaoTipo", "numero": "numero", "ano": "ano", "ementa": "ementa",
                    "ementa_detalhada": "ementaDetalhada", "keywords": "keywords",
                    "data_apresentacao": "dataApresentacao", "cod_situacao": "statusProposicao.codSituacao",
                    "situacao": "statusProposicao.descricaoSituacao", "orgao_situacao": "statusProposicao.siglaOrgao",
                    "regime": "statusProposicao.regime", "apreciacao": "statusProposicao.apreciacao",
                    "despacho": "statusProposicao.despacho", "data_ultima_tramitacao": "statusProposicao.dataHora",
                    "url_inteiro_teor": "urlInteiroTeor", "uri": "uri"}, prioridade=1),
            ],
            regras=[not_null("ementa", "sigla_tipo"),
                    date_between("data_apresentacao", date(1946, 1, 1), HOJE + timedelta(days=1))],
        ),
        Entidade(
            "proposicoes_autores", ["id_proposicao", "nome_autor"],
            {"id_proposicao": "int", "nome_autor": "text", "id_deputado": "int", "uri_autor": "text",
             "cod_tipo": "int", "tipo_autor": "text", "ordem_assinatura": "int", "proponente": "bool"},
            [Fonte("proposicoes_autores", {
                "id_proposicao": "@id_pai", "nome_autor": "nome", "id_deputado": "@id:uri", "uri_autor": "uri",
                "cod_tipo": "codTipo", "tipo_autor": "tipo", "ordem_assinatura": "ordemAssinatura",
                "proponente": "proponente"})],
            transformar=_so_deputados,
        ),
        Entidade(
            "proposicoes_temas", ["id_proposicao", "cod_tema"],
            {"id_proposicao": "int", "cod_tema": "int", "tema": "text", "relevancia": "int"},
            [Fonte("proposicoes_temas", {"id_proposicao": "@id_pai", "cod_tema": "codTema", "tema": "tema",
                                         "relevancia": "relevancia"})],
        ),
        Entidade(
            "proposicoes_relacionadas", ["id_proposicao", "id_relacionada"],
            {"id_proposicao": "int", "id_relacionada": "int", "sigla_tipo": "text", "numero": "int", "ano": "int",
             "ementa": "text"},
            [Fonte("proposicoes_relacionadas", {"id_proposicao": "@id_pai", "id_relacionada": "id",
                                                "sigla_tipo": "siglaTipo", "numero": "numero", "ano": "ano",
                                                "ementa": "ementa"})],
        ),
        Entidade(
            "proposicoes_tramitacoes", ["id_proposicao", "sequencia"],
            {"id_proposicao": "int", "sequencia": "int", "data_hora": "ts", "sigla_orgao": "text", "id_orgao": "int",
             "regime": "text", "cod_tipo_tramitacao": "text", "descricao_tramitacao": "text", "cod_situacao": "int",
             "descricao_situacao": "text", "despacho": "text", "ambito": "text", "apreciacao": "text", "url": "text",
             "id_ultimo_relator": "int"},
            [Fonte("proposicoes_tramitacoes", {
                "id_proposicao": "@id_pai", "sequencia": "sequencia", "data_hora": "dataHora",
                "sigla_orgao": "siglaOrgao", "id_orgao": "@id:uriOrgao", "regime": "regime",
                "cod_tipo_tramitacao": "codTipoTramitacao", "descricao_tramitacao": "descricaoTramitacao",
                "cod_situacao": "codSituacao", "descricao_situacao": "descricaoSituacao", "despacho": "despacho",
                "ambito": "ambito", "apreciacao": "apreciacao", "url": "url",
                "id_ultimo_relator": "@id:uriUltimoRelator"})],
        ),
        # ---------------------------------------------------------- votações
        Entidade(
            "votacoes", ["id_votacao"],
            {"id_votacao": "text", "data": "date", "data_hora_registro": "ts", "id_orgao": "int",
             "sigla_orgao": "text", "id_evento": "int", "aprovacao": "int", "descricao": "text", "uri": "text"},
            [
                Fonte("votacoes", _VOTACAO, prioridade=1),
                Fonte("votacoes_detalhe", {**_VOTACAO, "id_orgao": "idOrgao", "id_evento": "idEvento"}, prioridade=2),
                Fonte("eventos_votacoes", _VOTACAO),
                Fonte("orgaos_votacoes", _VOTACAO),
                Fonte("proposicoes_votacoes", _VOTACAO),
            ],
            regras=[date_between("data", date(2000, 1, 1), HOJE + timedelta(days=1))],
        ),
        Entidade(
            "votacoes_proposicoes", ["id_votacao", "id_proposicao", "papel"], conformada=True,
            tipos={"id_votacao": "text", "id_proposicao": "int", "papel": "text", "sigla_tipo": "text",
                   "numero": "int", "ano": "int"},
            fontes=[
                *[Fonte(b, _OBJETO, filtro=_tem("uriProposicaoObjeto"))
                  for b in ("votacoes", "eventos_votacoes", "orgaos_votacoes")],
                Fonte("proposicoes_votacoes", {"id_votacao": "id", "id_proposicao": "@id_pai",
                                               "papel": "@const:votada_na_tramitacao"}),
                Fonte("votacoes_detalhe", {
                    "id_votacao": "id", "id_proposicao": "objetosPossiveis[].id", "papel": "@const:possivel",
                    "sigla_tipo": "objetosPossiveis[].siglaTipo", "numero": "objetosPossiveis[].numero",
                    "ano": "objetosPossiveis[].ano"}, explodir="objetosPossiveis"),
                Fonte("votacoes_detalhe", {
                    "id_votacao": "id", "id_proposicao": "proposicoesAfetadas[].id", "papel": "@const:afetada",
                    "sigla_tipo": "proposicoesAfetadas[].siglaTipo", "numero": "proposicoesAfetadas[].numero",
                    "ano": "proposicoesAfetadas[].ano"}, explodir="proposicoesAfetadas"),
            ],
        ),
        Entidade(
            "votacoes_orientacoes", ["id_votacao", "sigla_partido_bloco"],
            {"id_votacao": "text", "sigla_partido_bloco": "text", "orientacao_voto": "text",
             "cod_tipo_lideranca": "text", "cod_partido_bloco": "int"},
            [Fonte("votacoes_orientacoes", {
                "id_votacao": "@id_pai", "sigla_partido_bloco": "siglaPartidoBloco",
                "orientacao_voto": "orientacaoVoto", "cod_tipo_lideranca": "codTipoLideranca",
                "cod_partido_bloco": "codPartidoBloco"})],
        ),
        Entidade(
            "votos", ["id_votacao", "id_deputado"],
            {"id_votacao": "text", "id_deputado": "int", "tipo_voto": "text", "data_registro_voto": "ts",
             "nome": "text", "sigla_partido": "text", "sigla_uf": "text"},
            [Fonte("votacoes_votos", {
                "id_votacao": "@id_pai", "id_deputado": "deputado_.id", "tipo_voto": "tipoVoto",
                "data_registro_voto": "dataRegistroVoto", "nome": "deputado_.nome",
                "sigla_partido": "deputado_.siglaPartido", "sigla_uf": "deputado_.siglaUf"})],
            regras=[in_set("tipo_voto", {"Sim", "Não", "Abstenção", "Obstrução", "Artigo 17"}, rejeita=False)],
        ),
    ]  # fmt: skip
