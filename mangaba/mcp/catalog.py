"""Catálogo curado de servidores MCP — a galeria que faltava.

Até aqui, Configurações ▸ Servidores MCP nascia VAZIA e a única forma de adicionar um
servidor era digitar JSON à mão (`{"command": "npx", "args": [...]}`). Isso é tarefa de
desenvolvedor, não de usuário: quem instalou o app abria a aba, via "nenhum servidor" e
não tinha o que fazer ali. Na máquina de quem desenvolve o `mcp.json` já existia de
antes, então o buraco passou despercebido — quem sentiu foram os usuários.

Aqui os servidores viram DADO, como os conectores (`connectors/descriptors.py`) e as
skills-padrão (`skills/defaults.py`): a UI lista, a pessoa clica em Instalar e o
`mcp.json` é escrito por baixo.

`runtime` é o que o servidor precisa ter na máquina. Declarar isso permite avisar ANTES
de instalar — no Windows, sem Node, o erro que chegava era "[WinError 2] O sistema não
pode encontrar o arquivo especificado", que não diz o que falta.
"""

from __future__ import annotations

from typing import Any, Optional

# Runtimes e onde obtê-los. Node cobre a maior parte do ecossistema MCP publicado.
RUNTIMES: dict[str, dict[str, str]] = {
    "node": {
        "titulo": "Node.js",
        "url": "https://nodejs.org",
        "checar": "npx",
        "porque": "A maioria dos servidores MCP é distribuída como pacote npm.",
    },
    "uv": {
        "titulo": "uv",
        "url": "https://docs.astral.sh/uv/getting-started/installation/",
        "checar": "uvx",
        "porque": "Servidores MCP escritos em Python rodam com o uvx.",
    },
}


CATALOG: list[dict[str, Any]] = [
    {
        "name": "filesystem",
        "titulo": "Arquivos",
        "blurb": "Ler e escrever arquivos numa pasta que você escolher.",
        "runtime": "node",
        "requires_approval": True,
        "config": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "{pasta}"],
            "enabled": True,
        },
        # Campos que a UI pede antes de instalar; `{chave}` é substituída no config.
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
        "name": "memory",
        "titulo": "Memória",
        "blurb": "Um bloco de notas persistente que o agente consulta entre conversas.",
        "runtime": "node",
        "requires_approval": False,
        "config": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
            "enabled": True,
        },
        "campos": [],
    },
    {
        "name": "sequential-thinking",
        "titulo": "Raciocínio passo a passo",
        "blurb": "Ajuda o modelo a quebrar problemas difíceis em etapas encadeadas.",
        "runtime": "node",
        "requires_approval": False,
        "config": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
            "enabled": True,
        },
        "campos": [],
    },
    {
        "name": "git",
        "titulo": "Git",
        "blurb": "Histórico, diffs e status de um repositório local.",
        "runtime": "uv",
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
    {
        "name": "fetch",
        "titulo": "Buscar página",
        "blurb": "Baixa uma página da web e entrega o conteúdo em texto limpo.",
        "runtime": "uv",
        "requires_approval": False,
        "config": {
            "command": "uvx",
            "args": ["mcp-server-fetch"],
            "enabled": True,
        },
        "campos": [],
    },
    {
        "name": "sqlite",
        "titulo": "SQLite",
        "blurb": "Consultar e resumir um banco SQLite local.",
        "runtime": "uv",
        "requires_approval": True,
        "config": {
            "command": "uvx",
            "args": ["mcp-server-sqlite", "--db-path", "{banco}"],
            "enabled": True,
        },
        "campos": [
            {
                "key": "banco",
                "label": "Arquivo do banco",
                "help": "Caminho do arquivo .db / .sqlite.",
                "placeholder": "/Users/voce/dados/vendas.db",
            }
        ],
    },
]


def entry_for(name: str) -> Optional[dict[str, Any]]:
    return next((e for e in CATALOG if e["name"] == name), None)


def runtime_disponivel(runtime: str) -> bool:
    """O runtime deste servidor existe na máquina? Alimenta o aviso antes de instalar."""
    import shutil

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
        rt = RUNTIMES.get(e["runtime"], {})
        saida.append(
            {
                **{k: v for k, v in e.items() if k != "config"},
                "runtime_pronto": runtime_disponivel(e["runtime"]),
                "runtime_titulo": rt.get("titulo", e["runtime"]),
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
    cfg["args"] = [_sub(a) for a in cfg.get("args", [])]
    cfg["requires_approval"] = entry.get("requires_approval", True)
    return cfg
