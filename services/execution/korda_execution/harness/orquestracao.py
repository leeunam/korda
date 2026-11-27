"""Ponto único que o worker chama: construir, testar e corrigir até o limite.

O planejamento anexa o documento-base antes da primeira aprovação. O worker
prepara a sandbox e fornece a especificação aprovada e o ciclo limitado de
correção. A avaliação independente e a revisão da entrega seguem no host.
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
