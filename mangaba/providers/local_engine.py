"""Motor local (Ollama) — detecção do binário, auto-start do servidor e instalação sob demanda.

O provedor "Mangaba Local" fala com o Ollama pela API OpenAI-compatível em `/v1`, mas até aqui
o app só *apontava* para uma instalação que o usuário tinha de providenciar e manter no ar.
Este módulo fecha essa lacuna em três degraus, do mais barato ao mais caro:

1. `engine_status()` — o servidor já responde? Então não há nada a fazer.
2. `ensure_running()` — binário instalado mas servidor parado ⇒ sobe `ollama serve` em segundo
   plano e espera a porta abrir.
3. `install()` — binário ausente ⇒ baixa o instalador oficial e o executa.

O nome do produto na UI é "Mangaba Local"; o motor por baixo continua sendo o Ollama (MIT) e é
creditado no blurb do provedor. Renomear o rótulo não pode esconder a origem.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import httpx

DEFAULT_HOST = "http://localhost:11434"

# Onde o instalador oficial deixa o binário em cada plataforma. O PATH cobre a maioria dos
# casos, mas no macOS o app do menu-bar não põe nada no PATH de um processo que não veio de
# um shell de login — que é exatamente o caso do nosso sidecar.
_EXTRA_PATHS = {
    "Darwin": [
        "/Applications/Ollama.app/Contents/Resources/ollama",
        "/usr/local/bin/ollama",
        "/opt/homebrew/bin/ollama",
    ],
    "Linux": ["/usr/local/bin/ollama", "/usr/bin/ollama"],
    "Windows": [
        r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe",
        r"%PROGRAMFILES%\Ollama\ollama.exe",
    ],
}


def find_binary() -> Optional[str]:
    """Caminho do binário do motor local, ou None se não estiver instalado."""
    found = shutil.which("ollama")
    if found:
        return found
    for raw in _EXTRA_PATHS.get(platform.system(), []):
        candidate = Path(os.path.expandvars(raw))
        if candidate.exists():
            return str(candidate)
    return None


def is_serving(host: str = DEFAULT_HOST, timeout: float = 1.5) -> bool:
    """O servidor local está no ar e falando a API OpenAI-compatível?"""
    try:
        resp = httpx.get(host.rstrip("/") + "/v1/models", timeout=timeout)
        return resp.status_code < 300
    except Exception:
        return False


def engine_status(host: str = DEFAULT_HOST) -> dict[str, Any]:
    """Estado do motor para a UI decidir o que oferecer: rodar, iniciar ou instalar."""
    binary = find_binary()
    running = is_serving(host)
    if running:
        state = "running"
    elif binary:
        state = "stopped"
    else:
        state = "absent"
    return {"state": state, "installed": bool(binary), "running": running, "binary": binary}


def ensure_running(host: str = DEFAULT_HOST, wait_secs: float = 20.0) -> dict[str, Any]:
    """Sobe `ollama serve` se o binário existir e o servidor estiver parado.

    Idempotente: se já estiver servindo, retorna de imediato sem gastar um spawn.
    """
    if is_serving(host):
        return {"ok": True, "state": "running"}

    binary = find_binary()
    if not binary:
        return {"ok": False, "state": "absent", "error": "O motor local não está instalado."}

    # `serve` é um processo de longa duração: desgarramos do sidecar (start_new_session) para
    # que ele sobreviva a um restart nosso, e silenciamos a saída para não encher o log do app.
    # No Windows, CREATE_NO_WINDOW evita o console piscando — mesmo cuidado que o sidecar toma.
    creationflags = 0x08000000 if platform.system() == "Windows" else 0
    # O agente manda ~3.200 tokens fixos por turno (system prompt + 19 schemas de tools).
    # Com o contexto padrão do Ollama (4096), o INÍCIO da conversa é truncado em silêncio
    # — o modelo "esquece" as ferramentas. 16k dá folga com ~1–2 GB de KV cache no Q4.
    # KEEP_ALIVE=30m evita descarregar o modelo a cada 5 min ocioso (recarga de 5–15 s
    # na primeira mensagem depois de uma pausa). Valores do usuário no ambiente vencem.
    env = dict(os.environ)
    env.setdefault("OLLAMA_CONTEXT_LENGTH", "16384")
    env.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    try:
        subprocess.Popen(
            [binary, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            creationflags=creationflags,
        )
    except Exception as exc:
        return {"ok": False, "state": "stopped", "error": f"Não consegui iniciar o motor local ({exc.__class__.__name__})."}

    deadline = time.monotonic() + wait_secs
    while time.monotonic() < deadline:
        if is_serving(host):
            return {"ok": True, "state": "running"}
        time.sleep(0.4)
    return {
        "ok": False,
        "state": "stopped",
        "error": "O motor local foi iniciado mas não respondeu a tempo.",
    }


_RELEASE = "https://github.com/ollama/ollama/releases/latest/download"
_DOWNLOADS = {
    "Darwin": (f"{_RELEASE}/Ollama-darwin.zip", "Ollama-darwin.zip"),
    "Windows": (f"{_RELEASE}/OllamaSetup.exe", "OllamaSetup.exe"),
}


def _cache_dir() -> Path:
    d = Path.home() / ".cache" / "mangaba" / "engine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def install(progress: Optional[Any] = None) -> dict[str, Any]:
    """Baixa o motor local oficial e o instala.

    macOS: o pacote é só um .app — extraímos direto em /Applications, sem privilégios.
    Windows: entregamos o instalador ao usuário em vez de executá-lo por conta própria. Rodar
    um .exe recém-baixado de forma silenciosa é exatamente o padrão que não queremos no app;
    o instalador oficial já pede consentimento via UAC, e essa confirmação é do usuário.
    Linux: o método oficial é um script shell — apontamos a instrução em vez de canalizar
    `curl | sh` sem o usuário ver o que roda.
    """
    system = platform.system()
    if find_binary():
        return {"ok": True, "already": True}

    if system == "Linux":
        return {
            "ok": False,
            "error": "No Linux, instale com: curl -fsSL https://ollama.com/install.sh | sh",
            "manual": True,
        }

    target = _DOWNLOADS.get(system)
    if not target:
        return {"ok": False, "error": f"Sem instalador automático para {system}."}

    url, filename = target
    dest = _cache_dir() / filename
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            done = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done / total)
    except Exception as exc:
        return {"ok": False, "error": f"Falha ao baixar o motor local ({exc.__class__.__name__})."}

    try:
        if system == "Darwin":
            import zipfile

            with zipfile.ZipFile(dest) as zf:
                zf.extractall("/Applications")
            # O .zip perde o bit de execução; sem isto o app extraído não abre.
            binary = Path("/Applications/Ollama.app/Contents/Resources/ollama")
            if binary.exists():
                binary.chmod(0o755)
        else:  # Windows — o usuário conclui a instalação no diálogo oficial.
            os.startfile(str(dest))  # type: ignore[attr-defined]
            return {"ok": True, "handed_off": True}
    except Exception as exc:
        return {"ok": False, "error": f"Falha ao instalar o motor local ({exc.__class__.__name__})."}

    return {"ok": True, "installed": bool(find_binary())}


def pull_model(
    tag: str, host: str = DEFAULT_HOST, progress: Optional[Any] = None
) -> dict[str, Any]:
    """Baixa um modelo pela API nativa `/api/pull` (streaming de linhas JSON com progresso)."""
    import json

    try:
        with httpx.stream(
            "POST",
            host.rstrip("/") + "/api/pull",
            json={"model": tag},
            timeout=httpx.Timeout(30.0, read=None),  # download longo: sem teto de leitura
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("error"):
                    return {"ok": False, "error": ev["error"]}
                total, done = ev.get("total") or 0, ev.get("completed") or 0
                if progress and total:
                    progress(done / total)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"Falha ao baixar o modelo {tag} ({exc.__class__.__name__})."}


# Modelo inicial do primeiro uso: pequeno o bastante para descer em minutos (~2,5 GB),
# suporta tool-calling e — decisivo — licença Apache-2.0. O antigo qwen2.5:3b-instruct
# está sob "Qwen RESEARCH LICENSE" (só pesquisa): não pode ser o padrão de fábrica de
# um produto. As variantes 7B/14B da família continuam Apache e seguem nos tiers.
STARTER_MODEL = "qwen3:4b"


def total_ram_gb() -> float:
    """RAM física total, em GB. 0.0 se não der para descobrir (aí ninguém recomenda nada)."""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return stat.ullTotalPhys / 1e9
        if system == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            return int(out.stdout.strip()) / 1e9
        # Linux
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024 / 1e9
    except Exception:
        pass
    return 0.0


# Curadoria por RAM (tags padrão do Ollama = Q4_K_M, o piso de qualidade que oferecemos —
# quantizações abaixo de Q4 degradam demais, ver o caso Bonsai Q1). Regra: o arquivo deve
# caber em ~2/3 da RAM; o resto é sistema + contexto. Tamanhos conferidos no registro
# em 30/07/2026.
_TIERS = [
    # (ram mínima em GB, tag, tamanho do download em GB)
    (24.0, "qwen3:32b", 20.2),  # o maior generalista que vale a pena hoje
    (12.0, "qwen3:14b", 9.3),  # melhor 14B geral; par do gemma4:e4b
    (6.0, "qwen2.5:7b-instruct", 4.7),  # entrada digna em 8 GB
    (0.0, STARTER_MODEL, 2.5),  # máquinas mínimas ficam no starter
]


def recommended_model(ram_gb: Optional[float] = None) -> dict[str, Any]:
    """O maior modelo local que ESTA máquina roda bem — recomendação do card da UI."""
    ram = total_ram_gb() if ram_gb is None else ram_gb
    for minimo, tag, download_gb in _TIERS:
        if ram >= minimo:
            return {"tag": tag, "download_gb": download_gb, "ram_gb": round(ram, 1)}
    return {"tag": STARTER_MODEL, "download_gb": 1.9, "ram_gb": round(ram, 1)}


# Download de modelo disparado pela UI (card "Baixar recomendado") — mesmo formato de
# progresso do bootstrap, para o polling do frontend ser um só.
_pull_state: dict[str, Any] = {"phase": "idle", "tag": None, "progress": 0.0, "error": None}


def pull_status() -> dict[str, Any]:
    return dict(_pull_state)


def pull_in_progress() -> bool:
    return _pull_state["phase"] == "pulling"


def start_pull(tag: str, host: str = DEFAULT_HOST) -> dict[str, Any]:
    """Baixa um modelo em thread própria; o estado fica em pull_status() para a UI."""
    import threading

    if pull_in_progress():
        return {"ok": False, "error": f"Já baixando {_pull_state['tag']}."}
    _pull_state.update(phase="pulling", tag=tag, progress=0.0, error=None)

    def _run() -> None:
        res = pull_model(tag, host, progress=lambda p: _pull_state.update(progress=p))
        if res.get("ok"):
            _pull_state.update(phase="done", progress=1.0)
        else:
            _pull_state.update(phase="error", error=res.get("error"))

    threading.Thread(target=_run, daemon=True, name=f"pull-{tag}").start()
    return {"ok": True, "tag": tag}

# Estado do bootstrap de primeiro uso, para a UI acompanhar sem bloquear nada.
# Fases: idle → installing → starting → pulling → ready | needs_user | error
_bootstrap_state: dict[str, Any] = {"phase": "idle", "progress": 0.0, "error": None}


def bootstrap_status() -> dict[str, Any]:
    return dict(_bootstrap_state)


def bootstrap(host: str = DEFAULT_HOST) -> dict[str, Any]:
    """Deixa o Mangaba Local utilizável de ponta a ponta, sem cliques: instala o motor
    (onde dá para fazer isso em silêncio), sobe o servidor e garante ao menos um modelo.

    Windows fica de fora da instalação automática de propósito: `install()` ali dispara o
    instalador oficial com diálogo UAC, e um prompt de privilégio surgindo sozinho na
    primeira abertura do app é exatamente o comportamento de malware que não vamos imitar —
    o card do provedor oferece o mesmo caminho com um clique consciente do usuário.
    """
    st = _bootstrap_state
    st.update(phase="starting", progress=0.0, error=None)

    if not find_binary() and not is_serving(host):
        if platform.system() == "Windows":
            st.update(phase="needs_user", error=None)
            return {"ok": False, "needs_user": True}
        st.update(phase="installing")
        res = install(progress=lambda p: st.update(progress=p))
        if not res.get("ok"):
            st.update(phase="error", error=res.get("error"))
            return res

    st.update(phase="starting", progress=0.0)
    run = ensure_running(host)
    if not run.get("ok"):
        st.update(phase="error", error=run.get("error"))
        return run

    if not list_models(host):
        st.update(phase="pulling", progress=0.0)
        res = pull_model(STARTER_MODEL, host, progress=lambda p: st.update(progress=p))
        if not res.get("ok"):
            st.update(phase="error", error=res.get("error"))
            return res

    st.update(phase="ready", progress=1.0, error=None)
    return {"ok": True, "models": list_models(host)}


def list_models(host: str = DEFAULT_HOST, timeout: float = 5.0) -> list[str]:
    """Modelos já baixados na máquina. Lista vazia se o servidor não responder."""
    try:
        resp = httpx.get(host.rstrip("/") + "/v1/models", timeout=timeout)
        if resp.status_code >= 300:
            return []
        return [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
    except Exception:
        return []
