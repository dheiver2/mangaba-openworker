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
    # `>=` e não `==`: a listagem agora inclui os fluxos criados na máquina ("Meus fluxos").
    # Fixar a contagem quebraria na máquina de quem usa `criar_fluxo` — o teste é sobre os
    # de fábrica estarem lá e resolvidos, não sobre não existir mais nada.
    assert len(probs) >= len(PROBLEMAS)
    assert {p["id"] for p in PROBLEMAS} <= {p["id"] for p in probs}
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

    # Roda o MESMO validador que `criar_fluxo` usa em runtime, em vez de reimplementar a
    # regra aqui. Se as duas cópias existissem, elas divergiriam — e a que protege o usuário
    # é a de runtime, porque um fluxo gerado nunca passa por este teste.
    from mangaba.fluxos.validacao import Inventario, validar_fluxo

    inventario = Inventario(skills=skills_reais, mcps=mcps_reais, conectores=con_reais)
    for f in FLUXOS.values():
        erros = validar_fluxo(f, inventario)
        assert not erros, f"{f['id']}: {erros}"


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


# -- fluxo semeia um Plan de verdade (não só um parágrafo de prompt) -----------
def test_todo_fluxo_declara_passos_verificaveis():
    """Sem passos, o `entrega` do cartão é promessa que nada no runtime confere: a
    decomposição fica por conta da improvisação do modelo, e um trabalho que não cabe num
    turno não deixa rastro do que já foi feito."""
    for f in FLUXOS.values():
        assert len(f["passos"]) >= 3, f"{f['id']}: precisa de pelo menos 3 passos"
        for p in f["passos"]:
            assert p.strip() and p[0].isupper(), f"{f['id']}: passo malformado {p!r}"


def test_passos_viram_plano_encadeado():
    from mangaba.fluxos.plano import plano_do_fluxo

    plano = plano_do_fluxo(["ler", "calcular", "escrever"])
    assert [p["id"] for p in plano] == ["p1", "p2", "p3"]
    assert plano[0].get("depends_on") is None, "o primeiro passo não depende de nada"
    assert plano[2]["depends_on"] == ["p2"]
    assert all(p["status"] == "pending" for p in plano)
    assert plano_do_fluxo([]) == [] and plano_do_fluxo(["  "]) == []


def test_plano_semeado_e_aceito_pelo_Plan_de_verdade():
    """A trava que importa: o formato gerado tem de ser exatamente o que `plan_write` come.
    Um passo que o Plan descarta silenciosamente viraria plano vazio — e o done-gate,
    que é o ponto de tudo isto, nunca cobraria nada."""
    from mangaba.fluxos.plano import plano_do_fluxo
    from mangaba.plan import Plan

    plan = Plan()
    resumo = plan.replace(plano_do_fluxo(["ler", "calcular", "escrever"]))
    assert resumo["open"] == 3
    # p2 depende de p1: não pode entrar em andamento antes de p1 fechar.
    assert plan.set_status("p2", "in_progress")["ok"] is False
    plan.set_status("p1", "done")
    assert plan.set_status("p2", "in_progress")["ok"] is True


def test_prompt_do_fluxo_manda_gravar_o_plano():
    """O prompt resolvido é o que a GUI entrega à conversa — se a instrução não estiver
    nele, o plano nunca é gravado e nada disto acontece."""
    ctx = dict(CTX_TUDO_PRONTO)
    r = resolver_fluxo(fluxo_por_id("cobranca-planilha"), **ctx)
    assert "plan_write" in r["prompt"]
    assert "p1." in r["prompt"] and "p2." in r["prompt"]
    assert r["prompt"].startswith(fluxo_por_id("cobranca-planilha")["prompt"][:40])
    assert len(r["plano"]) == len(fluxo_por_id("cobranca-planilha")["passos"])


