#!/usr/bin/env python3
"""Verifica o instalador Windows antes de publicar.

O instalador é gerado por cross-compile a partir do macOS
(`packaging/build_windows_cross.sh`), então não há como executá-lo aqui. Estas
checagens são o substituto: cada uma existe porque a falta dela deixou passar um
build quebrado para os usuários.

  1. libstdc++ (v0.1.8) — o app nem abria: "libstdc++-6.dll não foi encontrado".
     Conferir que os ARQUIVOS estavam dentro do instalador não disse nada sobre
     DLLs penduradas. Agora toda importação de todo PE precisa resolver.
  2. ícone (v0.1.10) — trocar icons/icon.ico e rebuildar NÃO re-embute o ícone:
     o recurso fica em cache e o binário sai com o antigo. Só se via na barra de
     tarefas do Windows.
  3. sidecar incompleto — um arquivo faltando vira uma tela girando para sempre,
     sem mensagem nenhuma.

Uso:
    python3 tests/packaging/verificar_windows.py <instalador.exe> [--icone icons/icon.ico]

Requer o 7-Zip (`brew install sevenzip`) para abrir o payload do NSIS.
Sai com código 1 e uma lista de falhas quando algo não confere.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pe  # noqa: E402

# DLLs que todo Windows já tem. O que não casar aqui precisa vir dentro do
# instalador, senão o processo não inicia. Prefixos, comparados em minúsculas.
DLLS_DO_SISTEMA = (
    "kernel32", "kernelbase", "advapi32", "api-ms-win", "ext-ms-win", "ntdll",
    "user32", "gdi32", "shell32", "shlwapi", "ole32", "oleaut32", "ws2_32",
    "crypt32", "bcrypt", "ncrypt", "secur32", "version", "msvcrt", "rpcrt4",
    "comdlg32", "comctl32", "winmm", "iphlpapi", "dbghelp", "psapi", "userenv",
    "setupapi", "cfgmgr32", "imm32", "uxtheme", "dwmapi", "wintrust", "mswsock",
    "dnsapi", "netapi32", "powrprof", "winhttp", "wininet", "urlmon", "propsys",
    "d3d11", "dxgi", "dcomp", "opengl32", "glu32", "ucrtbase", "sechost",
    "combase", "bcryptprimitives", "cryptbase", "profapi", "avrt", "ksuser",
    "mf", "mfplat", "audioses", "winspool", "oleacc", "msimg32", "usp10",
    # Winsock legado (usado pelo plugin NSISdl do instalador), compressão CAB e
    # a API do Windows Installer — todas de fábrica, mas fáceis de esquecer.
    "wsock32", "ws2help", "cabinet", "msi", "mpr", "wtsapi32", "rasapi32",
    "gdiplus", "hid", "winsta", "credui", "shcore", "pdh", "wldap32", "normaliz",
)

# Arquivos sem os quais o app não funciona. O sidecar é o runtime embeddable do
# Windows: sem a stdlib (.zip), a DLL do interpretador ou o ._pth, o Python nem
# inicia — e o app fica em "Não conectado" para sempre.
ARQUIVOS_OBRIGATORIOS = (
    "mangaba-desktop.exe",
    "WebView2Loader.dll",
    "sidecar/mangaba-server.exe",
    "sidecar/python.exe",
    "sidecar/python311.dll",
    "sidecar/python311.zip",
    "sidecar/python311._pth",
    "sidecar/vcruntime140.dll",
    "sidecar/server_entry.py",
    "sidecar/Lib/site-packages/mangaba/server/run.py",
    "sidecar/Lib/site-packages/fastapi/__init__.py",
    "sidecar/Lib/site-packages/uvicorn/__init__.py",
    "sidecar/Lib/site-packages/aisuite/__init__.py",
)

MINIMO_MODULOS_MANGABA = 100


def _sete_zip() -> str:
    for nome in ("7zz", "7z", "7za"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    sys.exit("7-Zip nao encontrado. Instale com: brew install sevenzip")


def extrair(instalador: pathlib.Path, destino: pathlib.Path) -> None:
    subprocess.run(
        [_sete_zip(), "x", "-y", f"-o{destino}", str(instalador)],
        check=True, capture_output=True,
    )


def checar_arquivos(raiz: pathlib.Path) -> list[str]:
    falhas = []
    for rel in ARQUIVOS_OBRIGATORIOS:
        if not (raiz / rel).exists():
            falhas.append(f"arquivo obrigatorio ausente no instalador: {rel}")

    modulos = raiz / "sidecar" / "Lib" / "site-packages" / "mangaba"
    if modulos.is_dir():
        quantos = len(list(modulos.rglob("*.py")))
        if quantos < MINIMO_MODULOS_MANGABA:
            falhas.append(
                f"o pacote mangaba veio incompleto: {quantos} modulos "
                f"(esperado ao menos {MINIMO_MODULOS_MANGABA})"
            )
    return falhas


def checar_dlls(raiz: pathlib.Path) -> list[str]:
    """Toda DLL importada precisa ser do sistema ou estar dentro do instalador.

    Foi o que faltou na v0.1.8: o app dependia de libstdc++-6.dll, que não existe
    em Windows nenhum, e o instalador parecia completo."""
    disponiveis = {p.name.lower() for p in raiz.rglob("*") if p.is_file()}
    falhas = []
    for caminho in sorted(raiz.rglob("*")):
        if not caminho.is_file() or caminho.suffix.lower() not in (".exe", ".dll", ".pyd"):
            continue
        try:
            importadas = pe.dlls_importadas(caminho.read_bytes())
        except pe.PEInvalido:
            continue
        for dll in sorted(importadas):
            minusculo = dll.lower()
            if minusculo.startswith(DLLS_DO_SISTEMA):
                continue
            if minusculo in disponiveis:
                continue
            falhas.append(
                f"{caminho.relative_to(raiz)} depende de {dll}, que nao e do "
                f"Windows nem esta no instalador (o processo nao inicia)"
            )
    return falhas


def checar_subsistemas(raiz: pathlib.Path) -> list[str]:
    """O sidecar precisa ser console: um build "windowed" deixa stdout/stderr
    nulos e trava o log de inicializacao do uvicorn."""
    falhas = []
    esperado = {
        "mangaba-desktop.exe": (pe.SUBSISTEMA_GUI, "GUI"),
        "sidecar/mangaba-server.exe": (pe.SUBSISTEMA_CONSOLE, "console"),
    }
    for rel, (valor, rotulo) in esperado.items():
        caminho = raiz / rel
        if not caminho.exists():
            continue  # ausencia ja e reportada por checar_arquivos
        obtido = pe.subsistema(caminho.read_bytes())
        if obtido != valor:
            falhas.append(f"{rel} deveria ser {rotulo}, mas o subsistema PE e {obtido}")
    return falhas


def checar_pth(raiz: pathlib.Path) -> list[str]:
    """O runtime embeddable ignora site-packages por padrao; sem estas linhas o
    Python sobe sem enxergar nenhuma dependencia."""
    caminho = raiz / "sidecar" / "python311._pth"
    if not caminho.exists():
        return []
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    falhas = []
    for exigido in ("python311.zip", "Lib\\site-packages", "import site"):
        if exigido not in texto:
            falhas.append(f"python311._pth nao contem {exigido!r}")
    return falhas


def checar_icone(raiz: pathlib.Path, icone: pathlib.Path) -> list[str]:
    """Compara as imagens do .ico com os bytes do .exe.

    O recurso de icone fica em cache: trocar icons/icon.ico e rebuildar mantem o
    icone antigo embutido, e isso so aparece na barra de tarefas do Windows
    (v0.1.10). Quando falha, `cargo clean -p mangaba-desktop` resolve."""
    exe = raiz / "mangaba-desktop.exe"
    if not exe.exists() or not icone.exists():
        return []
    dados_ico = icone.read_bytes()
    dados_exe = exe.read_bytes()
    _, _, quantos = struct.unpack_from("<HHH", dados_ico, 0)
    ausentes = []
    for i in range(quantos):
        base = 6 + i * 16
        largura, _, _, _, _, _, tam, offset = struct.unpack_from("<BBBBHHII", dados_ico, base)
        if dados_ico[offset : offset + tam] not in dados_exe:
            ausentes.append(largura or 256)
    if ausentes:
        return [
            "o icone embutido no .exe nao e o atual — faltam os tamanhos "
            f"{ausentes}. O recurso ficou em cache; rode: "
            "cargo clean -p mangaba-desktop --release --target x86_64-pc-windows-gnu"
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instalador", type=pathlib.Path)
    parser.add_argument(
        "--icone",
        type=pathlib.Path,
        default=pathlib.Path("surfaces/gui/src-tauri/icons/icon.ico"),
        help="icone de origem, para conferir o que foi embutido no .exe",
    )
    args = parser.parse_args()

    if not args.instalador.exists():
        return print(f"instalador nao encontrado: {args.instalador}") or 1

    with tempfile.TemporaryDirectory() as tmp:
        raiz = pathlib.Path(tmp)
        print(f"==> extraindo {args.instalador.name}")
        extrair(args.instalador, raiz)

        checagens = (
            ("arquivos do payload", lambda: checar_arquivos(raiz)),
            ("dependencias de DLL", lambda: checar_dlls(raiz)),
            ("subsistema dos executaveis", lambda: checar_subsistemas(raiz)),
            ("python311._pth", lambda: checar_pth(raiz)),
            ("icone embutido", lambda: checar_icone(raiz, args.icone)),
        )

        todas: list[str] = []
        for nome, executar in checagens:
            falhas = executar()
            print(f"  {'FALHOU' if falhas else 'ok    '}  {nome}")
            todas.extend(falhas)

    if todas:
        print("\nFALHAS:")
        for f in todas:
            print(f"  - {f}")
        print(f"\n{len(todas)} problema(s). NAO publique este instalador.")
        return 1

    print("\nTodas as checagens passaram.")
    print("Lembrete: isto verifica o ARTEFATO, nao que o app funcione em Windows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
