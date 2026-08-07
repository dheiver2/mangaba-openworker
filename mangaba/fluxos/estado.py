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

from ..capacidades import familia_para
from .identidade import conector_equivalente, mcps_equivalentes
from .plano import plano_do_fluxo, prompt_com_plano


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

    # Família de agente que o fluxo inicia — DERIVADA do que o fluxo exige, não escrita à mão.
    #
    # A regra em si não mudou: um fluxo LOCAL (sem MCP e sem conector) roda na família enxuta
    # "negocio" (~20 ferramentas) em vez da Cowork padrão (~47), porque no modelo local em CPU
    # o prefill do esquema de ferramentas é o que a pessoa sente como "demora"; e um fluxo
    # AGENDADO precisa sair de "negocio", já que quem cria o agendamento é o próprio agente
    # chamando `create_scheduled_task` — tool que só a família "knowledge" recebe. Rotear um
    # fluxo agendado para negocio deixaria a peça `criar_automacao` impossível de cumprir.
    #
    # O que mudou é de ONDE a regra vem. Antes ela era reescrita aqui e em `agent.py`, e as
    # duas cópias só se mantinham em dia por um teste que comparava uma com a outra. Agora as
    # duas leem `capacidades.py`. Com fluxos gerados em runtime isso deixa de ser gosto: um
    # fluxo gerado não passa pelo CI antes de existir, então a regra tem de ser consultável
    # por código.
    exigidas = list(fluxo.get("exige") or ())
    if fluxo.get("mcps") or fluxo.get("conectores"):
        exigidas.append("integracoes")
    if fluxo.get("agendado"):
        exigidas.append("agendar")
    agente = familia_para(exigidas)

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
        # O prompt entregue à conversa já carrega a instrução de gravar o plano. Montado aqui
        # (e não na GUI) porque o contrato do card é `onIniciarFluxo(prompt, agente)`: a tela
        # manda o texto e não sabe o que é plano — nem precisa saber.
        "prompt": prompt_com_plano(fluxo.get("prompt", ""), fluxo.get("passos") or []),
        "plano": plano_do_fluxo(fluxo.get("passos") or []),
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
