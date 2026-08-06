"""Fluxos agênticos por problema — o catálogo e o resolvedor de prontidão.

A tela inteira se apoia numa regra: "pronto" só quando VERIFICADO. Peça cadastrada não é
peça funcionando, e um fluxo que promete e não entrega custa mais caro que fluxo nenhum —
a pessoa perde a confiança na tela toda, não só naquele cartão.
"""

from __future__ import annotations

import tempfile

from mangaba.fluxos import FLUXOS, PROBLEMAS, fluxo_por_id, listar_problemas
from mangaba.fluxos.estado import resolver_fluxo, resolver_problemas

CTX_TUDO_PRONTO = dict(
    skills_instaladas={"cobranca-inadimplencia", "email-profissional", "limpeza-planilha"},
    skills_desativadas=set(),
    mcps_conectados={"hubspot_mcp"},
    mcps_conhecidos={"hubspot_mcp": "hubspot_mcp"},
    conectores_conectados={"gmail"},
    conectores_conhecidos={"gmail": "Gmail"},
    modelo_pronto=True,
    modelo_local_pronto=True,
)


def test_todo_problema_tem_dor_em_linguagem_de_negocio():
    """O cartão é lido por quem tem o problema, não por quem conhece o sistema. Se a dor
    citar mecanismo (skill, MCP, conector), a tradução que o produto devia fazer voltou
    para o colo do usuário."""
    tecnicos = ("skill", "mcp", "conector", "endpoint", "api", "token")
    for p in PROBLEMAS:
        assert p["dor"], f"{p['id']} sem dor descrita"
        assert len(p["dor"]) > 40, f"{p['id']}: a dor precisa ser concreta"
        assert not any(t in p["dor"].lower() for t in tecnicos), (
            f"{p['id']}: a dor fala de mecanismo em vez do problema"
        )


def test_todo_problema_tem_ao_menos_um_fluxo():
    for p in PROBLEMAS:
        assert p["fluxos"], f"{p['id']} sem fluxo"


def test_maioria_dos_problemas_tem_alternativas():
    """A razão de existir mais de um fluxo: quem tem CRM resolve diferente de quem só tem
    planilha, e quem trata dado sensível resolve diferente de quem não trata. Caminho único
    obrigaria todos à mesma pilha."""
    com_alternativa = [p for p in PROBLEMAS if len(p["fluxos"]) > 1]
    assert len(com_alternativa) >= len(PROBLEMAS) * 0.6


def test_fluxo_declara_o_que_entrega():
    """`entrega` é o que chega na mão da pessoa — não o que o sistema faz por dentro."""
    for f in FLUXOS.values():
        assert f["entrega"], f"{f['id']} não diz o que entrega"
        assert f["prompt"], f"{f['id']} sem prompt inicial"
        assert f["modelo"] in {"qualquer", "local", "forte"}


def test_ids_de_fluxo_sao_unicos():
    ids = [f["id"] for p in PROBLEMAS for f in p["fluxos"]]
    assert len(ids) == len(set(ids))


def test_fluxo_pronto_quando_todas_as_pecas_estao():
    fluxo = fluxo_por_id("cobranca-planilha")
    r = resolver_fluxo(fluxo, **CTX_TUDO_PRONTO)
    assert r["pronto"] is True and r["faltam"] == 0


def test_mcp_cadastrado_mas_nao_conectado_conta_como_faltando():
    """A lição que custou caro neste projeto: cadastro mente, verificação não. Um servidor
    com OAuth aparece na lista antes de existir token — chamá-lo de pronto faria o fluxo
    morrer no meio do trabalho."""
    # triagem-suporte usa Intercom, que só existe como MCP (sem conector nativo).
    ctx = {
        **CTX_TUDO_PRONTO,
        "mcps_conectados": set(),  # cadastrado, sem token
        "mcps_conhecidos": {"intercom_mcp": "Intercom"},
    }
    r = resolver_fluxo(fluxo_por_id("triagem-suporte"), **ctx)
    assert r["pronto"] is False
    mcp = next(p for p in r["pecas"] if p["tipo"] == "mcp")
    assert mcp["pronta"] is False and mcp["acao"] == "conectar_mcp"


def test_skill_desativada_conta_como_faltando():
    ctx = {**CTX_TUDO_PRONTO, "skills_desativadas": {"cobranca-inadimplencia"}}
    r = resolver_fluxo(fluxo_por_id("cobranca-planilha"), **ctx)
    assert r["pronto"] is False
    peca = next(p for p in r["pecas"] if p["rotulo"] == "cobranca-inadimplencia")
    assert peca["acao"] == "ativar_skill"


