"""Verifica o contrato entre o shell Tauri (Rust), o servidor (Python) e a GUI (TS).

As três partes combinam nomes que nenhum compilador confere: variáveis de
ambiente, cabeçalhos HTTP, argumentos de linha de comando e onde o sidecar mora.
Renomear de um lado e esquecer do outro compila, passa em todos os testes de
unidade e só falha na máquina do usuário — o app abre e fica em "Não conectado",
sem mensagem.

Não é hipótese: os defeitos desta sessão foram todos desse tipo (código correto,
combinação entre as partes quebrada). Estes testes leem os fontes das três
linguagens e afirmam que continuam de acordo.

Ler texto-fonte é grosseiro de propósito — é o que permite comparar Rust, Python
e TypeScript sem compilar nem executar nenhum dos três.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
LIB_RS = RAIZ / "surfaces" / "gui" / "src-tauri" / "src" / "lib.rs"
RUN_PY = RAIZ / "mangaba" / "server" / "run.py"
SECRETS_PY = RAIZ / "mangaba" / "secrets.py"
API_TS = RAIZ / "surfaces" / "gui" / "src" / "api.ts"


@pytest.fixture(scope="module")
def rust() -> str:
    return LIB_RS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def python_run() -> str:
    return RUN_PY.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Variáveis de ambiente: o Rust escreve, o Python lê.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "variavel",
    ["MANGABA_API_TOKEN", "MANGABA_EXIT_WITH_PARENT", "MANGABA_PARENT_PID"],
)
def test_variaveis_que_o_rust_envia_o_python_le(variavel, rust, python_run):
    assert f'.env("{variavel}"' in rust, f"{variavel}: o Rust deixou de enviar"
    assert variavel in python_run, (
        f"{variavel}: o Rust envia mas o Python nao le mais — o sidecar perde "
        f"a autenticacao ou o vinculo com o app"
    )


def test_state_dir_concorda_entre_rust_e_python():
    """Divergir aqui separa o estado: a GUI grava a senha num lugar e o
    servidor procura noutro."""
    rust = LIB_RS.read_text(encoding="utf-8")
    python = SECRETS_PY.read_text(encoding="utf-8")

    # Rust: PathBuf::from(appdata).join("mangaba")
    assert re.search(r'var\("APPDATA"\)', rust)
    assert re.search(r'\.join\("mangaba"\)', rust)
    # Python: Path(appdata) / "mangaba"
    assert 'os.environ.get("APPDATA")' in python
    assert 'Path(appdata) / "mangaba"' in python

    # Ambos honram o override, do qual dependem sidecar e testes.
    assert 'var("MANGABA_STATE_DIR")' in rust
    assert 'os.environ.get("MANGABA_STATE_DIR")' in python


# --------------------------------------------------------------------------
# Linha de comando do sidecar.
# --------------------------------------------------------------------------
def test_argumentos_do_sidecar(rust, python_run):
    """O Rust invoca `--host H --port P`; o Python precisa aceitar ambos."""
    assert '"--host"' in rust and '"--port"' in rust
    assert '"--host"' in python_run, "o servidor deixou de aceitar --host"
    assert '"--port"' in python_run, "o servidor deixou de aceitar --port"


def test_nome_e_lugar_do_sidecar(rust):
    """O Rust procura `sidecar/mangaba-server[.exe]` ao lado do executável.

    É o que o empacotamento precisa entregar — nos dois sistemas. Se o nome
    mudar de um lado só, o app sobe sem servidor."""
    assert '"mangaba-server.exe"' in rust
    assert '"mangaba-server"' in rust
    assert '.join("sidecar")' in rust

    # E o empacotamento coloca exatamente ali.
    conf = (RAIZ / "surfaces/gui/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    assert '"binaries/sidecar": "sidecar"' in conf, (
        "tauri.conf.json nao instala mais os recursos em sidecar/ — o Rust nao "
        "vai achar o servidor"
    )


# --------------------------------------------------------------------------
# Injeção Rust -> GUI e cabeçalhos GUI -> servidor.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("chave", ["__MANGABA_HTTP__", "__MANGABA_WS__", "__MANGABA_API_TOKEN__"])
def test_valores_injetados_sao_os_que_a_gui_le(chave, rust):
    """O Rust injeta esses globais antes da SPA carregar; a GUI os consome.

    Sem eles a interface nao sabe em qual porta falar (o sidecar sobe numa porta
    livre aleatoria, nao na 8765)."""
    assert f"window.{chave}=" in rust, f"o Rust parou de injetar {chave}"
    assert API_TS.exists()
    assert chave in API_TS.read_text(encoding="utf-8"), (
        f"a GUI nao le mais {chave} — perde o endereco ou o token do sidecar"
    )


def test_cabecalhos_de_autenticacao_batem():
    """Dois cabeçalhos, dois papéis: o token prova mesma máquina, a sessão prova
    que é a pessoa certa nela. Renomear um sem o outro tranca o app."""
    ts = API_TS.read_text(encoding="utf-8")
    servidor = (RAIZ / "mangaba" / "server" / "app.py").read_text(encoding="utf-8")

    for cabecalho in ("X-Mangaba-Token", "X-Mangaba-Session"):
        assert cabecalho in ts, f"a GUI parou de enviar {cabecalho}"
        # O FastAPI/Starlette normaliza para minúsculas na leitura.
        assert cabecalho.lower() in servidor.lower(), (
            f"o servidor nao le mais {cabecalho} — toda requisicao da GUI vira 401"
        )


# --------------------------------------------------------------------------
# Empacotamento Windows: o lançador é a peça que substitui o PyInstaller.
# --------------------------------------------------------------------------
def test_lancador_windows_chama_o_entry_point_certo():
    """O lançador roda `python.exe -u server_entry.py`; o entry point precisa
    existir e apontar para o main() real."""
    lancador = (RAIZ / "packaging" / "win_launcher.c").read_text(encoding="utf-8")
    assert "server_entry.py" in lancador
    assert "python.exe" in lancador

    entry = RAIZ / "packaging" / "server_entry.py"
    assert entry.exists()
    texto = entry.read_text(encoding="utf-8")
    assert "from mangaba.server.run import main" in texto
    assert "main()" in texto


def _codigo_sem_comentarios(fonte: str) -> str:
    """Remove comentários C.

    Necessário porque o lançador *documenta* o defeito do `_execv` em prosa —
    procurar o nome no arquivo inteiro acusaria a própria explicação."""
    sem_bloco = re.sub(r"/\*.*?\*/", " ", fonte, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", sem_bloco)


def test_lancador_usa_createprocess_e_nao_execv():
    """No Windows `_execv` nao substitui o processo: o CRT cria outro (com PID
    diferente) e encerra o atual, entao o Tauri fica com um handle de filho que
    morre no instante em que o sidecar sobe. Foi o bug da v0.1.10."""
    fonte = (RAIZ / "packaging" / "win_launcher.c").read_text(encoding="utf-8")
    codigo = _codigo_sem_comentarios(fonte)

    assert "CreateProcess" in codigo
    assert "_execv" not in codigo, (
        "_execv voltou ao lancador: o Tauri perde o processo do sidecar"
    )
    assert "WaitForSingleObject" in codigo, (
        "sem esperar o Python, o lancador sai na hora e o Tauri considera o "
        "sidecar morto"
    )


def test_lancador_marca_handles_como_herdaveis():
    """Sem HANDLE_FLAG_INHERIT o Python nasce com stdout/stderr invalidos e o
    uvicorn morre na primeira linha de log."""
    lancador = (RAIZ / "packaging" / "win_launcher.c").read_text(encoding="utf-8")
    assert "SetHandleInformation" in lancador
    assert "HANDLE_FLAG_INHERIT" in lancador
