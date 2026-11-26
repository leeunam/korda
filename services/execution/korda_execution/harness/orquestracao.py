"""Ponto único que o worker chama: construir, testar e corrigir até o limite.

O worker só orquestra: gera o documento-base, prepara a sandbox, chama esta
função e depois avalia e entrega. `executar_etapa` (ciclo K10 do #21) entra
por parâmetro, para este módulo não depender do merge.
"""

from __future__ import annotations

from collections.abc import Callable


def construir_e_verificar(construtor, corretor: Callable[[dict, int], dict], tentar: Callable[[], dict],
                          executar_etapa: Callable, registrar: Callable[[str, dict], None], *, limite: int,
                          documento_base: str | None) -> dict:
    """Construção pelo harness, depois build e até `limite` correções. Nunca aprova sozinho."""
    construcao = construtor.construir(documento_base)
    if not construcao.get("ok"):
        resultado = {"ok": False, "codigo": "construcao_falhou",
                     "erro": construcao.get("erro") or "a construção não produziu modelos", "construcao": construcao}
        registrar("intervention_requested", dict(resultado))
        return resultado
    etapa = executar_etapa(tentar, corretor, registrar, limite=limite)
    return {**etapa, "construcao": construcao}
