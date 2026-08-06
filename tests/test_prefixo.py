"""Teto do PREFIXO de cada família de agente — o custo fixo pago em todo turno.

Por que isto é um teste e não um relatório: o prefixo (system + esquema das ferramentas) é
reenviado a cada hop do laço agêntico, e ele cresce sozinho. Toda ferramenta nova o empurra
para cima, ninguém sente na hora, e um dia a primeira resposta ficou lenta sem que nada
"tenha mudado". Já aconteceu neste projeto: a v0.1.33 criou a família `negocio` justamente
para fugir das ~47 ferramentas do cowork, e em 2026-08-06 o cowork estava em 61.

Os números que sustentam os tetos, medidos em 2026-08-06:

- motor local (qwen3-4b): prefill FRIO de 3.675 tokens levou 18,9 s — ~5 ms por token. Cada
  1.000 tokens de prefixo custam ~5 s na primeira resposta de uma sessão (com o cache quente
  a mesma chamada cai para 1,3 s).
- gateway Mangaba: prompt curto responde em 0,55 s de forma estável, mas a partir de alguns
  milhares de tokens a cadeia de fallback desvia para modelos 5× mais lentos — 2 s a 4,8 s.
  Ou seja, o prefixo sozinho já tira toda sessão agêntica da faixa rápida.

Os tetos abaixo são o valor MEDIDO na data, arredondado para cima com folga. Se um deles
estourar, a pergunta não é "aumenta o teto?" — é "esta ferramenta nova precisa mesmo estar no
prefixo de todo turno, ou pode ser carregada sob demanda?".
"""

from __future__ import annotations

import json
import tempfile

import pytest

from mangaba.server.manager import SessionManager

# família → teto de tokens do prefixo (system + schemas)
TETOS = {
    "chat": 3_200,
    "negocio": 5_400,
    "code": 6_300,
    # Apertado de 8.200 para 7.400 em 2026-08-06, quando as 10 ferramentas de automação de
    # navegador saíram do prefixo de quem não tem Playwright (−671 tokens). Tetos que ficam
    # frouxos depois de uma economia deixam a gordura voltar sem ninguém notar.
    "cowork": 7_400,
}


def _medir(agente: str) -> tuple[int, int, int]:
    m = SessionManager(workspace=tempfile.mkdtemp())
    eng = m.get_engine(f"__prefixo__{agente}", agent=agente)
    schemas = eng.registry.schemas()
    tok_schemas = len(json.dumps(schemas, ensure_ascii=False)) // 4
    system = eng._outbound_messages()[0].get("content") or ""
    tok_system = len(system) // 4
    return len(schemas), tok_schemas, tok_system


@pytest.mark.parametrize("agente,teto", sorted(TETOS.items()))
def test_prefixo_da_familia_cabe_no_teto(agente: str, teto: int):
    n, tok_schemas, tok_system = _medir(agente)
    total = tok_schemas + tok_system
    assert total <= teto, (
        f"o prefixo de `{agente}` subiu para ~{total} tokens ({n} ferramentas: "
        f"{tok_schemas} de schema + {tok_system} de system), acima do teto de {teto}.\n"
        f"Isso é pago em TODO turno, e no motor local custa ~5 ms por token de prefill frio "
        f"(~{total * 5 / 1000:.1f} s na primeira resposta).\n"
        f"Antes de subir o teto: a ferramenta nova precisa estar no prefixo de todo turno, "
        f"ou pode ser carregada sob demanda?"
    )


def test_schemas_nao_carregam_campos_vazios():
    """O gerador da aisuite emite `description: ""` para todo parâmetro sem docstring e
    `default: null` para todo opcional. São ~263 tokens só no cowork — lixo que o modelo lê
    em todo turno, sem carregar informação nenhuma."""
    m = SessionManager(workspace=tempfile.mkdtemp())
    bruto = json.dumps(
        m.get_engine("__prefixo__vazios", agent="cowork").registry.schemas(),
        ensure_ascii=False,
    )
    assert '"description": ""' not in bruto
    assert '"default": null' not in bruto


