"""Exercita os ramos de código que só rodam no Windows.

Este projeto é desenvolvido e testado no macOS, então tudo sob
`if sys.platform == "win32"` nunca é executado pela suíte — os testes existentes
só checam a plataforma e saem. Esse código chega intacto ao usuário Windows sem
nunca ter rodado uma vez aqui.

O que importa aqui não é cobertura por cobertura: um erro nesses ramos aparece
como o app abrindo e ficando em "Não conectado", sem mensagem nenhuma. Os
comentários do próprio código descrevem dois defeitos que já morderam
(`OpenProcess` truncado por falta de `restype`, e ACL sem flags de herança
derrubando o sqlite) — o que quer dizer que este caminho quebra em silêncio.

A plataforma é simulada com monkeypatch; as chamadas ao SO viram dublês, e o que
se verifica são os argumentos e as decisões.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest


# --------------------------------------------------------------------------
# state_dir(): precisa bater com o que o shell Tauri usa (src-tauri/src/lib.rs
# resolve %APPDATA%\mangaba). Divergir aqui faz servidor e GUI lerem estados
# diferentes — senha num lugar, conversas noutro.
# --------------------------------------------------------------------------
def test_state_dir_no_windows_usa_appdata(monkeypatch):
    from mangaba import secrets as mod

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("MANGABA_STATE_DIR", raising=False)
    monkeypatch.setenv("APPDATA", r"C:\Users\Joao\AppData\Roaming")

    assert mod.state_dir() == Path(r"C:\Users\Joao\AppData\Roaming") / "mangaba"


def test_state_dir_override_vence_no_windows(monkeypatch, tmp_path):
    """O sidecar e os testes dependem do override em qualquer plataforma."""
    from mangaba import secrets as mod

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\Joao\AppData\Roaming")
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))

    assert mod.state_dir() == tmp_path


def test_state_dir_sem_appdata_cai_no_home(monkeypatch):
    """APPDATA ausente é raro, mas não pode virar exceção na inicialização."""
    from mangaba import secrets as mod

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("MANGABA_STATE_DIR", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    assert mod.state_dir() == Path.home() / ".config" / "mangaba"


# --------------------------------------------------------------------------
# _restrict_to_user(): no Windows usa icacls, porque os bits POSIX não existem
# (um chmod 0600 lá é no-op silencioso e o arquivo herda ACLs amplas).
# --------------------------------------------------------------------------
def _capturar_icacls(monkeypatch) -> list[list[str]]:
    from mangaba import secrets as mod

    chamadas: list[list[str]] = []

    def falso_run(args, **kwargs):
        chamadas.append(list(args))
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod.subprocess, "run", falso_run)
    monkeypatch.setenv("USERNAME", "Joao")
    monkeypatch.setenv("USERDOMAIN", "MEUPC")
    return chamadas


def test_diretorio_ganha_ace_herdavel(monkeypatch, tmp_path):
    """(OI)(CI) não é detalhe cosmético.

    Sem essas flags, `/inheritance:r` deixa o diretório com um ACE não-herdável
    e qualquer arquivo criado dentro nasce com DACL vazia — o sqlite falha com
    "unable to open database file" e o servidor morre ao subir. É o cenário que
    o comentário do código descreve."""
    from mangaba import secrets as mod

    chamadas = _capturar_icacls(monkeypatch)
    mod._restrict_to_user(tmp_path, is_dir=True)

    assert len(chamadas) == 1
    args = chamadas[0]
    assert args[0] == "icacls"
    assert "/inheritance:r" in args
    concessao = args[args.index("/grant:r") + 1]
    assert concessao == r"MEUPC\Joao:(OI)(CI)F", (
        "diretório sem herança: arquivos criados dentro ficam sem permissão "
        "e o sqlite não abre"
    )


def test_arquivo_ganha_ace_simples(monkeypatch, tmp_path):
    from mangaba import secrets as mod

    chamadas = _capturar_icacls(monkeypatch)
    alvo = tmp_path / "segredos.json"
    alvo.write_text("{}")
    mod._restrict_to_user(alvo, is_dir=False)

    concessao = chamadas[0][chamadas[0].index("/grant:r") + 1]
    assert concessao == r"MEUPC\Joao:F"


def test_sem_dominio_usa_so_o_usuario(monkeypatch, tmp_path):
    from mangaba import secrets as mod

    chamadas = _capturar_icacls(monkeypatch)
    monkeypatch.delenv("USERDOMAIN", raising=False)
    mod._restrict_to_user(tmp_path, is_dir=True)

    concessao = chamadas[0][chamadas[0].index("/grant:r") + 1]
    assert concessao == r"Joao:(OI)(CI)F"


def test_sem_username_nao_explode(monkeypatch, tmp_path):
    """Melhor não restringir do que impedir o usuário de salvar uma chave."""
    from mangaba import secrets as mod

    chamadas = _capturar_icacls(monkeypatch)
    monkeypatch.delenv("USERNAME", raising=False)
    mod._restrict_to_user(tmp_path, is_dir=True)

    assert chamadas == []


def test_falha_do_icacls_nao_impede_salvar(monkeypatch, tmp_path):
    """icacls indisponível não pode derrubar a gravação do segredo."""
    from mangaba import secrets as mod

    def run_que_explode(args, **kwargs):
        raise OSError("icacls não encontrado")

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod.subprocess, "run", run_que_explode)
    monkeypatch.setenv("USERNAME", "Joao")

    mod._restrict_to_user(tmp_path, is_dir=True)  # não deve levantar


# --------------------------------------------------------------------------
# _watch_parent_windows(): o sidecar se encerra quando o app fecha. Se este
# código decidir errado, ele se mata logo após subir — que é exatamente o
# sintoma "abre e fica em Não conectado".
# --------------------------------------------------------------------------
class _FalsoKernel32:
    """Dublê de kernel32 que registra o que foi declarado e chamado."""

    def __init__(self, handle=0x1234, resultado_wait=0):
        self._handle = handle
        self._resultado_wait = resultado_wait
        self.args_openprocess = None
        self.OpenProcess = self._fazer_openprocess()
        self.WaitForSingleObject = self._fazer_wait()

    def _fazer_openprocess(self):
        dono = self

        class _Func:
            restype = None
            argtypes = None

            def __call__(self, acesso, herdar, pid):
                dono.args_openprocess = (acesso, herdar, pid)
                return dono._handle

        return _Func()

    def _fazer_wait(self):
        dono = self

        class _Func:
            restype = None
            argtypes = None

            def __call__(self, handle, timeout):
                return dono._resultado_wait

        return _Func()


def _rodar_watch(monkeypatch, kernel32, pid_pai=4321):
    """Chama _watch_parent_windows com kernel32 dublê e thread síncrona."""
    from mangaba.server import run as mod

    saidas: list[int] = []
    monkeypatch.setattr(mod.os, "_exit", lambda codigo: saidas.append(codigo))

    import ctypes

    monkeypatch.setattr(ctypes, "WinDLL", lambda nome, **kw: kernel32, raising=False)

    # Thread que executa na hora, para o teste observar o efeito sem corrida.
    import threading

    class ThreadImediata:
        def __init__(self, target, daemon=None):
            self._target = target
            self.daemon = daemon

        def start(self):
            self._target()

    monkeypatch.setattr(threading, "Thread", ThreadImediata)
    mod._watch_parent_windows(pid_pai)
    return saidas


def test_watch_encerra_quando_o_pai_morre(monkeypatch):
    """WAIT_OBJECT_0 significa que o processo pai realmente terminou."""
    kernel32 = _FalsoKernel32(handle=0x1234, resultado_wait=0)  # WAIT_OBJECT_0
    saidas = _rodar_watch(monkeypatch, kernel32)
    assert saidas == [0]


def test_watch_ignora_wait_failed(monkeypatch):
    """WAIT_FAILED (0xFFFFFFFF) vem de handle ruim, não de pai morto.

    Tratar isso como "o pai morreu" mataria um servidor saudável poucos
    segundos após o start — o comentário do código diz que foi exatamente esse
    o congelamento observado."""
    kernel32 = _FalsoKernel32(handle=0x1234, resultado_wait=0xFFFFFFFF)
    saidas = _rodar_watch(monkeypatch, kernel32)
    assert saidas == [], "servidor saudável não pode ser encerrado por WAIT_FAILED"


def test_watch_desiste_se_openprocess_falha(monkeypatch):
    """Handle nulo: sem watch, sobra o kill do Tauri como limpeza."""
    kernel32 = _FalsoKernel32(handle=0, resultado_wait=0)
    saidas = _rodar_watch(monkeypatch, kernel32)
    assert saidas == []


def test_watch_declara_tipos_do_ctypes(monkeypatch):
    """OpenProcess devolve um HANDLE de 64 bits.

    Sem `restype`, o ctypes assume int de 32 bits e trunca o handle para lixo —
    o WaitForSingleObject recebe um handle inválido e o watch nunca funciona.
    O código traz isso como comentário; aqui vira teste."""
    import ctypes
    from ctypes import wintypes

    kernel32 = _FalsoKernel32()
    _rodar_watch(monkeypatch, kernel32)

    assert kernel32.OpenProcess.restype is wintypes.HANDLE
    assert kernel32.OpenProcess.argtypes == [
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
    ]
    assert kernel32.WaitForSingleObject.restype is wintypes.DWORD


def test_watch_pede_apenas_synchronize(monkeypatch):
    """SYNCHRONIZE (0x00100000) é o mínimo para esperar no handle.

    Pedir mais acesso do que o necessário pode fazer o OpenProcess falhar por
    permissão — e aí o sidecar deixa de se encerrar junto com o app."""
    kernel32 = _FalsoKernel32()
    _rodar_watch(monkeypatch, kernel32, pid_pai=4321)

    acesso, herdar, pid = kernel32.args_openprocess
    assert acesso == 0x0010_0000
    assert herdar is False
    assert pid == 4321


# --------------------------------------------------------------------------
# Shell: no Windows o comando roda via PowerShell e o kill é em árvore.
# --------------------------------------------------------------------------
def test_shell_windows_usa_powershell_e_novo_grupo(monkeypatch):
    """/bin/bash não existe no Windows; e sem um grupo de processo próprio o
    cancelamento não alcança os filhos do comando."""
    from mangaba.tools import shell as mod

    capturado: dict = {}

    class FalsoPopen:
        def __init__(self, argv, **kwargs):
            capturado["argv"] = argv
            capturado["kwargs"] = kwargs
            self.pid = 999
            self.stdin = None
            # A tarefa sobe uma thread que lê stdout; um objeto que devolve EOF
            # na hora deixa essa thread terminar em silêncio.
            self.stdout = io.StringIO("")

        def poll(self):
            return None

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod.subprocess, "Popen", FalsoPopen)
    monkeypatch.setattr(
        mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False
    )

    try:
        mod._BackgroundTask("t1", "echo oi", cwd=".", env={})
    except Exception as exc:  # pragma: no cover - falha real do teste
        pytest.fail(f"criacao da tarefa falhou no ramo Windows: {exc!r}")

    assert capturado["argv"][0] == "powershell.exe"
    assert "-NoProfile" in capturado["argv"]
    assert capturado["argv"][-1] == "echo oi"
    assert capturado["kwargs"].get("creationflags") == 0x200
    assert "start_new_session" not in capturado["kwargs"], (
        "start_new_session é POSIX; no Windows o Popen rejeita"
    )


# --- paridade Windows/macOS: o que o MODELO sabe da plataforma -------------------------
# A implementação já era OS-nativa; o que faltava era isso chegar ao modelo. Sem os testes
# abaixo, a descrição volta a ser escrita "para bash" sem ninguém perceber no Mac.


def test_run_shell_declara_powershell_no_windows(monkeypatch):
    """No Windows a descrição da tool precisa dizer PowerShell, não silêncio.

    Calada, o modelo assume bash e escreve `export`/`&&`/`grep` num PowerShell — no macOS
    ele acerta por padrão e no Windows erra por padrão, uma diferença real de capacidade.
    """
    import importlib

    import mangaba.tools.shell as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    recarregado = importlib.reload(mod)
    try:
        descricao = recarregado._RUN_SHELL_SCHEMA["function"]["description"]
        assert "PowerShell" in descricao
        assert "bash" not in descricao.lower()
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_run_shell_declara_bash_no_posix():
    import mangaba.tools.shell as mod

    descricao = mod._RUN_SHELL_SCHEMA["function"]["description"]
    assert "bash" in descricao
    assert "PowerShell" not in descricao


def test_environment_context_no_windows_nao_fala_de_macos(monkeypatch, tmp_path):
    """O bloco justificava a regra de pastas com o prompt de permissão do macOS."""
    import mangaba.environment as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    texto = mod.environment_context(tmp_path)
    assert "run_shell runs PowerShell" in texto
    assert "On macOS" not in texto
    assert "find/ls/grep" not in texto


def test_environment_context_no_mac_mantem_o_texto_de_sempre(monkeypatch, tmp_path):
    import mangaba.environment as mod

    monkeypatch.setattr(mod.sys, "platform", "darwin")
    texto = mod.environment_context(tmp_path)
    assert "run_shell runs bash" in texto
    assert "On macOS" in texto


def test_ocr_reconhece_o_sidecar_embeddable_do_windows(monkeypatch, tmp_path):
    """O sidecar do Windows é o Python embeddable, não PyInstaller: `sys.frozen` é falso.

    Detectando só o congelado, quem instalou pelo .exe recebia "rode pip install" — e não
    existe pip nenhum dentro do embeddable.
    """
    import mangaba.ocr as mod

    (tmp_path / "python311._pth").write_text("", encoding="utf-8")
    falso_exe = tmp_path / "python.exe"
    falso_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod_sys := __import__("sys"), "executable", str(falso_exe))
    monkeypatch.delattr(mod_sys, "frozen", raising=False)

    assert mod.empacotado() is True
    assert "pip install" not in mod.como_instalar()


def test_ocr_fora_de_bundle_ainda_sugere_pip(monkeypatch, tmp_path):
    """Instalação por código-fonte continua recebendo a instrução que de fato funciona."""
    import sys as mod_sys

    import mangaba.ocr as mod

    falso_exe = tmp_path / "python"
    falso_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod_sys, "executable", str(falso_exe))
    monkeypatch.delattr(mod_sys, "frozen", raising=False)

    assert mod.empacotado() is False
    assert "pip install" in mod.como_instalar()