def test_fluxo_local_exige_modelo_local_e_nao_qualquer_um():
    """'Sem sair da máquina' é uma promessa de privacidade. Uma chave de nuvem configurada
    não a cumpre — se o GGUF não está no disco, o fluxo NÃO está pronto."""
    ctx = {**CTX_TUDO_PRONTO, "modelo_local_pronto": False, "modelo_pronto": True}
    r = resolver_fluxo(fluxo_por_id("fechamento-local"), **ctx)
    assert r["pronto"] is False
    modelo = next(p for p in r["pecas"] if p["tipo"] == "modelo")
    assert modelo["acao"] == "baixar_modelo_local"


def test_automacao_nao_impede_o_fluxo_de_rodar_sob_demanda():
    """O agendamento é criado quando a pessoa ativa o fluxo, nunca antes — um agendamento
    que nasce ligado seria o app trabalhando sem convite. E enquanto não existe, o fluxo
    roda sob demanda: contá-lo como impedimento assustaria sem motivo."""
    ctx = {**CTX_TUDO_PRONTO, "conectores_conectados": {"hubspot", "gmail"}}
    r = resolver_fluxo(fluxo_por_id("cobranca-crm-semanal"), **ctx)
    agenda = next(p for p in r["pecas"] if p["tipo"] == "automação")
    assert agenda["pronta"] is False and agenda["acao"] == "criar_automacao"
    assert r["pronto"] is True, "automação pendente não pode bloquear o uso sob demanda"


def test_ordem_poe_o_caminho_mais_curto_na_frente():
    """Quem abre o cartão quer o caminho mais curto para resolver, não o mais completo."""
    ctx = {**CTX_TUDO_PRONTO, "mcps_conectados": set(), "conectores_conectados": set()}
    probs = resolver_problemas(listar_problemas(), **ctx)
    cobrar = next(p for p in probs if p["id"] == "cobrar-atrasados")
    assert cobrar["fluxos"][0]["faltam"] <= cobrar["fluxos"][-1]["faltam"]
    # e problemas com algum caminho pronto vêm antes dos que não têm nenhum
    prontos = [i for i, p in enumerate(probs) if p["tem_pronto"]]
    travados = [i for i, p in enumerate(probs) if not p["tem_pronto"]]
    if prontos and travados:
        assert max(prontos) < min(travados)


def test_manager_resolve_contra_a_maquina_de_verdade():
    from mangaba.server.manager import SessionManager

    m = SessionManager(workspace=tempfile.mkdtemp())
    probs = m.fluxos_por_problema()
    assert len(probs) == len(PROBLEMAS)
    for p in probs:
        for f in p["fluxos"]:
            assert "pecas" in f and "pronto" in f
            assert any(x["tipo"] == "modelo" for x in f["pecas"]), (
                "todo fluxo depende de um modelo — a peça tem de aparecer"
            )


def test_toda_peca_referenciada_existe_de_verdade():
    """A auditoria que pega o erro mais provável: eu escrevi os fluxos de memória e
    declarei skills, MCPs e conectores por nome. Um nome errado produz um fluxo que
    NUNCA fica pronto — a peça inexistente conta como faltando para sempre, e a pessoa
    fica travada num cartão que não tem como completar. Esta trava roda contra as fontes
    reais, então um typo quebra o CI em vez de chegar ao usuário."""
    import glob
    import os
    import tempfile

    from mangaba.mcp import catalog as mcp_cat
    from mangaba.server.manager import SessionManager

    skills_reais = {
        os.path.basename(d)
        for d in glob.glob(os.path.expanduser("~/.config/mangaba/skills/*"))
        if os.path.isdir(d)
    }
    # Fallback: se a máquina de CI não tiver skills semeadas, usa as skills-padrão do código.
    if not skills_reais:
        from mangaba.skills.defaults import DEFAULTS

        skills_reais = {d["name"] for d in DEFAULTS}

    mcps_reais = {i["name"] for i in mcp_cat.listar()}
    m = SessionManager(workspace=tempfile.mkdtemp())
    con_reais = {c["name"] for c in m.list_connectors()}

    for f in FLUXOS.values():
        for s in f["skills"]:
            assert s in skills_reais, f"{f['id']}: skill inexistente {s!r}"
        for x in f["mcps"]:
            assert x in mcps_reais, f"{f['id']}: mcp inexistente {x!r}"
        for c in f["conectores"]:
            assert c in con_reais, f"{f['id']}: conector inexistente {c!r}"


