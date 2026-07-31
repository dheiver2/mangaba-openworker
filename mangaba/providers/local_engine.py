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
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx

# 127.0.0.1 e não "localhost": no Windows o nome costuma resolver ::1 (IPv6) primeiro e o
# Ollama escuta em IPv4, então cada sonda pagava uma tentativa perdida antes de acertar —
# o bastante para estourar o timeout curto do gate que decide se os modelos aparecem no
# chat. O IP literal não passa por resolvedor nenhum.
DEFAULT_HOST = "http://127.0.0.1:11434"

# Instalação e download de modelo são operações longas disparadas por DOIS caminhos (a
# thread de bootstrap e a UI): sem exclusão mútua, as duas frentes brigam pelo mesmo
# arquivo/estado.
_install_lock = threading.Lock()
_pull_lock = threading.Lock()
_bootstrap_lock = threading.Lock()

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


# Autostart: o motor é responsabilidade do APP, não do usuário. Quem instalou o Ollama pelo
# instalador oficial ganha um ícone de bandeja que sobe no login — mas quem instalou pelo
# nosso card, ou fechou a bandeja, ou está num Windows onde ela não subiu, ficava com o motor
# parado e o chat "sem modelo" sem nada explicando. Sempre que percebemos o motor parado com
# binário presente, subimos em segundo plano.
_ULTIMO_AUTOSTART = 0.0
_AUTOSTART_INTERVALO = 30.0  # não vale tentar a cada sonda: `get_settings` roda o tempo todo


def autostart_em_segundo_plano(host: str = DEFAULT_HOST) -> bool:
    """Sobe o motor sem bloquear quem chamou. True se uma tentativa foi disparada.

    Não espera o resultado de propósito: os chamadores são caminhos de leitura (a sonda de
    liveness roda em todo fetch da GUI) e travá-los por até 20 s deixaria a interface
    pendurada. A próxima sonda, segundos depois, já encontra o motor no ar."""
    global _ULTIMO_AUTOSTART

    agora = time.monotonic()
    if agora - _ULTIMO_AUTOSTART < _AUTOSTART_INTERVALO:
        return False
    if not find_binary():
        return False  # sem binário não há o que subir — isso é caso de instalação
    _ULTIMO_AUTOSTART = agora
    threading.Thread(
        target=ensure_running, args=(host,), daemon=True, name="motor-autostart"
    ).start()
    return True


def engine_version(host: str = DEFAULT_HOST) -> Optional[str]:
    """Versão do motor local, ou None se ele não responder."""
    try:
        return httpx.get(host.rstrip("/") + "/api/version", timeout=1.5).json().get("version")
    except Exception:
        return None


def engine_status(host: str = DEFAULT_HOST) -> dict[str, Any]:
    """Estado do motor para a UI decidir o que oferecer: rodar, iniciar ou instalar."""
    binary = find_binary()
    running = is_serving(host)
    if running:
        state = "running"
    elif binary:
        state = "stopped"
        autostart_em_segundo_plano(host)  # instalado e parado ⇒ o app sobe, o usuário não
    else:
        state = "absent"
    # `models`: motor no ar SEM nenhum modelo baixado é exatamente o estado que produz o
    # "sem modelo" no chat — sem este número a UI não sabia diferenciar de "tudo pronto".
    return {
        "state": state,
        "installed": bool(binary),
        "running": running,
        "binary": binary,
        "models": len(list_models(host)) if running else 0,
    }


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
    # O contexto sai de `contexto_para_a_maquina()`: fixá-lo em 16k custava ~2,4 GB de KV
    # cache e, somado aos pesos, não cabia numa máquina de 8 GB — o processo do modelo
    # morria e o motor devolvia algo que não era JSON.
    # KEEP_ALIVE=30m evita descarregar o modelo a cada 5 min ocioso (recarga de 5–15 s
    # na primeira mensagem depois de uma pausa). Valores do usuário no ambiente vencem.
    # Ambiente MÍNIMO: `dict(os.environ)` levava MANGABA_API_TOKEN e todas as chaves de
    # provedor já carregadas para um processo que sobrevive ao sidecar (start_new_session)
    # e cujo ambiente qualquer processo do mesmo usuário lê (/proc/<pid>/environ, `ps -E`).
    # O motor local só precisa de PATH/HOME e das suas próprias OLLAMA_*.
    # Comparação sem caixa: no Windows o `os.environ` do Python MAIÚSCULA todas as chaves
    # (SystemRoot vira SYSTEMROOT), então a lista com grafia mista deixava o SYSTEMROOT de
    # fora — e sem ele os sockets do Windows nem inicializam: o `ollama serve` que o app
    # tentasse subir morria no berço. WINDIR/PATHEXT/PROGRAMDATA entram pelo mesmo motivo.
    _ESSENCIAIS = {
        "path", "home", "userprofile", "tmpdir", "temp", "tmp",
        "systemroot", "windir", "pathext", "systemdrive", "localappdata",
        "appdata", "programdata", "programfiles", "comspec", "username", "lang",
    }
    # NO_PROXY explícito: o motor é Go e respeita HTTP_PROXY/HTTPS_PROXY do ambiente. Numa
    # máquina com proxy corporativo (ou antivírus que intercepta) e sem NO_PROXY, até a
    # conversa interna do motor com o próprio runner em 127.0.0.1 vai parar no proxy, que
    # responde HTML — e o motor morre com "invalid character '<' looking for beginning of
    # value". Nosso filtro já não repassa as variáveis de proxy, mas declarar é de graça e
    # protege quem tiver um proxy definido no registro do Windows.
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper().startswith("OLLAMA_") or k.lower() in _ESSENCIAIS
    }
    env.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")
    env.setdefault("no_proxy", "localhost,127.0.0.1,::1")
    env.setdefault("OLLAMA_CONTEXT_LENGTH", str(contexto_para_a_maquina()))
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

    # Sem esta trava, o bootstrap do primeiro boot e um clique em "Instalar" no card
    # baixavam ~180 MB PARA O MESMO ARQUIVO ao mesmo tempo — os dois streams se
    # intercalavam e o zip resultante era lixo (extraído por cima de /Applications).
    if not _install_lock.acquire(blocking=False):
        return {"ok": False, "error": "A instalação do motor local já está em andamento."}
    try:
        return _install(system, progress)
    finally:
        _install_lock.release()


