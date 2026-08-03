"""Motor local (llama.cpp) — binário embutido sob demanda, modelos GGUF e auto-start.

O provedor "Mangaba Local" fala com um `llama-server` (llama.cpp) que o PRÓPRIO APP baixa,
gerencia e sobe — nada de instalador externo, conta ou chave. Três degraus, do mais barato
ao mais caro:

1. `engine_status()` — servidor no ar? Nada a fazer.
2. `ensure_running()` — binário e modelo presentes ⇒ sobe `llama-server` em segundo plano.
3. `install()` / `pull(tag)` — baixa o binário oficial (release do llama.cpp no GitHub)
   e o modelo GGUF (Hugging Face, quantização Q4_K_M).

Por que llama.cpp e não Ollama: o binário é pequeno, roda dentro da pasta de estado do app
(sem admin, sem app de bandeja) e o `--jinja` dá **tool calling nativo** aos modelos Qwen3 —
o que devolve ao agente ler arquivo, rodar comando e usar conector com um modelo local.

O nome do produto na UI é "Mangaba Local"; o motor por baixo é o llama.cpp (MIT) e os
modelos são os Qwen3 (Apache-2.0) — ambos creditados no blurb do provedor.
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
import threading
import time
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Optional

import httpx

# 127.0.0.1 e não "localhost": no Windows o nome resolve ::1 (IPv6) primeiro e o servidor
# escuta em IPv4 — cada sonda pagaria uma tentativa perdida. O IP literal não passa por
# resolvedor nenhum.
DEFAULT_PORT = 8778
DEFAULT_HOST = f"http://127.0.0.1:{DEFAULT_PORT}"

_RELEASES_LATEST = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

# Modelos oferecidos, do menor para o maior. Q4_K_M: abaixo disso a qualidade cai rápido
# demais para valer o download. `min_ram_gb` é o piso da faixa da tabela de recomendação.
CATALOG: list[dict[str, Any]] = [
    {
        "tag": "qwen3-4b",
        "label": "Qwen3 4B · Local",
        "file": "Qwen3-4B-Q4_K_M.gguf",
        "url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
        "download_gb": 2.5,
        "min_ram_gb": 0,
    },
    {
        "tag": "qwen3-8b",
        "label": "Qwen3 8B · Local",
        "file": "Qwen3-8B-Q4_K_M.gguf",
        "url": "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf",
        "download_gb": 5.0,
        "min_ram_gb": 6,
    },
    {
        "tag": "qwen3-14b",
        "label": "Qwen3 14B · Local",
        "file": "Qwen3-14B-Q4_K_M.gguf",
        "url": "https://huggingface.co/Qwen/Qwen3-14B-GGUF/resolve/main/Qwen3-14B-Q4_K_M.gguf",
        "download_gb": 9.3,
        "min_ram_gb": 12,
    },
    {
        "tag": "qwen3-32b",
        "label": "Qwen3 32B · Local",
        "file": "Qwen3-32B-Q4_K_M.gguf",
        "url": "https://huggingface.co/Qwen/Qwen3-32B-GGUF/resolve/main/Qwen3-32B-Q4_K_M.gguf",
        "download_gb": 20.2,
        "min_ram_gb": 24,
    },
]

# Instalação e download são operações longas disparadas por DOIS caminhos (bootstrap e UI):
# sem exclusão mútua, as duas frentes brigam pelo mesmo arquivo/estado.
_install_lock = threading.Lock()
_pull_lock = threading.Lock()
_serve_lock = threading.Lock()

# Estado vivo compartilhado com a UI (mesmo shape do card antigo do Mangaba Local).
# Escrito pelas threads de download/instalação e lido pelo engine_status; o lock evita
# um snapshot com `phase` novo e `progress` velho (barra momentaneamente inconsistente).
_state_lock = threading.Lock()
_bootstrap: dict[str, Any] = {"phase": "idle", "progress": 0.0, "error": None}
_pull: dict[str, Any] = {"phase": "idle", "tag": None, "progress": 0.0, "error": None}

_proc: Optional[subprocess.Popen] = None
_active_tag: Optional[str] = None

_ULTIMO_AUTOSTART = 0.0
_AUTOSTART_INTERVALO = 30.0  # `get_settings` roda o tempo todo; não vale tentar a cada sonda


def _state_dir() -> Path:
    from ..secrets import state_dir

    base = state_dir() / "local-engine"
    (base / "bin").mkdir(parents=True, exist_ok=True)
    (base / "models").mkdir(parents=True, exist_ok=True)
    return base


def entry_for_tag(tag: str) -> Optional[dict[str, Any]]:
    return next((m for m in CATALOG if m["tag"] == tag), None)


def model_path(tag: str) -> Optional[Path]:
    m = entry_for_tag(tag)
    if not m:
        return None
    return _state_dir() / "models" / m["file"]


def downloaded_tags() -> list[str]:
    return [m["tag"] for m in CATALOG if (p := model_path(m["tag"])) and p.exists()]


def ram_gb() -> float:
    """Memória física total, sem dependências novas (psutil não entra por causa disto)."""
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            return int(out.stdout.strip()) / 1024**3
        if system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 1024**3
        # Linux e afins
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except Exception:
        return 8.0  # palpite conservador: recomenda o 8B, que roda em quase tudo


def recommended(ram: Optional[float] = None) -> dict[str, Any]:
    """O maior modelo do catálogo que ESTA máquina roda bem, pela RAM detectada."""
    ram = ram_gb() if ram is None else ram
    escolha = CATALOG[0]
    for m in CATALOG:
        if ram >= m["min_ram_gb"] and (ram >= m["download_gb"] + 3):
            escolha = m
    return {"tag": escolha["tag"], "download_gb": escolha["download_gb"], "ram_gb": ram}


# -- binário -------------------------------------------------------------------


def _binary_name() -> str:
    return "llama-server.exe" if platform.system() == "Windows" else "llama-server"


def find_binary() -> Optional[str]:
    """Caminho do llama-server gerenciado pelo app (ou None). Só olhamos a NOSSA pasta:
    um llama.cpp do sistema pode ser velho demais para `--jinja`, e depurar isso à
    distância custa mais do que 20 MB de download."""
    cand = _state_dir() / "bin" / _binary_name()
    return str(cand) if cand.exists() else None


def _pick_asset(assets: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """O zip certo para esta plataforma, dentre os assets da release do llama.cpp."""
    system = platform.system()
    names = [(a.get("name") or "", a) for a in assets]
    if system == "Darwin":
        want = ["macos-arm64"] if platform.machine() == "arm64" else ["macos-x64"]
    elif system == "Windows":
        # CPU cobre toda máquina; quem tem GPU ganha depois (Vulkan exigiria testar driver).
        want = ["win-cpu-x64", "win-avx2-x64", "win-x64"]
    else:
        want = ["ubuntu-x64", "linux-x64"]
    for token in want:
        for name, asset in names:
            # macOS/Linux saem em .tar.gz, Windows em .zip — aceitamos os dois.
            if token in name and name.endswith((".zip", ".tar.gz")):
                return asset
    return None


def install() -> dict[str, Any]:
    """Baixa a release oficial do llama.cpp e deixa o `llama-server` pronto na pasta do app.
    Nunca levanta: a UI mostra o erro ao lado do botão que o causou."""
    with _install_lock:
        if find_binary():
            return {"ok": True}
        try:
            with _state_lock:
                _bootstrap.update(phase="installing", progress=0.0, error=None)
            rel = httpx.get(_RELEASES_LATEST, timeout=20, follow_redirects=True).json()
            asset = _pick_asset(rel.get("assets") or [])
            if not asset:
                raise RuntimeError("release do llama.cpp sem binário para esta plataforma")
            name = asset.get("name") or "engine.zip"
            dest = _state_dir() / "bin" / ("engine.tar.gz" if name.endswith(".tar.gz") else "engine.zip")
            _download(asset["browser_download_url"], dest, _bootstrap)
            if dest.name.endswith(".tar.gz"):
                with tarfile.open(dest) as tf:
                    tf.extractall(_state_dir() / "bin")
            else:
                with zipfile.ZipFile(dest) as zf:
                    zf.extractall(_state_dir() / "bin")
            dest.unlink(missing_ok=True)
            # O zip pode trazer o binário em build/bin/ — achata para a raiz de bin/.
            root = _state_dir() / "bin"
            if not (root / _binary_name()).exists():
                found = next(root.rglob(_binary_name()), None)
                if not found:
                    raise RuntimeError("zip da release não trouxe o llama-server")
                for f in found.parent.iterdir():
                    f.rename(root / f.name)
            binary = root / _binary_name()
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            with _state_lock:
                _bootstrap.update(phase="idle", progress=1.0, error=None)
            return {"ok": True}
        except Exception as exc:
            with _state_lock:
                _bootstrap.update(phase="error", error=str(exc))
            return {"ok": False, "error": f"Não consegui baixar o motor local ({exc})."}


# -- modelos -------------------------------------------------------------------


def _download(url: str, dest: Path, state: dict[str, Any]) -> None:
    """Stream para `.part` com progresso em `state` e rename atômico no fim."""
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        with open(part, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    state["progress"] = done / total
    os.replace(part, dest)  # não Path.rename: no Windows ele falha se dest já existe


def pull(tag: str) -> dict[str, Any]:
    """Dispara o download de um modelo do catálogo em segundo plano; progresso via status."""
    m = entry_for_tag(tag)
    if not m:
        return {"ok": False, "error": f"modelo desconhecido: {tag}"}
    dest = model_path(tag)
    assert dest is not None
    if dest.exists():
        return {"ok": True}
    if _pull["phase"] == "pulling":
        return {"ok": False, "error": "já existe um download em andamento"}

    def _job() -> None:
        with _pull_lock:
            try:
                with _state_lock:
                    _pull.update(phase="pulling", tag=tag, progress=0.0, error=None)
                _download(m["url"], dest, _pull)
                with _state_lock:
                    _pull.update(phase="done", progress=1.0)
                # O modelo recém-baixado é o que a pessoa quer usar: sobe já.
                ensure_running(tag)
            except Exception as exc:
                dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
                with _state_lock:
                    _pull.update(phase="error", error=str(exc))

    threading.Thread(target=_job, daemon=True, name="modelo-pull").start()
    return {"ok": True}


# -- servidor ------------------------------------------------------------------


def is_serving(host: str = DEFAULT_HOST, timeout: float = 1.5) -> bool:
    try:
        return httpx.get(host.rstrip("/") + "/v1/models", timeout=timeout).status_code < 300
    except Exception:
        return False


def ensure_running(tag: Optional[str] = None, wait_s: float = 120.0) -> bool:
    """Sobe (ou troca) o llama-server para servir `tag`. O llama.cpp serve UM modelo por
    processo, então trocar de modelo local reinicia o servidor — barato perto do load."""
    global _proc, _active_tag

    with _serve_lock:
        tags = downloaded_tags()
        if not tags:
            return False
        tag = tag if tag in tags else (_active_tag if _active_tag in tags else tags[-1])
        if _active_tag == tag and is_serving():
            return True
        binary = find_binary()
        if not binary:
            return False
        stop()
        _kill_stale_process()  # órfão de um Quit anterior ainda pode segurar a porta
        path = model_path(tag)
        assert path is not None
        cmd = [
            binary,
            "-m", str(path),
            "--host", "127.0.0.1",
            "--port", str(DEFAULT_PORT),
            "--jinja",  # tool calling nativo — a razão de o motor existir
            "--ctx-size", "16384",
            "-ngl", "99",  # tudo que couber na GPU (Metal no macOS); CPU ignora
        ]
        env = {**os.environ, "LLAMA_LOG_VERBOSITY": "1"}
        kwargs: dict[str, Any] = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        # `with` fecha a cópia do handle no pai; o filho mantém a sua — sem handle órfão
        # acumulando a cada reinício (no Windows, um handle aberto trava o append).
        with open(_state_dir() / "engine.log", "ab") as log:
            _proc = subprocess.Popen(cmd, stdout=log, stderr=log, env=env, **kwargs)
        _active_tag = tag
        # PID em disco: o cleanup do app roda por SIGKILL (Quit do desktop), que pula o
        # nosso stop(). Quem subir depois lê o PID e mata o órfão que ficou na porta.
        _write_pidfile(_proc.pid)
        proc = _proc  # referência local — stop() em outra thread não a zera sob os pés
    inicio = time.monotonic()
    while time.monotonic() - inicio < wait_s:
        if is_serving():
            return True
        if proc.poll() is not None:
            return False  # morreu no load — o engine.log conta o porquê
        time.sleep(0.5)
    return False


def _pidfile() -> Path:
    return _state_dir() / "engine.pid"


def _write_pidfile(pid: int) -> None:
    try:
        _pidfile().write_text(str(pid))
    except OSError:
        pass


def _kill_stale_process() -> None:
    """Mata um llama-server órfão de uma execução anterior (Quit do desktop = SIGKILL,
    que pula o nosso stop()). Sem isto, a porta 8778 fica presa e o GGUF na RAM."""
    pf = _pidfile()
    try:
        pid = int(pf.read_text().strip())
    except (OSError, ValueError):
        return
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=0x08000000,
            )
        else:
            os.kill(pid, 9)
    except (OSError, ProcessLookupError):
        pass
    finally:
        pf.unlink(missing_ok=True)


def stop() -> None:
    global _proc
    proc = _proc
    _proc = None
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    _pidfile().unlink(missing_ok=True)


def autostart_em_segundo_plano() -> bool:
    """Sobe o motor sem bloquear quem chamou (a sonda roda em todo fetch da GUI)."""
    global _ULTIMO_AUTOSTART

    agora = time.monotonic()
    if agora - _ULTIMO_AUTOSTART < _AUTOSTART_INTERVALO:
        return False
    if not find_binary() or not downloaded_tags():
        return False
    _ULTIMO_AUTOSTART = agora
    threading.Thread(target=ensure_running, daemon=True, name="motor-autostart").start()
    return True


def active_tag() -> Optional[str]:
    return _active_tag


def engine_status() -> dict[str, Any]:
    """Estado do motor para a UI decidir o que oferecer: rodar, iniciar ou instalar.
    Mesmo shape do card do Mangaba Local na galeria de provedores."""
    installed = find_binary() is not None
    running = is_serving()
    tags = downloaded_tags()
    return {
        "state": "running" if running else ("stopped" if installed else "absent"),
        "installed": installed,
        "running": running,
        "binary": find_binary(),
        "models": len(tags),
        "tags": tags,
        "active": _active_tag,
        **({"bootstrap": dict(_bootstrap), "pull": dict(_pull)}),
        "recommended": recommended(),
    }
