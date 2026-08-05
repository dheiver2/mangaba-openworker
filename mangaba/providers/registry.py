"""Model-provider registry — descriptors + a factory, mirroring the connector
(`connectors/descriptors.py`) and web-search (`web/providers.py`) patterns.

A `ProviderDescriptor` declares a provider's UI config `fields` (rendered dynamically by the
GUI, same `to_dict()` shape connectors use) and a `build(profile, secrets)` factory that returns
a `ProviderClient`. The `ProviderRouter` selects a descriptor by the `provider:` prefix of a
model string and builds (and caches) its client from the matching SecretStore profile.

Today: `openai` (the default, with an optional custom endpoint that covers Azure OpenAI's
`/openai/v1` and any OpenAI-compliant gateway), `anthropic` (native Messages API via
`AnthropicProvider`), `gemini` (native Google GenAI API via `GeminiProvider`), and `local`
(llama-server embutido, OpenAI-compatible — see `local_engine.py`). Bedrock/Vertex auth for
Claude is future work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .anthropic_provider import AnthropicProvider
from .base import ProviderClient
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider


@dataclass(frozen=True)
class ProviderField:
    """One config input for a provider, rendered by the GUI (mirrors connectors' `Field`)."""

    key: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    placeholder: str = ""
    # Pre-filled (still editable) form value — e.g. an OpenAI-compatible vendor's official
    # endpoint, so the user only has to paste a key. Distinct from `placeholder` (grey hint).
    default: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "secret": self.secret,
            "required": self.required,
            "help": self.help,
            "placeholder": self.placeholder,
            "default": self.default,
        }


@dataclass(frozen=True)
class ProviderDescriptor:
    """A model provider: its UI fields + a factory that builds its `ProviderClient`."""

    name: str
    title: str
    needs_key: bool
    fields: list[ProviderField]
    build: Callable[[dict[str, Any], Any], ProviderClient] = field(repr=False)
    recommended_model: Optional[str] = (
        None  # pre-filled in the UI; auto-added on configure
    )
    env_key: Optional[str] = (
        None  # env var that can supply the API key (e.g. ANTHROPIC_API_KEY)
    )
    # One-line note under the provider title (e.g. "Connects through X's OpenAI-compatible API").
    blurb: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "needs_key": self.needs_key,
            "fields": [f.to_dict() for f in self.fields],
            "recommended_model": self.recommended_model,
            "blurb": self.blurb,
        }