def test_fluxo_local_inicia_na_familia_enxuta():
    """A causa da lentidão sentida no modelo local é o prefill do esquema de ferramentas: a
    família Cowork padrão manda ~47 ferramentas, e cada uma custa tokens antes da primeira
    palavra sair. Um fluxo que só lê arquivo e escreve entregável não usa navegador, e-mail,
    agendamento nem mensageria — então roda na família 'negocio' (~20 ferramentas). Já um
    fluxo com conector/MCP precisa da máquina de integração e fica em 'cowork'. Esta regra é
    o que transforma a economia em algo real; se ela inverter, a lentidão volta."""
    for f in FLUXOS.values():
        r = resolver_fluxo(f, **CTX_TUDO_PRONTO)
        # Local E sem agendamento → família enxuta. Peça externa OU agendamento (que precisa de
        # create_scheduled_task, exclusivo de Cowork) → Cowork.
        enxuto = not (f["mcps"] or f["conectores"] or f["agendado"])
        esperado = "negocio" if enxuto else "cowork"
        assert r["agente"] == esperado, (
            f"{f['id']}: esperava iniciar em {esperado!r}, veio {r['agente']!r}"
        )


def test_fluxo_agendado_nunca_roteia_para_negocio():
    """Armadilha que já mordeu: 'posts-da-semana' é local E agendado, e roteava para 'negocio'
    — família enxuta que NÃO tem create_scheduled_task. Quem cria o agendamento é o agente na
    conversa de ativação, então um fluxo agendado numa família sem a ferramenta deixa a peça
    'criar_automacao' impossível de cumprir. Todo fluxo com `agendado` precisa nascer numa
    família que saiba se agendar."""
    for f in FLUXOS.values():
        r = resolver_fluxo(f, **CTX_TUDO_PRONTO)
        if f["agendado"]:
            assert r["agente"] != "negocio", (
                f"{f['id']}: fluxo agendado roteado para 'negocio', que não tem "
                "create_scheduled_task — a automação nunca seria criada"
            )


def test_familia_de_cada_fluxo_tem_as_ferramentas_que_o_fluxo_exige():
    """A trava de verdade: em vez de reafirmar a regra de roteamento, confere contra a MÁQUINA.
    Constrói o engine da família que cada fluxo aponta e exige que a capacidade necessária
    esteja lá — agendamento para fluxos agendados. Se alguém mexer no gating de agent.py ou no
    roteamento de estado.py e os dois divergirem, isto quebra o CI em vez de chegar ao usuário
    como uma automação que 'roda' mas nunca se agenda."""
    import tempfile

    from mangaba.server.manager import SessionManager

    m = SessionManager(workspace=tempfile.mkdtemp())
    # Cache de nomes de ferramentas por família — construir engine é caro, uma vez por família.
    tools_por_agente: dict[str, set[str]] = {}

    def tools_de(agente: str) -> set[str]:
        if agente not in tools_por_agente:
            eng = m.get_engine(f"__inv__{agente}", agent=agente)
            tools_por_agente[agente] = {
                s["function"]["name"] for s in eng.registry.schemas()
            }
        return tools_por_agente[agente]

    for f in FLUXOS.values():
        r = resolver_fluxo(f, **CTX_TUDO_PRONTO)
        if f["agendado"]:
            assert "create_scheduled_task" in tools_de(r["agente"]), (
                f"{f['id']}: fluxo agendado nasce em {r['agente']!r}, que não expõe "
                "create_scheduled_task — não teria como se agendar"
            )


def test_familia_negocio_existe_e_e_mais_enxuta_que_cowork():
    """A família que os fluxos locais apontam precisa existir de verdade e ser realmente
    menor — senão o ponteiro 'negocio' cairia no default e não economizaria nada."""
    from mangaba.personas.registry import PersonaRegistry

    reg = PersonaRegistry()
    neg = reg.get("negocio")
    assert neg is not None, "família 'negocio' não registrada"
    assert neg.family == "business"
    assert neg.default_surfaced is False, (
        "'negocio' é destino de fluxo, não persona de escolher à mão — fora do picker"
    )


