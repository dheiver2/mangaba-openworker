"""Catálogo curado de servidores MCP — a galeria que faltava.

Até aqui, Configurações ▸ Servidores MCP nascia VAZIA e a única forma de adicionar um
servidor era digitar JSON à mão. Isso é tarefa de desenvolvedor, não de usuário: quem
instalou o app abria a aba, via "nenhum servidor" e não tinha o que fazer ali. Na máquina
de quem desenvolve o `mcp.json` já existia de antes, então o buraco passou despercebido —
quem sentiu foram os usuários.

**HTTP primeiro, de propósito.** Servidor remoto (`type: http`) não precisa de NADA
instalado: sem Node, sem uv, sem download. Servidor `stdio` roda por `npx`/`uvx`, que a
máquina de um desenvolvedor tem e a de um usuário comum — especialmente no Windows — não;
lá o erro que chega é "[WinError 2] O sistema não pode encontrar o arquivo especificado",
que não diz o que falta. Por isso o catálogo é dominado por HTTP, e os stdio vêm no fim,
marcados com o runtime que exigem.

Os servidores viram DADO, como os conectores (`connectors/descriptors.py`) e as
skills-padrão (`skills/defaults.py`): a UI lista, a pessoa clica em Instalar e o
`mcp.json` é escrito por baixo.
"""

from __future__ import annotations

from typing import Any, Optional

# Runtimes exigidos pelos servidores stdio, e onde obtê-los.
RUNTIMES: dict[str, dict[str, str]] = {
    "node": {
        "titulo": "Node.js",
        "url": "https://nodejs.org",
        "checar": "npx",
        "porque": "Servidores MCP distribuídos como pacote npm rodam com o npx.",
    },
    "uv": {
        "titulo": "uv",
        "url": "https://docs.astral.sh/uv/getting-started/installation/",
        "checar": "uvx",
        "porque": "Servidores MCP escritos em Python rodam com o uvx.",
    },
}


def _http(
    name: str,
    titulo: str,
    blurb: str,
    url: str,
    *,
    oauth: bool = False,
    aprova: bool = True,
    categoria: str = "Ferramentas",
) -> dict[str, Any]:
    cfg: dict[str, Any] = {"type": "http", "url": url, "enabled": True}
    if oauth:
        cfg["auth"] = "oauth"
    if not aprova:
        cfg["requires_approval"] = False
    return {
        "name": name,
        "titulo": titulo,
        "blurb": blurb,
        "categoria": categoria,
        "runtime": None,  # HTTP não precisa de nada instalado
        "oauth": oauth,
        "requires_approval": aprova,
        "config": cfg,
        "campos": [],
    }