# -- roteamento derivado das capacidades (fonte única) -------------------------
def test_roteamento_sai_do_registro_de_capacidades():
    """A regra de família era reescrita em estado.py e em agent.py, e só se mantinha em dia
    por teste. Agora as duas leem `capacidades.py` — e um fluxo GERADO em runtime, que nunca
    passa pelo CI, é roteado pela mesma regra."""
    from mangaba.capacidades import familia_para, familia_tem

    assert familia_para([]) == "negocio", "sem exigência, a família mais enxuta"
    assert familia_para(["agendar"]) == "cowork"
    assert familia_para(["integracoes"]) == "cowork"
    assert familia_para(["verificar"]) == "negocio"
    assert familia_tem("business", "agendar") is False
    assert familia_tem("knowledge", "agendar") is True
    assert familia_tem("business", "capacidade-que-nao-existe") is False


def test_fluxo_pode_exigir_capacidade_explicita():
    """`exige` deixa um fluxo pedir uma capacidade que suas peças não implicam — o caminho
    que um fluxo gerado usa para declarar que precisa de agendamento sem ter conector."""
    from mangaba.fluxos.estado import resolver_fluxo as _rf

    base = dict(fluxo_por_id("cobranca-planilha"))
    assert _rf(base, **CTX_TUDO_PRONTO)["agente"] == "negocio"
    base["exige"] = ["agendar"]
    assert _rf(base, **CTX_TUDO_PRONTO)["agente"] == "cowork"


# -- criar_fluxo: o pedido virando procedimento guardado -----------------------
def _inventario():
    from mangaba.fluxos.validacao import Inventario

    return Inventario(
        skills={"limpeza-planilha", "email-profissional"},
        mcps={"granola"},
        conectores={"gmail"},
    )


def _ferramenta(tmp_path):
    from mangaba.fluxos.store import FluxoStore
    from mangaba.fluxos.tools import fluxo_tools

    store = FluxoStore(tmp_path / "fluxos.json")
    (tool,) = fluxo_tools(store, _inventario)
    return store, tool


def test_criar_fluxo_recusa_peca_que_nao_existe(tmp_path):
    """A regra que só existia no CI, agora em runtime. Gravar um fluxo com skill inexistente
    produziria um cartão em que a peça conta como faltando PARA SEMPRE — a pessoa fica
    travada nele sem entender por quê. Recusar e explicar deixa o modelo corrigir."""
    store, criar = _ferramenta(tmp_path)
    r = criar(
        titulo="Da planilha",
        resumo="limpa e devolve",
        entrega="planilha limpa mais relatório",
        prompt="Limpe a planilha anexada.",
        passos=["Ler a planilha", "Limpar com script", "Escrever o relatório"],
        skills=["skill-que-nao-existe"],
    )
    assert r["ok"] is False
    assert any("skill-que-nao-existe" in e for e in r["erros"])
    assert store.listar() == [], "nada pode ser gravado quando a validação falha"


def test_criar_fluxo_exige_passos_de_verdade(tmp_path):
    store, criar = _ferramenta(tmp_path)
    r = criar(
        titulo="Qualquer coisa",
        resumo="faz coisas",
        entrega="resultado",
        prompt="Faça.",
        passos=["Um passo só"],
    )
    assert r["ok"] is False and any("passos" in e for e in r["erros"])


def test_criar_fluxo_grava_e_aparece_resolvido_como_os_de_fabrica(tmp_path):
    """Um fluxo gravado é um fluxo: mesma resolução de prontidão, mesmo roteamento de
    família, mesmo plano semeado no prompt — não um cidadão de segunda classe."""
    store, criar = _ferramenta(tmp_path)
    r = criar(
        titulo="Da planilha, quando eu pedir",
        resumo="Limpa a planilha e diz o que mudou.",
        entrega="Planilha limpa mais um relatório do que mudou",
        prompt="Limpe a planilha que vou anexar e me diga o que foi alterado.",
        passos=["Ler a planilha anexada", "Limpar com script", "Escrever o relatório"],
        skills=["limpeza-planilha"],
    )
    assert r["ok"] is True and r["passos"] == 3
    (gravado,) = store.listar()

    resolvido = resolver_fluxo(gravado, **CTX_TUDO_PRONTO)
    assert resolvido["agente"] == "negocio", "local e sem agenda → família enxuta"
    assert "plan_write" in resolvido["prompt"]
    assert len(resolvido["plano"]) == 3
    assert any(p["tipo"] == "skill" for p in resolvido["pecas"])


