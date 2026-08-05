"""New-flagship rollout (2026-07-14): GPT-5.6 Sol/Terra/Luna + Claude Fable 5 in the
matrix, both families' flagships as defaults, and friendly errors when an account can't
use them (GPT-5.6 rolls out per-organization; quota/credits can run out on any model).
"""

from mangaba.config import Config
from mangaba.providers.errors import friendly_model_error
from mangaba.providers.matrix import MATRIX, models_for_provider
from mangaba.providers.registry import get_descriptor


def test_new_flagships_in_matrix_with_labels():
    for mid, label in {
        "gpt-5.6-sol": "GPT-5.6 Sol · OpenAI",
        "gpt-5.6-terra": "GPT-5.6 Terra · OpenAI",
        "gpt-5.6-luna": "GPT-5.6 Luna · OpenAI",
        "anthropic:claude-fable-5": "Claude Fable 5 · Anthropic",
    }.items():
        assert MATRIX[mid].label == label
        assert MATRIX[mid].caps.tools and MATRIX[mid].caps.vision

    assert "gpt-5.6-sol" in models_for_provider("openai")
    assert "claude-fable-5" in models_for_provider("anthropic")


def test_flagships_are_the_defaults():
    # O carro-chefe de cada provedor é o que ele recomenda quando o usuário o configura.
    assert Config().model == "gpt-5.6-sol"
    assert get_descriptor("openai").recommended_model == "gpt-5.6-sol"
    assert get_descriptor("anthropic").recommended_model == "claude-fable-5"


# -- friendly access/quota errors --------------------------------------------------------
def test_no_access_errors_are_translated():
    # OpenAI's 404/403 body for a model the org can't use yet
    exc = RuntimeError(
        "Error code: 404 - {'error': {'code': 'model_not_found', 'message': "
        "'The model `gpt-5.6-sol` does not exist or you do not have access to it.'}}"
    )
    msg = friendly_model_error("gpt-5.6-sol", exc)
    assert msg and "doesn't have access to gpt-5.6-sol" in msg

    # Anthropic's 404 body is type not_found_error + "model: <id>"
    exc = RuntimeError(
        "Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', "
        "'message': 'model: claude-fable-5'}}"
    )
    msg = friendly_model_error("anthropic:claude-fable-5", exc)
    assert msg and "doesn't have access to anthropic:claude-fable-5" in msg


def test_quota_errors_are_translated():
    exc = RuntimeError(
        "Error code: 429 - {'error': {'code': 'insufficient_quota', 'message': "
        "'You exceeded your current quota, please check your plan and billing details.'}}"
    )
    msg = friendly_model_error("gpt-5.6-sol", exc)
    assert msg and "out of quota for gpt-5.6-sol" in msg

    exc = RuntimeError(
        "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
        "'message': 'Your credit balance is too low to access the Anthropic API.'}}"
    )
    msg = friendly_model_error("anthropic:claude-fable-5", exc)
    assert msg and "out of quota" in msg


def test_unrelated_errors_pass_through_raw():
    # a plain rate-limit (429 without a quota code) must NOT be dressed up
    assert (
        friendly_model_error(
            "gpt-5.6-sol",
            RuntimeError("Error code: 429 - rate_limit_exceeded, retry after 2s"),
        )
        is None
    )
    # a 404 from a wrong base_url isn't an access problem
    assert (
        friendly_model_error(
            "gpt-5.6-sol", RuntimeError("Error code: 404 - no route /v2/chat")
        )
        is None
    )
    assert (
        friendly_model_error("gpt-5.6-sol", RuntimeError("connection reset by peer"))
        is None
    )


def test_estouro_de_contexto_vira_mensagem_acionavel():
    """O corpo cru do llama.cpp é um JSON com n_ctx/n_prompt_tokens que não diz nada a
    quem só quer trabalhar. Caso real: um gateway anunciava context_window 32768 e
    servia n_ctx 8192 — o usuário via o JSON e não tinha o que fazer com ele."""
    from mangaba.providers.errors import friendly_model_error

    exc = Exception(
        "Error code: 400 - {'error': {'code': 400, 'message': 'request (12187 tokens) "
        "exceeds the available context size (8192 tokens), try increasing it', "
        "'type': 'exceed_context_size_error', 'n_prompt_tokens': 12187, 'n_ctx': 8192}}"
    )
    msg = friendly_model_error("mangaba-nordeste:Mangaba-Nordeste-30B", exc)
    assert msg is not None
    assert "12187" in msg and "8192" in msg
    # as três saídas que a pessoa tem, e a que o admin tem
    assert "sessão nova" in msg
    assert "conectores" in msg
    assert "--ctx-size" in msg


def test_janela_do_gateway_e_a_medida_nao_a_anunciada():
    """A janela declarada tem de ser SEMPRE a medida. Este número já valeu 8.192 —
    o gateway anunciava 32768 mas servia 8192, porque no llama-server o `-c` é dividido
    entre os slots de `--parallel`. Depois de o administrador corrigir (-c 131072 ÷ 4
    slots), a medição confirmou 32.768: prompt de 10k passa, que antes era recusado."""
    from mangaba.providers.matrix import model_context_windows

    assert model_context_windows()["mangaba-nordeste:Mangaba-Nordeste-30B"] == 32_768


def test_verificador_mede_a_janela_em_vez_de_confiar_no_anuncio():
    """A lição que custou uma release: eu declarei 32.768 confiando no /v1/models e o
    valor real era 8.192. O verificador de provedor passa a sondar a janela com prompts
    crescentes e avisa quando a medida diverge do anúncio."""
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[1] / "packaging" / "verificar_provedor.py"
    ).read_text(encoding="utf-8")
    assert "Janela de contexto (medida" in script
    assert "DIVERGE do anúncio" in script
    assert "--parallel" in script  # a pegadinha que causou o caso real


def test_429_de_ritmo_e_diferente_de_429_de_credito():
    """O gateway da organização passou a limitar por chave (30 req/min). O laço agêntico
    é rajado — com cache quente um hop leva ~1,7s, o que dá ~35 req/min de UM agente só,
    acima do teto. Sem tratar, a pessoa via o JSON cru; e 'sem crédito' é outro problema,
    com outra saída."""
    from mangaba.providers.errors import friendly_model_error

    ritmo = friendly_model_error(
        "mangaba-nordeste:X",
        Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit exceeded: 30 requests "
            "per minute', 'type': 'rate_limit_exceeded'}}"
        ),
    )
    assert ritmo and "rajada" in ritmo
    assert "rpm" in ritmo  # o que pedir ao administrador

    credito = friendly_model_error(
        "mangaba-nordeste:X",
        Exception("Error code: 429 - {'error': {'code': 'insufficient_quota'}}"),
    )
    assert credito and "quota" in credito.lower()
    assert credito != ritmo, "ritmo e crédito pedem ações diferentes"