CATALOG: list[dict[str, Any]] = [
    # -- HTTP sem login: instala e já usa (o melhor primeiro uso possível) -----------
    _http(
        "context7",
        "Context7",
        "Documentação atualizada de bibliotecas e frameworks, direto na conversa.",
        "https://mcp.context7.com/mcp",
        aprova=False,
        categoria="Documentação",
    ),
    _http(
        "deepwiki",
        "DeepWiki",
        "Explica repositórios do GitHub em profundidade, como uma wiki gerada.",
        "https://mcp.deepwiki.com/mcp",
        aprova=False,
        categoria="Documentação",
    ),
    _http(
        "microsoft_learn",
        "Microsoft Learn",
        "Documentação oficial da Microsoft e do Azure.",
        "https://learn.microsoft.com/api/mcp",
        aprova=False,
        categoria="Documentação",
    ),
    _http(
        "gitmcp",
        "GitMCP",
        "Lê a documentação de qualquer repositório público do GitHub.",
        "https://gitmcp.io/docs",
        aprova=False,
        categoria="Documentação",
    ),
    _http(
        "cloudflare_docs",
        "Cloudflare Docs",
        "Documentação da Cloudflare (Workers, DNS, R2 e afins).",
        "https://docs.mcp.cloudflare.com/mcp",
        aprova=False,
        categoria="Documentação",
    ),
    _http(
        "huggingface",
        "Hugging Face",
        "Busca modelos, datasets e Spaces no Hugging Face.",
        "https://huggingface.co/mcp",
        categoria="IA",
    ),
    # -- HTTP com login pela conta (OAuth no navegador) ------------------------------
    _http(
        "notion",
        "Notion",
        "Busca e edita páginas e bancos de dados do seu Notion.",
        "https://mcp.notion.com/mcp",
        oauth=True,
        categoria="Trabalho",
    ),
    _http(
        "linear",
        "Linear",
        "Issues, projetos e ciclos do Linear.",
        "https://mcp.linear.app/mcp",
        oauth=True,
        categoria="Trabalho",
    ),
    _http(
        "granola",
        "Granola",
        "Suas notas de reunião do Granola.",
        "https://mcp.granola.ai/mcp",
        oauth=True,
        categoria="Trabalho",
    ),
    _http(
        "sentry",
        "Sentry",
        "Erros e traces da sua aplicação no Sentry.",
        "https://mcp.sentry.dev/mcp",
        oauth=True,
        categoria="Desenvolvimento",
    ),
    _http(
        "vercel",
        "Vercel",
        "Projetos, deploys e logs da Vercel.",
        "https://mcp.vercel.com",
        oauth=True,
        categoria="Desenvolvimento",
    ),
    _http(
        "semgrep",
        "Semgrep",
        "Análise estática de segurança no seu código.",
        "https://mcp.semgrep.ai/mcp",
        oauth=True,
        categoria="Desenvolvimento",
    ),
    _http(
        "grafana",
        "Grafana",
        "Dashboards, métricas e alertas do Grafana.",
        "https://mcp.grafana.com/mcp",
        oauth=True,
        categoria="Desenvolvimento",
    ),
    _http(
        "stripe",
        "Stripe",
        "Pagamentos, clientes e assinaturas do Stripe.",
        "https://mcp.stripe.com",
        oauth=True,
        categoria="Negócios",
    ),
    # -- stdio: exigem runtime instalado, por isso vêm por último --------------------
    {
        "name": "filesystem",
        "titulo": "Arquivos",
        "blurb": "Ler e escrever arquivos numa pasta que você escolher.",
        "categoria": "Local",
        "runtime": "node",
        "oauth": False,
        "requires_approval": True,
        "config": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "{pasta}"],
            "enabled": True,
        },
        "campos": [
            {
                "key": "pasta",
                "label": "Pasta liberada",
                "help": "O servidor só enxerga esta pasta e o que houver dentro dela.",
                "placeholder": "/Users/voce/Documentos",
            }
        ],
    },
    {
        "name": "git",
        "titulo": "Git",
        "blurb": "Histórico, diffs e status de um repositório local.",
        "categoria": "Local",
        "runtime": "uv",
        "oauth": False,
        "requires_approval": True,
        "config": {
            "command": "uvx",
            "args": ["mcp-server-git", "--repository", "{repositorio}"],
            "enabled": True,
        },
        "campos": [
            {
                "key": "repositorio",
                "label": "Pasta do repositório",
                "help": "O caminho local do projeto versionado com Git.",
                "placeholder": "/Users/voce/projetos/meu-app",
            }
        ],
    },
]


def entry_for(name: str) -> Optional[dict[str, Any]]:
    return next((e for e in CATALOG if e["name"] == name), None)


def runtime_disponivel(runtime: Optional[str]) -> bool:
    """O runtime deste servidor existe na máquina? HTTP não precisa de nenhum."""
    import shutil

    if not runtime:
        return True
    info = RUNTIMES.get(runtime)
    if not info:
        return True  # runtime desconhecido: não bloqueia, deixa tentar
    cmd = info["checar"]
    if shutil.which(cmd):
        return True
    # No Windows o executável real costuma ser npx.cmd / uvx.exe.
    return any(shutil.which(f"{cmd}{s}") for s in (".cmd", ".bat", ".exe", ".ps1"))


def listar() -> list[dict[str, Any]]:
    """O catálogo como a UI o consome, já com a disponibilidade do runtime resolvida."""
    saida: list[dict[str, Any]] = []
    for e in CATALOG:
        rt = RUNTIMES.get(e["runtime"] or "", {})
        saida.append(
            {
                **{k: v for k, v in e.items() if k != "config"},
                "transport": "http" if e["runtime"] is None else "stdio",
                "runtime_pronto": runtime_disponivel(e["runtime"]),
                "runtime_titulo": rt.get("titulo", ""),
                "runtime_url": rt.get("url", ""),
                "runtime_porque": rt.get("porque", ""),
            }
        )
    return saida


def montar_config(name: str, valores: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Config final do servidor, com os `{campos}` substituídos pelo que a pessoa digitou."""
    entry = entry_for(name)
    if entry is None:
        raise ValueError(f"servidor desconhecido no catálogo: {name}")
    valores = valores or {}
    faltando = [
        c["label"] for c in entry["campos"] if not str(valores.get(c["key"], "")).strip()
    ]
    if faltando:
        raise ValueError("preencha: " + ", ".join(faltando))

    def _sub(texto: str) -> str:
        for chave, valor in valores.items():
            texto = texto.replace("{" + chave + "}", str(valor))
        return texto

    cfg = dict(entry["config"])
    if cfg.get("args"):
        cfg["args"] = [_sub(a) for a in cfg["args"]]
    return cfg
