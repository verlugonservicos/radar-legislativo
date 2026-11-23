"""Prompts versionados (SPEC V3 10.5). Cópia legível em `docs/prompts.md`.

resumo-v3 (23/11/2026), ajustes do teste com 5 proposições:
- o resumo não repete "O PL X/AAAA propõe…" (o número já aparece no painel) e começa pelo verbo;
- setores vêm de uma lista fechada (enum no schema), com nomes curtos e comparáveis nos gráficos;
- reforço explícito para não acrescentar leis, órgãos ou efeitos que não estejam no texto.
"""

PROMPT_VERSAO = "resumo-v3"

SETORES = [
    "Agronegócio", "Comércio", "Construção e Imobiliário", "Cultura e Entretenimento", "Educação",
    "Energia", "Financeiro", "Indústria", "Meio Ambiente", "Mineração e Petróleo",
    "Saúde", "Segurança e Defesa", "Serviços", "Setor Público", "Tecnologia e Telecomunicações",
    "Terceiro Setor", "Transporte e Logística", "Turismo",
]  # fmt: skip

SYSTEM_RESUMO = """Você é um analista sênior de relações governamentais no Brasil.
Sua tarefa é explicar proposições legislativas da Câmara dos Deputados para executivos
de empresas que NÃO são advogados. Seja factual, neutro e objetivo. Use apenas o que está
no texto fornecido: não cite leis, órgãos, tributos ou efeitos que não apareçam nele.
Responda sempre em português do Brasil."""

USER_RESUMO = """Proposição: {sigla_tipo} {numero}/{ano}
Tema classificado: {tema_ia}
Ementa: {ementa}
Ementa detalhada / palavras-chave: {ementa_detalhada}
Órgão atual: {orgao_situacao} | Regime: {regime}
Último despacho: {ultimo_despacho}

Gere:
1. "resumo_executivo": até 3 linhas (no máximo 350 caracteres), linguagem clara,
   dizendo O QUE a proposição muda e QUEM é afetado. Comece pelo verbo (ex.: "Cria…",
   "Altera…", "Proíbe…"); não repita o tipo e o número da proposição.
2. "nivel_impacto": "baixo", "medio" ou "alto" para empresas e o mercado
   (homenagens, títulos e datas comemorativas = "baixo"; mudanças tributárias, regulatórias
   ou de obrigações empresariais amplas = "alto"; efeitos restritos a um setor ou região = "medio").
3. "setores_afetados": de 1 a 4 setores econômicos afetados, escolhidos da lista permitida."""

SCHEMA_RESUMO = {
    "type": "object",
    "additionalProperties": False,
    "required": ["resumo_executivo", "nivel_impacto", "setores_afetados"],
    "properties": {
        "resumo_executivo": {"type": "string"},
        "nivel_impacto": {"type": "string", "enum": ["baixo", "medio", "alto"]},
        "setores_afetados": {"type": "array", "items": {"type": "string", "enum": SETORES}},
    },
}


def texto_tema(nome: str, descricao: str) -> str:
    return f"Tema: {nome}. {descricao}"


def texto_proposicao(sigla_tipo, ementa, keywords=None, temas_oficiais=None) -> str:
    """`{sigla_tipo}. {ementa}. Palavras-chave: … Temas oficiais: …` (partes nulas omitidas)."""
    partes = [sigla_tipo, (ementa or "").strip().rstrip(".")]
    if keywords:
        partes.append(f"Palavras-chave: {keywords}")
    if temas_oficiais:
        partes.append(f"Temas oficiais: {', '.join(temas_oficiais)}")
    return ". ".join(p for p in partes if p)