def test_mapa_de_identidade_so_referencia_servicos_reais():
    """O mapa conector⇄MCP é curado à mão — um rename em qualquer catálogo o deixaria apontando
    para um serviço que não existe, e o cruzamento silenciosamente pararia de creditar. Esta
    trava roda contra as fontes reais: se um nome sumir, quebra o CI, não a experiência."""
    import tempfile

    from mangaba.fluxos.identidade import SERVICOS_DUPLOS
    from mangaba.mcp import catalog as mcp_cat
    from mangaba.server.manager import SessionManager

    con_reais = {c["name"] for c in SessionManager(workspace=tempfile.mkdtemp()).list_connectors()}
    mcps_reais = {i["name"] for i in mcp_cat.listar()}
    for servico, (conector, mcps) in SERVICOS_DUPLOS.items():
        assert conector in con_reais, f"{servico}: conector {conector!r} não existe mais"
        for mcp in mcps:
            assert mcp in mcps_reais, f"{servico}: mcp {mcp!r} não existe mais"


def test_github_nao_e_confundido_com_o_mcp_git_generico():
    """A armadilha de uma heurística de prefixo: 'github'/'gitlab' NÃO são o MCP 'git' (que é
    git genérico, não a API do GitHub). O mapa curado tem de deixá-los de fora — creditá-los
    marcaria um fluxo do GitHub como pronto com a coisa errada conectada."""
    from mangaba.fluxos.identidade import conector_equivalente, mcps_equivalentes

    assert mcps_equivalentes("github") == frozenset()
    assert mcps_equivalentes("gitlab") == frozenset()
    assert conector_equivalente("git") is None


def test_mcp_equivalente_conectado_satisfaz_peca_de_conector():
    """O coração do I2: um fluxo pede o conector nativo, mas a pessoa já tem o MCP do mesmo
    serviço conectado. Não pode pedir a mesma conta de novo."""
    fluxo = {"conectores": ["linear"], "mcps": [], "skills": [], "agendado": None, "modelo": "qualquer"}
    ctx = {
        **CTX_TUDO_PRONTO,
        "conectores_conectados": set(),  # o conector nativo NÃO está ligado…
        "mcps_conectados": {"linear"},  # …mas o MCP equivalente está.
        "mcps_conhecidos": {"linear": "Linear"},
    }
    r = resolver_fluxo(fluxo, **ctx)
    con = next(p for p in r["pecas"] if p["tipo"] == "conector")
    assert con["pronta"] is True and r["pronto"] is True


def test_conector_equivalente_conectado_satisfaz_peca_de_mcp():
    """Simétrico: fluxo pede o MCP, mas a pessoa tem o conector nativo do mesmo serviço."""
    fluxo = {"conectores": [], "mcps": ["hubspot_mcp"], "skills": [], "agendado": None, "modelo": "qualquer"}
    ctx = {
        **CTX_TUDO_PRONTO,
        "mcps_conectados": set(),  # o MCP NÃO está ligado…
        "conectores_conectados": {"hubspot"},  # …mas o conector nativo está.
        "mcps_conhecidos": {"hubspot_mcp": "HubSpot"},
    }
    r = resolver_fluxo(fluxo, **ctx)
    mcp = next(p for p in r["pecas"] if p["tipo"] == "mcp")
    assert mcp["pronta"] is True and r["pronto"] is True


def test_servico_sem_equivalente_nao_ganha_credito_cruzado():
    """Garantia de que o crédito cruzado é ESTRITO: Intercom só existe como MCP. Ter um
    conector qualquer conectado não pode marcar a peça de Intercom como pronta."""
    fluxo = {"conectores": [], "mcps": ["intercom_mcp"], "skills": [], "agendado": None, "modelo": "qualquer"}
    ctx = {
        **CTX_TUDO_PRONTO,
        "mcps_conectados": set(),
        "conectores_conectados": {"gmail", "slack", "hubspot"},
        "mcps_conhecidos": {"intercom_mcp": "Intercom"},
    }
    r = resolver_fluxo(fluxo, **ctx)
    mcp = next(p for p in r["pecas"] if p["tipo"] == "mcp")
    assert mcp["pronta"] is False


def test_prefere_conector_nativo_quando_existe():
    """Regra de escolha da auditoria: quando um serviço tem conector NATIVO (OAuth
    gerenciado, mais fácil), o fluxo usa o conector — não o MCP do mesmo serviço, que
    pede login manual. MCP só quando é o ÚNICO caminho (Granola, Intercom não têm
    conector nativo)."""
    # HubSpot, Linear e monday têm conector nativo: nenhum fluxo deve citá-los como MCP.
    tem_conector = {"hubspot_mcp", "linear", "monday_mcp", "asana_mcp", "clickup_mcp"}
    for f in FLUXOS.values():
        vazou = tem_conector & set(f["mcps"])
        assert not vazou, (
            f"{f['id']}: usa MCP {vazou} de serviço que tem conector nativo — "
            "prefira o conector"
        )