def test_chat_e_o_mais_enxuto_e_cowork_o_mais_gordo():
    """A ordem entre as famílias é intencional: `chat` não tem área de trabalho e não deve
    pagar por ferramenta de entrega; `negocio` existe porque o cowork ficou grande demais
    para fluxo de negócio. Se essa ordem inverter, a separação perdeu o sentido."""
    tamanhos = {ag: sum(_medir(ag)[1:]) for ag in TETOS}
    assert tamanhos["chat"] < tamanhos["negocio"] < tamanhos["cowork"]
    assert tamanhos["negocio"] < tamanhos["code"], (
        "`negocio` foi criada para ser mais enxuta que a família de código"
    )


def test_motor_local_passa_valor_para_o_flash_attention():
    """O `-fa` do llama-server EXIGE valor (`on|off|auto`) nas versões atuais.

    Um `-fa` solto engole o argumento seguinte como se fosse o valor, e o motor morre no
    boot com `unknown value for --flash-attn: '-b'`. O efeito é brutal e mudo: o provedor
    Mangaba Local — o único que roda sem internet — simplesmente nunca sobe, e nada na tela
    diz por quê. Foi enviado assim da v0.1.34 à v0.1.37.

    O teste lê a linha de comando montada, e não o processo: subir o motor de verdade num
    teste custaria dezenas de segundos e dependeria da máquina ter modelo baixado."""
    import inspect

    from mangaba.providers import local_engine

    fonte = inspect.getsource(local_engine)
    assert '"-fa",' in fonte, "a flag saiu — se foi de propósito, apague este teste"
    assert '"-fa", "on"' in fonte or '"-fa", "auto"' in fonte or '"-fa", "off"' in fonte, (
        "`-fa` sem valor engole o próximo argumento e o motor local não sobe"
    )


def test_provedor_local_carrega_o_modelo_que_foi_pedido(monkeypatch):
    """O seletor de modelo local era decorativo — e o padrão silencioso era o pior caso.

    O llama.cpp serve UM modelo por processo. Nada ligava o nome escolhido ao motor:
    `ensure_running()` sem tag cai em `tags[-1]`, o ÚLTIMO modelo baixado. Numa máquina com
    `qwen3-4b` e `qwen3-14b` no disco, escolher "qwen3-4b" na interface e receber respostas
    do 14B era o comportamento normal.

    O custo disso foi MEDIDO em 2026-08-06, no mesmo prompt de ~9.400 tokens:
    27–29 ms/token no 14B (9,3 GB numa máquina de 16 GB) contra 8,56 ms/token no 4B —
    3,2× mais lento, silenciosamente, por um padrão que ninguém escolheu."""
    from mangaba.providers import local_engine
    from mangaba.providers.registry import build_provider_client

    pedidos: list[str] = []
    monkeypatch.setattr(local_engine, "active_tag", lambda: "qwen3-14b")
    monkeypatch.setattr(local_engine, "downloaded_tags", lambda: ["qwen3-4b", "qwen3-14b"])
    monkeypatch.setattr(
        local_engine, "ensure_running", lambda tag=None, **k: pedidos.append(tag) or True
    )

    cliente = build_provider_client("local", {}, None)
    cliente._garantir_modelo("qwen3-4b")
    assert pedidos == ["qwen3-4b"], "o modelo pedido tem de chegar ao motor"

    # Trocar de modelo reinicia o servidor (~15 s de load): só quando de fato muda.
    pedidos.clear()
    cliente._garantir_modelo("qwen3-14b")
    assert pedidos == [], "não reiniciar o motor quando o modelo pedido já é o ativo"

    # Um modelo que não está no disco não pode derrubar o turno nem reiniciar o motor.
    cliente._garantir_modelo("modelo-inexistente")
    assert pedidos == []


def test_motor_local_sobe_com_um_slot():
    """O llama-server sobe 4 slots por padrão, e CADA um reserva a janela inteira: eram
    65.536 tokens de cache KV reservados para usar 16.384, numa máquina de 16 GB. A pressão
    de memória aparecia como variância de 2× no mesmo prefill (110,8 s e 214,5 s para os
    mesmos ~7.000 tokens, medido em 2026-08-06). O app é de sessão única."""
    import inspect

    from mangaba.providers import local_engine

    assert '"--parallel", "1"' in inspect.getsource(local_engine)