def test_criar_fluxo_agendado_roteia_para_familia_que_sabe_agendar(tmp_path):
    store, criar = _ferramenta(tmp_path)
    r = criar(
        titulo="Toda segunda de manhã",
        resumo="Triagem semanal.",
        entrega="Lista priorizada em rascunho",
        prompt="Faça a triagem da semana.",
        passos=["Ler o que chegou", "Priorizar", "Escrever os rascunhos"],
        conectores=["gmail"],
        agendado="Segunda-feira, 9h",
    )
    assert r["ok"] is True
    (gravado,) = store.listar()
    assert resolver_fluxo(gravado, **CTX_TUDO_PRONTO)["agente"] == "cowork"


def test_ids_de_fluxo_gravado_nao_colidem(tmp_path):
    store, criar = _ferramenta(tmp_path)
    args = dict(
        titulo="Da planilha",
        resumo="x",
        entrega="y",
        prompt="z",
        passos=["Ler", "Limpar", "Escrever"],
    )
    a = criar(**args)
    b = criar(**args)
    assert a["ok"] and b["ok"] and a["id"] != b["id"]
    assert len(store.listar()) == 2


def test_fluxo_criado_aparece_na_tela_junto_dos_de_fabrica(tmp_path):
    """Ponta a ponta: gravado pelo agente → listado pelo manager → resolvido contra a
    máquina, no mesmo formato dos de fábrica. Se ficasse fora da listagem, `criar_fluxo`
    seria escrita em arquivo, não capacidade."""
    import tempfile

    from mangaba.fluxos.tools import fluxo_tools
    from mangaba.server.manager import SessionManager

    m = SessionManager(workspace=tempfile.mkdtemp(), data_dir=tmp_path / "data")
    antes = len(m.fluxos_por_problema())

    (criar,) = fluxo_tools(m.fluxo_store, m.inventario_de_fluxo)
    r = criar(
        titulo="Do jeito que eu faço aqui",
        resumo="Procedimento que já deu certo.",
        entrega="Arquivo com o resultado",
        prompt="Refaça o procedimento combinado.",
        passos=["Ler as entradas", "Processar com script", "Escrever o resultado"],
    )
    assert r["ok"] is True, r

    problemas = m.fluxos_por_problema()
    assert len(problemas) == antes + 1
    meus = next(p for p in problemas if p["id"] == "meus-fluxos")
    (f,) = meus["fluxos"]
    assert f["titulo"] == "Do jeito que eu faço aqui"
    assert "plan_write" in f["prompt"] and len(f["plano"]) == 3
    assert f["agente"] == "negocio" and "pronto" in f


def test_inventario_recusa_peca_inexistente_contra_a_maquina_real(tmp_path):
    """O inventário tem de vir da máquina, não de uma lista escrita à mão — senão a
    validação aprova nomes que não existem aqui."""
    import tempfile

    from mangaba.fluxos.validacao import validar_fluxo
    from mangaba.server.manager import SessionManager

    m = SessionManager(workspace=tempfile.mkdtemp(), data_dir=tmp_path / "data")
    inv = m.inventario_de_fluxo()
    proposta = {
        "titulo": "x", "entrega": "y", "prompt": "z",
        "passos": ["Um", "Dois"], "skills": ["nao-existe-mesmo"],
    }
    assert any("nao-existe-mesmo" in e for e in validar_fluxo(proposta, inv))
