#!/usr/bin/env python3
"""Confere que o sidecar empacotado tem todas as dependências do `mangaba`.

O sidecar do Windows não é montado por um instalador de pacotes: as wheels
`win_amd64` são baixadas e extraídas na mão (`pip install --target` recusa
wheels de outra plataforma). Isso significa que NADA valida o fecho de
dependências — se um pacote faltar, só se descobre quando o servidor morre no
import, em Windows, e o app fica em "Não conectado" sem dizer por quê.

Duas checagens:

  --site-packages  compara os imports de terceiros do `mangaba` com o que existe
                   na árvore empacotada. Roda em qualquer plataforma, inclusive
                   contra o sidecar do Windows a partir do macOS.

  --venv           sobe o servidor de verdade num ambiente que tem SOMENTE essas
                   dependências e bate num endpoint. É a prova de que o conjunto
                   é suficiente — o teste estático não pega import transitivo.

Uso:
    python3 tests/packaging/verificar_deps_sidecar.py --site-packages <dir>
    python3 tests/packaging/verificar_deps_sidecar.py --venv <python-do-venv>
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# Extras opcionais: importados dentro de funções, nunca no topo de um módulo que
# o servidor carrega. Faltar é aceitável — o conector correspondente fica
# indisponível, mas o app sobe.
OPCIONAIS = {"playwright", "slack_bolt", "slack_sdk", "telegram"}

# Nome do import -> diretório em site-packages, quando diferem.
APELIDOS = {"yaml": "yaml", "google": "google"}


def imports_de_terceiros(raiz_mangaba: pathlib.Path) -> set[str]:
    stdlib = set(sys.stdlib_module_names)
    topo: set[str] = set()
    for arquivo in raiz_mangaba.rglob("*.py"):
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                for alias in no.names:
                    topo.add(alias.name.split(".")[0])
            elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                topo.add(no.module.split(".")[0])
    return {m for m in topo if m not in stdlib and m not in ("mangaba", "__future__")}


def checar_site_packages(site_packages: pathlib.Path) -> list[str]:
    mangaba = site_packages / "mangaba"
    if not mangaba.is_dir():
        return [f"o pacote mangaba nao esta em {site_packages}"]

    presentes = {p.name.lower() for p in site_packages.iterdir()}
    faltando = []
    for modulo in sorted(imports_de_terceiros(mangaba)):
        if modulo in OPCIONAIS:
            continue
        nome = APELIDOS.get(modulo, modulo)
        achou = (
            (site_packages / nome).exists()
            or (site_packages / f"{nome}.py").exists()
            or nome.lower() in presentes
        )
        if not achou:
            faltando.append(
                f"{modulo} e importado pelo mangaba mas nao esta no sidecar "
                f"(o servidor morre no import e o app fica em 'Nao conectado')"
            )

    # Dependencias CONDICIONAIS de Windows que a varredura de imports acima nao enxerga:
    # ela roda em macOS e os ramos `sys_platform == 'win32'` dos pacotes nunca executam
    # aqui. O caso real: mcp declara `pywin32; sys_platform == 'win32'`, o pip descarta o
    # marcador em download cross-platform, e no Windows `import mcp` morria com
    # ModuleNotFoundError: pywintypes ja no boot do servidor (enviado na v0.1.12/13,
    # pego rodando o payload sob Wine). Checagem estatica: presenca do gatilho exige a
    # presenca do satelite.
    condicionais_win32 = {"mcp": ["pywin32_system32", "win32"]}
    for gatilho, satelites in condicionais_win32.items():
        if gatilho in presentes:
            for s in satelites:
                if s.lower() not in presentes:
                    faltando.append(
                        f"{gatilho} esta no sidecar mas {s} (pywin32) nao — no Windows "
                        f"`import {gatilho}` importa pywintypes e o servidor morre no boot"
                    )
    return faltando


def checar_venv(python: pathlib.Path, repo: pathlib.Path) -> list[str]:
    """Sobe o servidor com SOMENTE as dependências empacotadas e bate nele.

    O teste estático acima não enxerga import transitivo (um pacote que importa
    outro que não veio). Isto enxerga."""
    entry = repo / "packaging" / "server_entry.py"
    if not entry.exists():
        return [f"server_entry.py nao encontrado em {entry}"]

    porta = 8817
    with tempfile.TemporaryDirectory() as estado:
        ambiente = {
            "PATH": "/usr/bin:/bin",
            "MANGABA_STATE_DIR": estado,
            "MANGABA_API_TOKEN": "teste",
            "PYTHONPATH": str(repo),
        }
        proc = subprocess.Popen(
            [str(python), str(entry), "--host", "127.0.0.1", "--port", str(porta)],
            env=ambiente, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            for _ in range(40):  # até ~20s
                if proc.poll() is not None:
                    saida = proc.stdout.read() if proc.stdout else ""
                    return [f"o servidor morreu ao subir:\n{saida[-2000:]}"]
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{porta}/v1/providers",
                        headers={"X-Mangaba-Token": "teste"},
                    )
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        provedores = json.load(resp)
                    if not provedores:
                        return ["/v1/providers respondeu vazio"]
                    print(f"  ({len(provedores)} provedores listados)")
                    return []
                except (urllib.error.URLError, OSError, TimeoutError):
                    time.sleep(0.5)
            return ["o servidor nao respondeu em 20s"]
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-packages", type=pathlib.Path)
    parser.add_argument("--venv", type=pathlib.Path, help="python do venv de teste")
    args = parser.parse_args()

    if not args.site_packages and not args.venv:
        parser.error("informe --site-packages e/ou --venv")

    repo = pathlib.Path(__file__).resolve().parents[2]
    falhas: list[str] = []

    if args.site_packages:
        resultado = checar_site_packages(args.site_packages)
        print(f"  {'FALHOU' if resultado else 'ok    '}  dependencias no sidecar")
        falhas.extend(resultado)

    if args.venv:
        resultado = checar_venv(args.venv, repo)
        print(f"  {'FALHOU' if resultado else 'ok    '}  servidor sobe com o conjunto empacotado")
        falhas.extend(resultado)

    if falhas:
        print("\nFALHAS:")
        for f in falhas:
            print(f"  - {f}")
        return 1
    print("\nTodas as checagens passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
