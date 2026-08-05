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
