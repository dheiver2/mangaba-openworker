#!/usr/bin/env python3
"""Verifica o Mangaba.app antes de publicar o .dmg.

Espelha tests/packaging/verificar_windows.py. Cada checagem existe porque a
falta dela deixou passar um build quebrado:

  1. assinatura (v0.1.8) — o build do Tauri sem identidade Apple sai apenas
     "linker-signed": cobre o Mach-O mas NÃO sela os Resources. O `spctl`
     acusava "code has no resources but signature indicates they must be
     present" e o app não abria. É diferente de "não assinado", que é normal
     num build ad-hoc — por isso a checagem olha os Sealed Resources, não a
     mera existência de assinatura.
  2. sidecar — sem ele o app abre e fica em "Não conectado" para sempre.
  3. ícone — o mesmo cache de recurso que mordeu no Windows.

Uso:
    python3 tests/packaging/verificar_macos.py <caminho/Mangaba.app>

Sai com código 1 e uma lista de falhas quando algo não confere.
"""

from __future__ import annotations

import argparse
import pathlib
import plistlib
import subprocess
import sys

# O sidecar do macOS é um bundle onedir do PyInstaller: o executável mais a
# pasta _internal com o interpretador e as dependências.
ARQUIVOS_OBRIGATORIOS = (
    "Contents/MacOS/mangaba-desktop",
    "Contents/Resources/sidecar/mangaba-server",
    "Contents/Resources/icon.icns",
    "Contents/Info.plist",
)


def _rodar(comando: list[str]) -> tuple[int, str]:
    proc = subprocess.run(comando, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def checar_arquivos(app: pathlib.Path) -> list[str]:
    falhas = []
    for rel in ARQUIVOS_OBRIGATORIOS:
        if not (app / rel).exists():
            falhas.append(f"ausente no bundle: {rel}")

    sidecar = app / "Contents/Resources/sidecar/mangaba-server"
    if sidecar.exists() and not sidecar.stat().st_mode & 0o111:
        falhas.append("sidecar/mangaba-server nao esta executavel")
    return falhas


def checar_assinatura(app: pathlib.Path) -> list[str]:
    """Exige Sealed Resources.

    Um build ad-hoc é aceitável (não temos certificado Apple), mas ele precisa
    selar os Resources. Sem isso a assinatura fica estruturalmente quebrada e o
    Gatekeeper recusa o app — foi a v0.1.8. `codesign --force --deep --sign -`
    corrige."""
    codigo, saida = _rodar(["codesign", "-dv", str(app)])
    if codigo != 0:
        return [f"o bundle nao esta assinado nem ad-hoc: {saida.strip().splitlines()[:1]}"]

    if "Sealed Resources" not in saida:
        return [
            "assinatura sem Sealed Resources (build 'linker-signed': cobre o "
            "Mach-O mas nao os Resources). O Gatekeeper recusa o app. Rode: "
            "codesign --force --deep --sign - Mangaba.app"
        ]

    codigo, saida_verify = _rodar(["codesign", "--verify", "--deep", str(app)])
    if codigo != 0:
        return [f"codesign --verify --deep falhou: {saida_verify.strip()}"]
    return []


def checar_arquitetura(app: pathlib.Path) -> list[str]:
    binario = app / "Contents/MacOS/mangaba-desktop"
    if not binario.exists():
        return []
    codigo, saida = _rodar(["file", str(binario)])
    if codigo == 0 and "arm64" not in saida and "x86_64" not in saida:
        return [f"arquitetura inesperada no executavel: {saida.strip()}"]
    return []


def checar_versao(app: pathlib.Path, esperada: str | None) -> list[str]:
    """Um .dmg com versao defasada e a forma mais silenciosa de publicar o
    binario errado."""
    if not esperada:
        return []
    plist = app / "Contents/Info.plist"
    if not plist.exists():
        return []
    dados = plistlib.loads(plist.read_bytes())
    obtida = dados.get("CFBundleShortVersionString")
    if obtida != esperada:
        return [f"versao do bundle e {obtida!r}, esperada {esperada!r}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=pathlib.Path, help="caminho do Mangaba.app")
    parser.add_argument("--versao", help="versao esperada (ex.: 0.1.11)")
    args = parser.parse_args()

    if not args.app.exists():
        print(f"bundle nao encontrado: {args.app}")
        return 1

    checagens = (
        ("arquivos do bundle", lambda: checar_arquivos(args.app)),
        ("assinatura e Sealed Resources", lambda: checar_assinatura(args.app)),
        ("arquitetura", lambda: checar_arquitetura(args.app)),
        ("versao", lambda: checar_versao(args.app, args.versao)),
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
        print(f"\n{len(todas)} problema(s). NAO publique este .dmg.")
        return 1

    print("\nTodas as checagens passaram.")
    print("Lembrete: isto verifica o ARTEFATO, nao que o app funcione.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
