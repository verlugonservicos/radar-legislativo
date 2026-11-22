"""Grava uma resposta real de cada endpoint em `tests/fixtures/api/` (M1, SPEC V3 seção 18).

As fixtures alimentam os testes sem rede e servem para confirmar os campos marcados com ⚠️
na SPEC. Listas são cortadas em `MAX_ITENS` registros para manter o repositório leve; o
total original fica em `_meta.registros_originais`.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from radar.catalog.loader import load_catalog, topological_order
from radar.catalog.models import EndpointSpec
from radar.config import RAIZ_PROJETO, get_settings

log = logging.getLogger("radar.catalog.amostras")

FIXTURES = RAIZ_PROJETO / "tests" / "fixtures" / "api"
MAX_ITENS = 5
MAX_TENTATIVAS_ID = 15  # IDs testados até achar uma resposta não vazia


CPF_MASCARA = "00000000000"


def mascarar_pessoais(valor: object) -> object:
    """Troca CPFs por zeros: `cpf` (deputados) e `cnpjCpfFornecedor` de pessoa física (11 dígitos).

    Os dados são públicos na API, mas o repositório não precisa carregá-los (SPEC: CPF fica só
    na Bronze). CNPJ (14 dígitos) é mantido.
    """
    if isinstance(valor, list):
        return [mascarar_pessoais(v) for v in valor]
    if not isinstance(valor, dict):
        return valor
    saida = {}
    for chave, v in valor.items():
        digitos = "".join(c for c in str(v) if c.isdigit()) if isinstance(v, str) else ""
        cpf_deputado = chave == "cpf" and bool(v)
        cpf_fornecedor = chave == "cnpjCpfFornecedor" and len(digitos) == 11
        if cpf_deputado or cpf_fornecedor:
            saida[chave] = CPF_MASCARA
        else:
            saida[chave] = mascarar_pessoais(v)
    return saida


def _valores(hoje: date, dias: int = 7) -> dict[str, str]:
    s = get_settings()
    fim = hoje - timedelta(days=1)
    inicio = fim - timedelta(days=dias - 1)
    if inicio.year != fim.year:  # janelas de votações não podem cruzar o ano
        inicio = date(fim.year, 1, 1)
    mes_passado = hoje.replace(day=1) - timedelta(days=1)
    return {
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "ano": str(mes_passado.year),
        "mes": str(mes_passado.month),
        "id_legislatura": str(s.id_legislatura),
        "inicio_legislatura": s.inicio_legislatura.isoformat(),
        "hoje": hoje.isoformat(),
    }


def _render(params: dict[str, str], valores: dict[str, str]) -> dict[str, str]:
    return {k: v.format(**valores) for k, v in params.items()}


def _extrai(registro: dict, campo: str) -> list:
    """`id`, `parlamentar.id` ou `orgaos[].id` → lista de valores."""
    if "[]." in campo:
        lista, resto = campo.split("[].", 1)
        return [v for item in registro.get(lista) or [] for v in _extrai(item, resto)]
    valor: object = registro
    for parte in campo.split("."):
        valor = valor.get(parte) if isinstance(valor, dict) else None
    return [] if valor is None else [valor]


def _ids_candidatos(spec: EndpointSpec, respostas: dict[str, dict]) -> list:
    ids: list = []
    for origem in spec.ids.de if spec.ids else []:
        dados = (respostas.get(origem) or {}).get("dados")
        registros = dados if isinstance(dados, list) else [dados] if isinstance(dados, dict) else []
        # Votações do Plenário costumam ser nominais (com votos e orientações): vêm primeiro.
        registros = sorted(registros, key=lambda r: r.get("siglaOrgao") != "PLEN")
        for r in registros:
            for v in _extrai(r, spec.ids.campo):
                if v not in ids:
                    ids.append(v)
    if spec.ids and spec.ids.filtro == "legislaturas_recentes":
        ids = [i for i in ids if int(i) >= get_settings().id_legislatura - 2] or ids
    return ids[:MAX_TENTATIVAS_ID]


class Coletor:
    """Cliente HTTP mínimo para a coleta de amostras (o cliente completo é do M2)."""

    def __init__(self) -> None:
        s = get_settings()
        self.base = s.camara_base_url.rstrip("/")
        self.throttle = max(s.camara_throttle_segundos, 0.3)
        self.timeout = (s.camara_timeout_connect, s.camara_timeout_read)
        self.sessao = requests.Session()
        self.sessao.headers.update(
            {"User-Agent": s.camara_user_agent, "Accept": "application/json"}
        )
        self._ultima = 0.0

    def get(self, path: str, params: dict) -> tuple[int, dict | None, str]:
        espera = self.throttle - (time.monotonic() - self._ultima)
        if espera > 0:
            time.sleep(espera)
        for tentativa in range(3):
            self._ultima = time.monotonic()
            r = self.sessao.get(self.base + path, params=params, timeout=self.timeout)
            if r.status_code in (429, 500, 502, 503, 504) and tentativa < 2:
                time.sleep(2 * (tentativa + 1))
                continue
            corpo = r.json() if "json" in r.headers.get("Content-Type", "") and r.content else None
            return r.status_code, corpo, r.url
        return r.status_code, None, r.url


def _vazio(corpo: dict | None) -> bool:
    if not corpo:
        return True
    dados = corpo.get("dados")
    return dados in (None, [], {})


def _e_origem(nome: str, apenas: set[str]) -> bool:
    """Mantém os endpoints de origem dos IDs necessários aos pedidos em `apenas`."""
    specs = {s.nome: s for s in load_catalog()}
    pendentes, vistos = list(apenas), set()
    while pendentes:
        atual = specs.get(pendentes.pop())
        if atual and atual.ids:
            for origem in atual.ids.de:
                if origem == nome:
                    return True
                if origem not in vistos:
                    vistos.add(origem)
                    pendentes.append(origem)
    return False


def coletar(
    destino: Path = FIXTURES,
    hoje: date | None = None,
    apenas: set[str] | None = None,
    dias: int = 7,
    id_pai: str | None = None,
) -> dict[str, str]:
    """Chama cada endpoint uma vez (na ordem de dependência) e grava a fixture."""
    hoje = hoje or date.today()
    valores = _valores(hoje, dias)
    destino.mkdir(parents=True, exist_ok=True)
    coletor = Coletor()
    respostas: dict[str, dict] = {}
    resultado: dict[str, str] = {}

    for spec in topological_order(load_catalog()):
        if apenas and spec.nome not in apenas and not _e_origem(spec.nome, apenas):
            continue
        params = _render(spec.params, valores) | _render(spec.janela.params, valores)
        if spec.janela.passes:
            params |= _render(spec.janela.passes[0], valores)
        if spec.paginado:
            # uma página cheia: mais IDs candidatos para os filhos; a fixture guarda só MAX_ITENS
            params |= {"itens": str(spec.itens)}

        alvos = [None]
        if "{id}" in spec.path and id_pai and apenas and spec.nome in apenas:
            alvos = [id_pai]  # ID indicado pelo usuário (ex.: uma votação nominal conhecida)
        elif "{id}" in spec.path:
            alvos = _ids_candidatos(spec, respostas)
            if not alvos:
                resultado[spec.nome] = "sem IDs de origem"
                log.warning("%s: sem IDs de origem", spec.nome)
                continue

        status, corpo, url, id_usado = 0, None, "", None
        for alvo in alvos:
            path = spec.path.replace("{id}", str(alvo)) if alvo is not None else spec.path
            status, corpo, url = coletor.get(path, params)
            id_usado = alvo
            if status == 200 and not _vazio(corpo):
                break

        if status != 200 or corpo is None:
            resultado[spec.nome] = f"HTTP {status}"
            log.warning("%s: HTTP %s em %s", spec.nome, status, url)
            continue

        respostas[spec.nome] = corpo
        dados = corpo.get("dados")
        originais = len(dados) if isinstance(dados, list) else (1 if dados else 0)
        fixture = dict(corpo)
        fixture["dados"] = mascarar_pessoais(
            dados[:MAX_ITENS] if isinstance(dados, list) else dados
        )
        fixture["_meta"] = {
            "endpoint": spec.nome,
            "path": spec.path,
            "url": url,
            "id_pai": id_usado,
            "coletado_em": hoje.isoformat(),
            "janela_dias": dias,
            "registros_originais": originais,
            "tipo_dados": type(dados).__name__,
        }
        (destino / f"{spec.nome}.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        resultado[spec.nome] = "vazio" if _vazio(corpo) else f"ok ({originais})"
        log.info("%s: %s", spec.nome, resultado[spec.nome])
    return resultado