def _build_openai(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Key resolution stays in OpenAIProvider/resolve_api_key (explicit → env → SecretStore),
    # so we just hand it the SecretStore. An optional custom endpoint (Azure OpenAI /openai/v1,
    # OpenRouter, vLLM, …) comes from the stored profile.
    base_url = ((profile or {}).get("base_url") or "").strip() or None
    return OpenAIProvider(secrets=secrets, base_url=base_url)


def _build_anthropic(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Key resolution stays in AnthropicProvider/resolve_api_key (explicit → env → SecretStore),
    # deferred to first call so the provider can be built before a key exists.
    # thinking_budget: hidden profile override — absent/invalid → the default (ON),
    # explicit 0 → off (see DEFAULT_THINKING_BUDGET).
    from .anthropic_provider import DEFAULT_THINKING_BUDGET

    api_key = ((profile or {}).get("api_key") or "").strip() or None
    try:
        thinking_budget = int(str((profile or {}).get("thinking_budget") or "").strip())
    except ValueError:
        thinking_budget = DEFAULT_THINKING_BUDGET
    return AnthropicProvider(
        api_key=api_key, secrets=secrets, thinking_budget=thinking_budget
    )


def _build_gemini(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Same deferred-key contract as anthropic (GeminiProvider/resolve_api_key).
    api_key = ((profile or {}).get("api_key") or "").strip() or None
    return GeminiProvider(api_key=api_key, secrets=secrets)


def _build_local(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # O llama-server não pede chave, mas o SDK exige uma string não vazia — marcador.
    from .local_engine import DEFAULT_HOST

    return OpenAIProvider(api_key="local", base_url=DEFAULT_HOST + "/v1")




def _openai_compat(vendor: str, default_base_url: str, env_key: Optional[str] = None):
    """Builder factory for vendors reached through their OpenAI-compatible API (Z AI, DeepSeek,
    Kimi, MiniMax, Qwen, xAI, Mistral). The key is resolved from the vendor's OWN profile (or its
    env var) — deliberately NOT from the OpenAI env/SecretStore fallback, so a configured OpenAI
    key is never silently sent to a different vendor's endpoint. Missing key ⇒ fail fast with a
    vendor-named error (these are only built on demand, when one of their models is selected).
    """

    def build(profile: dict[str, Any], secrets: Any) -> ProviderClient:
        base_url = ((profile or {}).get("base_url") or "").strip() or default_base_url
        api_key = ((profile or {}).get("api_key") or "").strip() or (
            os.environ.get(env_key, "").strip() if env_key else ""
        )
        if not api_key:
            raise RuntimeError(
                f"No {vendor} API key configured — add it in Settings ▸ Models."
            )
        return OpenAIProvider(api_key=api_key, base_url=base_url)

    return build


def _compat(
    name: str,
    title: str,
    *,
    base_url: str,
    recommended_model: str,
    env_key: str,
    endpoint_help: str = "",
) -> ProviderDescriptor:
    """Descriptor for an OpenAI-compatible vendor: key + a prefilled, editable endpoint."""
    vendor = title.split(" (")[0]
    return ProviderDescriptor(
        name=name,
        title=title,
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                f"{vendor} API key",
                secret=True,
            ),
            ProviderField(
                "base_url",
                "Endpoint",
                required=False,
                default=base_url,
                placeholder=base_url,
                help=endpoint_help
                or f"Prefilled with {vendor}'s official endpoint; edit only for a regional or proxy variant.",
            ),
        ],
        build=_openai_compat(vendor, base_url, env_key),
        recommended_model=recommended_model,
        env_key=env_key,
        blurb=f"Uses {vendor}'s OpenAI-compatible API — the endpoint is prefilled, just add your key.",
    )


DESCRIPTORS: list[ProviderDescriptor] = [
    ProviderDescriptor(
        name="local",
        title="Mangaba Local",
        needs_key=False,
        blurb=(
            "IA neste computador, sem chave e sem nuvem — o app baixa o motor "
            "(llama.cpp, MIT) e um modelo Qwen3 (Apache-2.0) com tool calling nativo."
        ),
        fields=[],
        build=_build_local,
        recommended_model="qwen3-4b",
    ),
    ProviderDescriptor(
        name="openai",
        title="OpenAI",
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                "OpenAI API key",
                secret=True,
                placeholder="sk-…",
            ),
            ProviderField(
                "base_url",
                "Custom endpoint (optional)",
                secret=False,
                required=False,
                placeholder="https://…/openai/v1",
                help="For Azure OpenAI, OpenRouter, vLLM, or any OpenAI-compliant server. Leave blank for api.openai.com.",
            ),
        ],
        build=_build_openai,
        recommended_model="gpt-5.6-sol",
        env_key="OPENAI_API_KEY",
    ),
    ProviderDescriptor(
        name="anthropic",
        title="Claude (Anthropic)",
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                "Anthropic API key",
                secret=True,
                placeholder="sk-ant-…",
            ),
            # No thinking_budget field (owner call 2026-07-23): extended thinking is
            # on by default; the profile key stays a hidden override (0 = off).
        ],
        build=_build_anthropic,
        recommended_model="claude-fable-5",
        env_key="ANTHROPIC_API_KEY",
    ),
    ProviderDescriptor(
        name="gemini",
        title="Gemini (Google)",
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                "Gemini API key",
                secret=True,
                placeholder="AIza…",
            ),
        ],
        build=_build_gemini,
        recommended_model="gemini-3.6-flash",
        env_key="GEMINI_API_KEY",
    ),
    # OpenAI-compatible vendors, listed as first-class providers so users don't need to know the
    # "point the OpenAI slot at a different endpoint" trick (owner call, 2026-07-04). Each keeps
    # its own key profile; the endpoint is prefilled and editable (regional variants in `help`).
    _compat(
        "zai",
        "Z AI (GLM)",
        base_url="https://api.z.ai/api/paas/v4",
        recommended_model="glm-5.2",
        env_key="ZAI_API_KEY",
        endpoint_help="Prefilled with Z AI's international endpoint. China mainland: https://open.bigmodel.cn/api/paas/v4",
    ),
    _compat(
        "mangaba-nordeste",
        "Mangaba Nordeste (Mangaba AI)",
        base_url="https://mangaba-iprojectti.ngrok.app/v1",
        recommended_model="Mangaba-Nordeste-30B",
        env_key="MANGABA_NORDESTE_API_KEY",
        endpoint_help=(
            "Provedor agêntico da Mangaba AI servido no Brasil (Nossa Telecom/AL). "
            "Verificado agêntico pleno em 2026-08-05 (tools, streaming, parallel). "
            "Gere chaves-cliente no Swagger (/docs → /admin/keys)."
        ),
    ),
    _compat(
        "deepseek",
        "DeepSeek",
        base_url="https://api.deepseek.com",
        recommended_model="deepseek-v4-flash",
        env_key="DEEPSEEK_API_KEY",
    ),
    _compat(
        "kimi",
        "Kimi (Moonshot AI)",
        base_url="https://api.moonshot.ai/v1",
        recommended_model="kimi-k2.6",
        env_key="MOONSHOT_API_KEY",
        endpoint_help="Prefilled with Moonshot's international endpoint. China mainland: https://api.moonshot.cn/v1",
    ),
    _compat(
        "minimax",
        "MiniMax",
        base_url="https://api.minimax.io/v1",
        recommended_model="MiniMax-M2.5",
        env_key="MINIMAX_API_KEY",
    ),
    _compat(
        "qwen",
        "Qwen (Alibaba)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        recommended_model="qwen3-max",
        env_key="DASHSCOPE_API_KEY",
        endpoint_help="Prefilled with Alibaba Model Studio's international endpoint. China (Beijing): https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    _compat(
        "xai",
        "xAI (Grok)",
        base_url="https://api.x.ai/v1",
        recommended_model="grok-4.3",
        env_key="XAI_API_KEY",
    ),
    _compat(
        "mistral",
        "Mistral",
        base_url="https://api.mistral.ai/v1",
        recommended_model="mistral-large-latest",
        env_key="MISTRAL_API_KEY",
    ),
    _compat(
        "meta",
        "Meta (Muse Spark)",
        base_url="https://api.meta.ai/v1",
        recommended_model="muse-spark-1.1",
        env_key="META_API_KEY",
        endpoint_help="Prefilled with the Meta Model API endpoint (public preview, US-only as of 2026-07).",
    ),
    # Resellers: many labs' models behind one key, using THEIR model namespaces (the curated
    # ids + display labels live in providers/matrix.py). TODO: add Groq and OpenRouter here
    # (+ their matrix rows) once the current provider surface is tested — deliberately
    # deferred to bound how much needs verifying at once (owner call, 2026-07-04).
    _compat(
        "together",
        "Together AI",
        base_url="https://api.together.xyz/v1",
        recommended_model="zai-org/GLM-5.2",
        env_key="TOGETHER_API_KEY",
    ),
    _compat(
        "fireworks",
        "Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        recommended_model="accounts/fireworks/models/glm-5p2",
        env_key="FIREWORKS_API_KEY",
    ),
]

