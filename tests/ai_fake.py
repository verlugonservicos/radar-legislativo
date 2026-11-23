"""Cliente de IA falso para os testes: nenhuma chamada à OpenAI.

Embeddings determinísticos por "saco de palavras" com hash (textos que compartilham palavras
ficam próximos), e resumo fixo que respeita o schema.
"""

import hashlib
import re

import numpy as np

DIM = 1536


def vetor(texto: str) -> list[float]:
    v = np.zeros(DIM)
    for palavra in re.findall(r"\w{4,}", texto.lower()):
        v[int(hashlib.md5(palavra.encode()).hexdigest(), 16) % DIM] += 1.0
    if not v.any():
        v[0] = 1.0
    return (v / np.linalg.norm(v)).tolist()


class ClienteFalso:
    def __init__(self, falhar_em: set[str] | None = None) -> None:
        self.chamadas_embed = 0
        self.chamadas_chat = 0
        self.falhar_em = falhar_em or set()

    def embed(self, texts):
        self.chamadas_embed += 1
        return [vetor(t) for t in texts], sum(len(t) // 4 for t in texts)

    def chat_json(self, system, user, schema):
        self.chamadas_chat += 1
        if any(f in user for f in self.falhar_em):
            raise ValueError("falha simulada")
        impacto = "baixo" if "Denomina" in user or "Institui o Dia" in user else "medio"
        return ({"resumo_executivo": "Altera regras " + "x" * 500, "nivel_impacto": impacto,
                 "setores_afetados": ["Serviços", "Serviços", "Setor Público"]}, 600, 90)  # fmt: skip