def test_ferramentas_de_navegador_so_existem_com_playwright():
    """A automação de navegador é movida a Playwright — um EXTRA (`mangaba[browser]`) que
    NÃO vai no app empacotado. Sem ele as 10 ferramentas não têm como funcionar: cada
    chamada devolve "instale o playwright". Mesmo assim os schemas delas ficavam no prefixo
    de TODO turno, ~671 tokens medidos no cowork — cerca de 5 s de prefill local por sessão,
    gastos com ferramentas mortas.

    `browser_read_url` fica FORA do gate de propósito: busca texto por HTTP e funciona sem
    Playwright nenhum."""
    from mangaba.connectors.integration_tools import (
        _playwright_instalado,
        make_integration_tools,
    )
    from mangaba.secrets import SecretStore

    nomes = {
        t.__name__
        for t in make_integration_tools(SecretStore(), enabled_connectors={"browser"})
    }
    automacao = {
        "browser_open_url",
        "browser_click",
        "browser_type",
        "browser_screenshot",
        "browser_close",
    }
    if _playwright_instalado():
        assert automacao <= nomes, "com Playwright, as ferramentas de automação existem"
    else:
        assert not (automacao & nomes), (
            "sem Playwright elas não podem funcionar — não podem custar tokens do prefixo"
        )
        assert "browser_read_url" in nomes, "ler URL por HTTP não depende de Playwright"


def test_compactacao_conhece_a_janela_real_do_motor_local():
    """Sem isto, uma sessão local estourava a janela SEIS VEZES antes de compactar.

    O catálogo de modelos não tem entradas `local:*` — os tags dependem do que a pessoa
    baixou —, então `context_window` vinha None e o cálculo caía no padrão de 128.000: a
    compactação só dispararia em 102.400 tokens, contra os 16.384 que o llama-server serve.
    O sintoma para o usuário não é lentidão, é a tarefa morrendo no meio com "exceeds
    context size".

    A direção do erro importa: declarar janela MENOR que a servida custa um resumo a mais;
    declarar MAIOR mata a tarefa."""
    import tempfile

    from mangaba import compaction
    from mangaba.providers.local_engine import CTX_SIZE
    from mangaba.server.manager import SessionManager

    m = SessionManager(workspace=tempfile.mkdtemp())
    m.model = "local:qwen3-4b"
    eng = m.get_engine("__janela__", agent="negocio")
    cfg = eng._compaction_config()

    assert cfg["context_window"] == CTX_SIZE
    gatilho = compaction.trigger_tokens(
        cfg["context_window"],
        threshold_pct=float(cfg["threshold_pct"]),
        cap_tokens=int(cfg["cap_tokens"]),
    )
    assert gatilho < CTX_SIZE, "compactar DEPOIS de estourar a janela não serve para nada"


def test_a_janela_declarada_e_a_que_o_motor_sobe():
    """`CTX_SIZE` alimenta o argumento `--ctx-size` E o cálculo da compactação. Se alguém
    mudar o argumento sem mudar a constante, os dois divergem em silêncio — e a divergência
    só aparece como tarefa morrendo no meio, muito longe da causa."""
    import inspect

    from mangaba.providers import local_engine

    fonte = inspect.getsource(local_engine)
    assert '"--ctx-size", str(CTX_SIZE)' in fonte


def test_motor_local_nao_gasta_geracao_com_deliberacao():
    """O `--jinja` liga o modo de pensamento do Qwen3, e no laço agêntico ele é puro custo.

    MEDIDO em 2026-08-06, o MESMO turno de escolha de ferramenta:
      com pensamento:  122 tokens gerados, 435 chars de deliberação, 3,1 s
      sem pensamento:   25 tokens gerados,   0 chars,               0,6 s   (5,2× mais rápido)

    A geração é o gargalo do motor local (~30 tok/s), e ~78% do que ele gerava por hop era
    deliberação — paga a cada passo do laço. O ajuste vai por `extra_body` porque
    `chat_template_kwargs` não é campo do SDK da OpenAI: é extensão do llama-server."""
    from mangaba.providers.registry import build_provider_client

    cliente = build_provider_client("local", {}, None)
    ajustado = cliente._sem_pensamento({"temperature": 0})
    assert ajustado["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert ajustado["temperature"] == 0, "não pode atropelar os outros ajustes"

    # Um caller que peça pensamento de propósito (síntese final) continua no comando.
    explicito = cliente._sem_pensamento(
        {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}}
    )
    assert explicito["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