_BY_NAME = {d.name: d for d in DESCRIPTORS}


def provider_descriptors() -> list[ProviderDescriptor]:
    return list(DESCRIPTORS)


def provider_names() -> list[str]:
    return [d.name for d in DESCRIPTORS]


def get_descriptor(name: str) -> Optional[ProviderDescriptor]:
    return _BY_NAME.get(name)


def build_provider_client(
    name: str, profile: dict[str, Any], secrets: Any
) -> ProviderClient:
    """Build a `ProviderClient` for `name` from its stored profile. Unknown → OpenAI default."""
    descriptor = _BY_NAME.get(name) or _BY_NAME["openai"]
    return descriptor.build(profile or {}, secrets)


def detect_provider(api_key: str) -> Optional[str]:
    """Best-effort provider guess from an API key's shape, for the onboarding auto-detect.
    Returns a known provider name or None. Mirrors the GUI's client-side detection so both agree.
    """
    key = (api_key or "").strip()
    if not key:
        return None
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith(("sk-", "sk_")):
        return "openai"
    return None


def verify_provider_key(
    name: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Validate a provider's credentials with one cheap, read-only call (list models) — the same
    pattern connectors use to validate tokens. Transient: callers pass the key directly so a user
    can Test before saving. Never raises; returns {ok, error?}.
    """
    import httpx

    d = _BY_NAME.get(name) or _BY_NAME["openai"]
    key = (api_key or "").strip()
    if name == "local":
        # Sem chave: "verificar" é subir o motor (se der) e ver se ele responde.
        from .local_engine import engine_status

        st = engine_status()
        if not st["installed"]:
            return {"ok": False, "error": "O motor local ainda não foi instalado."}
        if not st["models"]:
            return {"ok": False, "error": "Nenhum modelo local baixado ainda."}
        if st["running"]:
            return {"ok": True}
        # Motor instalado com modelo, mas parado: dispara a subida em segundo plano e
        # devolve já. Esperar o load (dezenas de segundos, `ensure_running` síncrono)
        # aqui seguraria uma thread do pool do uvicorn — o motor sobe e o próximo
        # fetch de settings o vê pronto.
        import threading

        from .local_engine import ensure_running as _run

        threading.Thread(target=_run, daemon=True).start()
        return {
            "ok": True,
            "note": "O motor local está iniciando — o modelo ficará pronto em instantes.",
        }
    try:
        if name == "anthropic":
            resp = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=timeout,
            )
        elif name == "gemini":
            resp = httpx.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": key},
                timeout=timeout,
            )
        else:  # openai + any OpenAI-compatible endpoint (Azure, OpenRouter, vendors, vLLM…)
            default_base = next(
                (f.default for f in d.fields if f.key == "base_url" and f.default), ""
            )
            base = (
                (base_url or "").strip().rstrip("/")
                or default_base.rstrip("/")
                or "https://api.openai.com/v1"
            )
            resp = httpx.get(
                base + "/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=timeout,
            )
    except Exception as exc:  # DNS/connection/timeout — never let it bubble to a 500
        return {
            "ok": False,
            "error": f"Couldn't reach {d.title} ({exc.__class__.__name__}).",
        }

    if resp.status_code < 300:
        if name == "mangaba-nordeste":
            # Gateway próprio da organização: chave válida NÃO garante agente. O gateway
            # anterior deste projeto aceitava o parâmetro `tools` e nunca devolvia
            # `tool_calls` — e o modelo, em vez de falhar, INVENTAVA o resultado da
            # ferramenta. Testar aqui é o único momento em que a pessoa está olhando.
            aviso = _sonda_tool_calling(base_url or "", key, resp)
            if aviso:
                return {"ok": True, "aviso": aviso}
        return {"ok": True}
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "Invalid API key."}
    return {"ok": False, "error": f"{d.title} returned HTTP {resp.status_code}."}


def _sonda_tool_calling(base_url: str, key: str, resp_models: Any) -> Optional[str]:
    """Uma chamada barata que prova se o gateway executa ferramenta. Devolve o aviso a
    mostrar, ou None quando está tudo certo. Nunca levanta: é um extra da verificação."""
    import httpx

    try:
        modelos = [m["id"] for m in (resp_models.json().get("data") or []) if m.get("id")]
    except Exception:
        modelos = []
    if not modelos or not base_url:
        return None
    ferramenta = {
        "type": "function",
        "function": {
            "name": "obter_clima",
            "description": "Retorna o clima atual de uma cidade.",
            "parameters": {
                "type": "object",
                "properties": {"cidade": {"type": "string"}},
                "required": ["cidade"],
            },
        },
    }
    try:
        r = httpx.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={
                "model": modelos[0],
                "messages": [
                    {"role": "user", "content": "Qual o clima em Maceió? Use a ferramenta."}
                ],
                "tools": [ferramenta],
                "tool_choice": "auto",
            },
            timeout=45,
        )
        if r.status_code >= 300:
            return None  # sem conclusão: não vale assustar por um erro transitório
        msg = (r.json().get("choices") or [{}])[0].get("message", {}) or {}
        if msg.get("tool_calls"):
            return None
        return (
            "Chave válida, mas este gateway não devolveu uma chamada de ferramenta no "
            "teste. Modelos assim conversam, porém não leem arquivos, não rodam comandos "
            "e não usam conectores — e alguns chegam a inventar o resultado. Confirme com "
            "o administrador se o gateway suporta tool calling."
        )
    except Exception:
        return None