def _install(system: str, progress: Optional[Any]) -> dict[str, Any]:
    """Corpo da instalação, já sob `_install_lock`."""
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
                # Zip Slip: `extractall` puro aceita membros com `../` e caminhos absolutos —
                # um pacote adulterado (asset trocado, proxy TLS, redirect) escreveria em
                # qualquer lugar do perfil do usuário (ex.: ~/Library/LaunchAgents) e ganharia
                # persistência. Recusamos o pacote inteiro em vez de "pular" o membro ruim:
                # um zip com travessia não é um Ollama legítimo, é um ataque.
                for membro in zf.namelist():
                    destino = (Path("/Applications") / membro).resolve()
                    if not str(destino).startswith("/Applications/"):
                        return {
                            "ok": False,
                            "error": "O pacote do motor local contém caminhos inválidos e foi recusado.",
                        }
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


# Registries de terceiros são aceitos pelo `/api/pull` do Ollama ("evil.example/org/x"),
# então um POST autenticado bastaria para a máquina puxar dezenas de GB de origem hostil —
# e o modelo resultante ficaria selecionável no app. Só liberamos tags da biblioteca
# oficial (sem host) ou do Hugging Face, que é o caminho que documentamos.
_TAG_OFICIAL = re.compile(r"^[a-z0-9][a-z0-9._-]*(:[a-zA-Z0-9._-]+)?$")
_TAG_HF = re.compile(r"^hf\.co/[\w.-]+/[\w.-]+(:[\w.-]+)?$", re.IGNORECASE)


def tag_permitido(tag: str) -> bool:
    """O tag pode ser baixado? Barra registries arbitrários vindos pela API."""
    tag = (tag or "").strip()
    if not tag or len(tag) > 200 or ".." in tag:
        return False
    return bool(_TAG_OFICIAL.match(tag) or _TAG_HF.match(tag))


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
            # `read=None` (sem teto) travava a thread para sempre quando a conexão estalava
            # sem fechar (suspend/resume da máquina): o estado ficava em "pulling" eterno e
            # nenhum download novo era aceito. 180 s é folgado para o intervalo entre linhas
            # de progresso do Ollama e ainda detecta uma conexão morta.
            timeout=httpx.Timeout(30.0, read=180.0),
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


def contexto_para_a_maquina(ram_gb: Optional[float] = None) -> int:
    """Janela de contexto que o motor pode servir sem derrubar o processo do modelo.

    O agente manda ~3.200 tokens fixos por turno (system prompt + 19 schemas de ferramenta),
    então o padrão do Ollama (4096) trunca o começo da conversa em silêncio e o modelo
    "esquece" as ferramentas — foi por isso que passamos a fixar 16384. Só que o KV cache
    cresce LINEARMENTE com o contexto: num modelo 4B são ~2,4 GB só de cache a 16k, que
    somados aos pesos passam de 4,9 GB. Numa máquina de 8 GB rodando Windows isso não cabe,
    a alocação falha e o motor responde algo que não é JSON ("invalid character '<'...").
    Um contexto menor degrada a memória da conversa; um contexto grande demais impede
    qualquer conversa. Escalamos pela RAM e assumimos a primeira perda quando preciso."""
    ram = total_ram_gb() if ram_gb is None else ram_gb
    if ram >= 16.0:
        return 16384
    if ram >= 8.0:
        return 8192
    return 4096  # abaixo disso, caber é mais importante que lembrar


