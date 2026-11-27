"""Ciclo limitado de correção de uma etapa do plano já aprovado (K10)."""

from __future__ import annotations

from collections.abc import Callable


def executar_etapa(
    tentar: Callable[[], dict],
    corrigir: Callable[[dict, int], dict] | None,
    registrar: Callable[[str, dict], None],
    *,
    limite: int = 3,
) -> dict:
    """Valida a etapa após cada correção, inclusive após a última permitida.

    Somente o diagnóstico 'implementacao' permite corrigir. O chamador fornece
    um corretor com acesso exclusivo aos modelos autorizados pelo plano. O
    custo é a soma, em centavos, dos valores informados pelas correções.
    Qualquer falha de registro aborta a chamada antes de prosseguir.
    """
    if type(limite) is not int or not 0 <= limite <= 3:
        raise ValueError("limite deve ser um inteiro de 0 a 3 correções por etapa")

    tentativas = correcoes = custo_centavos = 0

    def resumo() -> dict:
        return {"tentativas": tentativas, "correcoes": correcoes, "custo_centavos": custo_centavos}

    def escalar(codigo: str, erro: str, *, custo_completo: bool = True) -> dict:
        resultado = {"ok": False, "codigo": codigo, "erro": erro,
                     "custo_completo": custo_completo, **resumo()}
        registrar("intervention_requested", resultado.copy())
        return resultado

    while True:
        tentativas += 1
        try:
            teste = tentar()
        except Exception as exc:
            teste = {"ok": False, "codigo": "tecnico", "erro": f"Execução interrompida ({type(exc).__name__})"}
        if not isinstance(teste, dict) or type(teste.get("ok")) is not bool:
            teste = {"ok": False, "codigo": "tecnico", "erro": "Verificador retornou um resultado inválido"}
        if teste["ok"]:
            registrar("test_passed", resumo())
            return {"ok": True, "custo_completo": True, **resumo()}

        codigo = teste.get("codigo")
        if not isinstance(codigo, str) or not codigo:
            codigo = "nao_classificado"
        erro = str(teste.get("erro") or "A etapa falhou sem uma descrição")[:2000]
        registrar("test_failed", {"codigo": codigo, "erro": erro, **resumo()})
        if codigo != "implementacao":
            return escalar(codigo, erro)
        if corrigir is None:
            return escalar("sem_corretor", erro)
        if correcoes >= limite:
            return escalar("limite_atingido", erro)

        correcoes += 1
        registrar("fix_started", resumo())
        try:
            ajuste = corrigir(teste, correcoes)
        except Exception as exc:
            erro = f"Correção interrompida ({type(exc).__name__})"
            registrar("fix_failed", {"erro": erro, "custo_completo": False, **resumo()})
            return escalar("correcao_interrompida", erro, custo_completo=False)

        custo = ajuste.get("custo_centavos") if isinstance(ajuste, dict) else None
        custo_conhecido = type(custo) is int and custo >= 0
        if custo_conhecido:
            custo_centavos += custo
        if not custo_conhecido or type(ajuste.get("ok")) is not bool:
            erro = "O corretor não devolveu o resultado e o custo válidos para a tentativa"
            registrar("fix_failed", {"erro": erro, "custo_completo": custo_conhecido, **resumo()})
            return escalar("correcao_invalida", erro, custo_completo=custo_conhecido)
        if not ajuste["ok"]:
            erro = str(ajuste.get("erro") or "O corretor recusou a alteração")[:2000]
            registrar("fix_failed", {"erro": erro, **resumo()})
            return escalar("correcao_recusada", erro)
        registrar("fix_applied", {"custo_correcao_centavos": custo, **resumo()})
