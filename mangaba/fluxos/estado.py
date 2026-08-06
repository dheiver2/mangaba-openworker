"""Resolve, para cada fluxo, o que já está pronto e o que falta.

A regra que sustenta a tela inteira: **"pronto" só quando verificado**. Peça cadastrada não
é peça funcionando — um servidor MCP com OAuth aparece na lista antes de existir token, e
declará-lo pronto faria o fluxo prometer um trabalho que morre no meio. É a mesma lição do
provedor que autenticava e não executava ferramenta: o cadastro mente, o teste não.

Um fluxo que promete e não entrega é pior que fluxo nenhum — a pessoa perde a confiança na
tela toda, não só naquele cartão.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .identidade import conector_equivalente, mcps_equivalentes


def _estado_peca(pronta: bool, rotulo: str, tipo: str, acao: str = "") -> dict[str, Any]:
    return {"rotulo": rotulo, "tipo": tipo, "pronta": pronta, "acao": acao}


def resolver_fluxo(
    fluxo: dict[str, Any],
    *,
    skills_instaladas: set[str],
    skills_desativadas: set[str],
    mcps_conectados: set[str],
    mcps_conhecidos: dict[str, str],
    conectores_conectados: set[str],
    conectores_conhecidos: dict[str, str],
    modelo_pronto: bool,
    modelo_local_pronto: bool,
    rotulo_mcp: Optional[Callable[[str], str]] = None,
) -> dict[str, Any]:
    """Devolve o fluxo com uma lista de peças e o veredito de prontidão."""
    pecas: list[dict[str, Any]] = []

    for nome in fluxo.get("skills", []):
        instalada = nome in skills_instaladas
        ativa = instalada and nome not in skills_desativadas
        acao = ""
        if not instalada:
            acao = "instalar_skill"
        elif not ativa:
            acao = "ativar_skill"
        pecas.append(_estado_peca(ativa, nome, "skill", acao))

    for nome in fluxo.get("mcps", []):
        # O mesmo serviço pode estar conectado pela via nativa: se o conector equivalente já
        # está ligado, a peça está satisfeita — a sessão terá as tools daquele serviço de todo
        # jeito. Sem isto, quem conectou o Linear nativo veria o fluxo de MCP "faltando".
        equiv = conector_equivalente(nome)
        conectado = nome in mcps_conectados or (
            equiv is not None and equiv in conectores_conectados
        )
        rotulo = (rotulo_mcp(nome) if rotulo_mcp else None) or mcps_conhecidos.get(nome, nome)
        acao = "" if conectado else ("conectar_mcp" if nome in mcps_conhecidos else "instalar_mcp")
        pecas.append(_estado_peca(conectado, rotulo, "mcp", acao))

    for nome in fluxo.get("conectores", []):
        # Simétrico: um servidor MCP equivalente conectado satisfaz a peça de conector nativo,
        # para não pedir a MESMA conta duas vezes (nem criar conexão duplicada).
        conectado = nome in conectores_conectados or bool(
            mcps_equivalentes(nome) & mcps_conectados
        )
        rotulo = conectores_conhecidos.get(nome, nome)
        pecas.append(
            _estado_peca(conectado, rotulo, "conector", "" if conectado else "conectar_conector")
        )

    if fluxo.get("agendado"):
        # A automação é criada quando a pessoa ativa o fluxo — nunca antes. Um agendamento
        # que nasce ligado sozinho seria o app decidindo trabalhar sem ser convidado.
        pecas.append(_estado_peca(False, fluxo["agendado"], "automação", "criar_automacao"))

    exige_local = fluxo.get("modelo") == "local"
    modelo_ok = modelo_local_pronto if exige_local else modelo_pronto
    pecas.append(
        _estado_peca(
            modelo_ok,
            "Modelo local" if exige_local else "Modelo",
            "modelo",
            "" if modelo_ok else ("baixar_modelo_local" if exige_local else "configurar_modelo"),
        )
    )

    # Família de agente que o fluxo inicia. Um fluxo LOCAL (sem MCP e sem conector) roda na
    # família enxuta "negocio" (~20 ferramentas) em vez da Cowork padrão (~47) — no modelo
    # local em CPU isso corta o prefill da primeira mensagem em milhares de tokens, que é o
    # que a pessoa sente como "demora". Fluxo que usa conector/MCP precisa da máquina de
    # integração e continua em Cowork; não dá para servir os dois com a mesma família porque
    # `connectors=True` já arrasta os 11 tools de navegador + e-mail.
    #
    # Um fluxo AGENDADO também sai de "negocio": quem cria o agendamento é o próprio agente,
    # chamando `create_scheduled_task` na conversa em que a pessoa ativa o fluxo — e essa tool
    # só é concedida à família "knowledge" (Cowork), nunca a "business" (negocio). Rotear um
    # fluxo agendado para negocio deixaria a peça `criar_automacao` impossível de cumprir: o
    # agente veria a instrução de agendar e não teria a ferramenta. A regra de roteamento aqui
    # e o gating em agent.py precisam concordar; o teste de invariante prende isso.
    usa_externo = bool(fluxo.get("mcps") or fluxo.get("conectores"))
    precisa_agenda = bool(fluxo.get("agendado"))
    agente = "negocio" if not usa_externo and not precisa_agenda else "cowork"

    faltando = [p for p in pecas if not p["pronta"]]
    # A automação não conta como impedimento: o fluxo roda sob demanda enquanto ela não
    # existe. Dizer "falta 1" por causa dela assustaria sem motivo.
    bloqueios = [p for p in faltando if p["tipo"] != "automação"]

    return {
        **fluxo,
        "pecas": pecas,
        "pronto": not bloqueios,
        "faltam": len(bloqueios),
        "agente": agente,
    }


def resolver_problemas(problemas: list[dict[str, Any]], **ctx: Any) -> list[dict[str, Any]]:
    """Todos os problemas com seus fluxos resolvidos, ordenados: o que dá para usar primeiro."""
    saida: list[dict[str, Any]] = []
    for p in problemas:
        fluxos = [resolver_fluxo(f, **ctx) for f in p["fluxos"]]
        # Dentro do problema, o fluxo mais próximo de funcionar vem primeiro — quem abre o
        # cartão quer ver o caminho mais curto, não o mais completo.
        fluxos.sort(key=lambda f: (f["faltam"], len(f["pecas"])))
        saida.append({**p, "fluxos": fluxos, "tem_pronto": any(f["pronto"] for f in fluxos)})
    saida.sort(key=lambda p: (not p["tem_pronto"], p["titulo"]))
    return saida