# Teto do download AUTOMÁTICO do primeiro uso. Adaptar o modelo à máquina é certo, mas
# puxar 20 GB sem ninguém pedir, logo na primeira abertura, não é: seria horas de download
# e disco cheio para quem só queria ver o app funcionando. Acima deste teto o modelo maior
# continua a UM clique no card ("baixar o recomendado"), aí com o usuário decidindo.
_TETO_DOWNLOAD_AUTOMATICO_GB = 5.0


def modelo_inicial_para_a_maquina(ram_gb: Optional[float] = None) -> dict[str, Any]:
    """O maior modelo que ESTA máquina roda bem E que cabe num download automático.

    Antes o primeiro uso baixava sempre o mesmo modelo pequeno, em qualquer máquina: quem
    tinha 32 GB ganhava um 4B por padrão, e quem tinha 4 GB ganhava um download que talvez
    nem coubesse. A escolha passa pelos mesmos tiers da recomendação, só que limitada pelo
    teto acima."""
    ram = total_ram_gb() if ram_gb is None else ram_gb
    for minimo, tag, download_gb in _TIERS:
        if ram >= minimo and download_gb <= _TETO_DOWNLOAD_AUTOMATICO_GB:
            return {"tag": tag, "download_gb": download_gb, "ram_gb": round(ram, 1)}
    return {"tag": STARTER_MODEL, "download_gb": 2.5, "ram_gb": round(ram, 1)}


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


def aguardar_e_continuar(host: str = DEFAULT_HOST, minutos: float = 15.0) -> dict[str, Any]:
    """Espera o motor aparecer (o usuário concluindo o instalador) e então completa o
    primeiro uso.

    No Windows a instalação é do usuário: entregamos o instalador oficial e ele passa pelo
    UAC e pelo assistente — o que leva minutos. Redisparar o bootstrap no instante em que
    entregamos o .exe (como fazíamos) o encontrava sem binário e ele voltava para
    `needs_user`: o motor subia depois, mas o modelo inicial NUNCA era baixado e o chat
    ficava "sem modelo" para sempre. Aqui a gente espera de verdade."""
    st = _bootstrap_state
    st.update(phase="needs_user", error=None)
    limite = time.monotonic() + minutos * 60
    while time.monotonic() < limite:
        if find_binary() or is_serving(host):
            return bootstrap(host)
        time.sleep(5)
    return {"ok": False, "timeout": True}


def start_pull(tag: str, host: str = DEFAULT_HOST) -> dict[str, Any]:
    """Baixa um modelo em thread própria; o estado fica em pull_status() para a UI."""
    import threading

    if not tag_permitido(tag):
        return {"ok": False, "error": f"Tag de modelo não permitido: {tag}"}
    # Checar-e-marcar tem de ser atômico: duas requisições quase simultâneas (duplo clique)
    # passavam as duas pelo teste e disputavam o MESMO _pull_state — a primeira a terminar
    # marcava "done" enquanto a outra ainda baixava gigabytes.
    with _pull_lock:
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
    # Reentrância: o bootstrap roda no lifespan E de novo depois de uma instalação pela UI.
    # Sem a trava, dois deles se atropelariam no mesmo estado (e disputariam o download do
    # modelo inicial). Quem chegar segundo sai de mãos abanando, não em erro.
    if not _bootstrap_lock.acquire(blocking=False):
        return {"ok": False, "busy": True}
    try:
        return _bootstrap(host)
    finally:
        _bootstrap_lock.release()


def _bootstrap(host: str) -> dict[str, Any]:
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
        # `_pull_state` é a fonte ÚNICA de "há um download de modelo em curso" — o da UI e
        # o do bootstrap se enxergam por ele. Durante o primeiro boot o card já oferece o
        # "baixar recomendado"; dois downloads de GBs em paralelo saturam disco e banda.
        # (A trava só cobre o checar-e-marcar; o download em si roda fora dela.)
        with _pull_lock:
            ja_baixando = pull_in_progress()
            if not ja_baixando:
                _pull_state.update(
                    phase="pulling",
                    tag=modelo_inicial_para_a_maquina()["tag"],
                    progress=0.0,
                    error=None,
                )
        if ja_baixando:
            st.update(phase="ready", progress=1.0, error=None)
            return {"ok": True, "pull_em_andamento": True}

        st.update(phase="pulling", progress=0.0)
        inicial = modelo_inicial_para_a_maquina()["tag"]
        res = pull_model(inicial, host, progress=lambda p: st.update(progress=p))
        _pull_state.update(
            phase="done" if res.get("ok") else "error",
            progress=1.0 if res.get("ok") else _pull_state["progress"],
            error=None if res.get("ok") else res.get("error"),
        )
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
