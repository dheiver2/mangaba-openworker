#!/usr/bin/env python3
"""Testa o app JÁ INSTALADO, de ponta a ponta: sobe o sidecar e usa a API.

É o teste que faltava. A suíte do projeto roda o servidor em processo
(`TestClient` + `create_app`), então prova que o CÓDIGO funciona — e todos os
defeitos desta sessão viveram no vão seguinte: código certo, empacotamento ou
lançamento quebrado. Ninguém exercitava o binário que o usuário realmente
executa.

Aqui o sidecar instalado é iniciado como um processo de verdade, numa porta
livre e com estado isolado, e a API é consumida como o app faz. Se o servidor
não subir, a saída dele é impressa — que é o diagnóstico que faltava quando o
app fica em "Não conectado".

Roda em macOS e Windows. No Windows ele também serve como ferramenta de suporte:
o usuário roda e manda a saída, em vez de caçar arquivo de log.

Uso:
    python3 tests/packaging/testar_app_instalado.py
    python3 tests/packaging/testar_app_instalado.py --app "C:\\Users\\eu\\AppData\\Local\\Mangaba"

Sai com 0 se o app instalado responde, 1 caso contrário.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

TOKEN = "teste-local-do-verificador"


def locais_provaveis() -> list[pathlib.Path]:
    """Onde cada instalador deixa o app."""
    if sys.platform == "darwin":
        return [
            pathlib.Path("/Applications/Mangaba.app"),
            pathlib.Path.home() / "Applications" / "Mangaba.app",
        ]
    if sys.platform == "win32":
        candidatos = []
        for var in ("LOCALAPPDATA", "PROGRAMFILES"):
            base = os.environ.get(var)
            if base:
                candidatos.append(pathlib.Path(base) / "Mangaba")
        return candidatos
    return []


def achar_sidecar(raiz: pathlib.Path) -> pathlib.Path | None:
    """O executável do sidecar dentro do app instalado.

    Os dois empacotamentos põem em lugares diferentes: no macOS dentro de
    Contents/Resources, no Windows ao lado do .exe."""
    nomes = ["mangaba-server.exe"] if sys.platform == "win32" else ["mangaba-server"]
    candidatos = [
        raiz / "Contents" / "Resources" / "sidecar",
        raiz / "sidecar",
    ]
    for pasta in candidatos:
        for nome in nomes:
            caminho = pasta / nome
            if caminho.exists():
                return caminho
    return None


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def consultar(porta: int, rota: str, timeout: float = 3.0):
    req = urllib.request.Request(
        f"http://127.0.0.1:{porta}{rota}", headers={"X-Mangaba-Token": TOKEN}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def testar(sidecar: pathlib.Path, espera_s: int) -> list[str]:
    porta = porta_livre()
    falhas: list[str] = []

    with tempfile.TemporaryDirectory() as estado:
        ambiente = dict(os.environ)
        # Estado isolado: nunca tocar na senha, conversas e segredos reais de
        # quem está rodando o teste.
        ambiente["MANGABA_STATE_DIR"] = estado
        ambiente["MANGABA_API_TOKEN"] = TOKEN
        ambiente.pop("MANGABA_EXIT_WITH_PARENT", None)

        print(f"  iniciando {sidecar.name} na porta {porta}")
        proc = subprocess.Popen(
            [str(sidecar), "--host", "127.0.0.1", "--port", str(porta)],
            env=ambiente,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )

        try:
            deadline = time.time() + espera_s
            respondeu = False
            while time.time() < deadline:
                if proc.poll() is not None:
                    saida = proc.stdout.read() if proc.stdout else ""
                    falhas.append(
                        f"o sidecar encerrou sozinho (codigo {proc.returncode}) antes de "
                        f"responder.\n--- saida do servidor ---\n{saida[-3000:]}"
                    )
                    return falhas
                try:
                    consultar(porta, "/v1/health")
                    respondeu = True
                    break
                except (urllib.error.URLError, OSError, TimeoutError):
                    time.sleep(0.5)

            if not respondeu:
                proc.terminate()
                saida = ""
                try:
                    saida = proc.communicate(timeout=5)[0] or ""
                except subprocess.TimeoutExpired:
                    proc.kill()
                falhas.append(
                    f"o sidecar nao respondeu em {espera_s}s (o app ficaria em "
                    f"'Nao conectado').\n--- saida do servidor ---\n{saida[-3000:]}"
                )
                return falhas

            print("  ok    /v1/health respondeu")

            # As funcionalidades que o usuario ve primeiro: escolher provedor e
            # colar a chave. Se isto falha, a tela de configuracao fica vazia.
            try:
                provedores = consultar(porta, "/v1/providers")
            except Exception as exc:
                falhas.append(f"/v1/providers falhou: {exc!r}")
                return falhas

            if not provedores:
                falhas.append("/v1/providers respondeu vazio — nenhum provedor para configurar")
            else:
                nomes = [p.get("name") for p in provedores]
                print(f"  ok    /v1/providers -> {len(provedores)} provedores: {', '.join(nomes[:6])}…")
                for obrigatorio in ("openai", "anthropic", "mangaba"):
                    if obrigatorio not in nomes:
                        falhas.append(f"provedor esperado ausente: {obrigatorio}")

                # Cada provedor precisa declarar os campos da chave, senão a
                # tela abre sem onde digitar.
                sem_campos = [
                    p.get("name") for p in provedores
                    if p.get("needs_key") and not p.get("fields")
                ]
                if sem_campos:
                    falhas.append(
                        f"provedores que pedem chave mas nao declaram campos: {sem_campos}"
                    )
                else:
                    print("  ok    todos os provedores declaram os campos da chave")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    return falhas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=pathlib.Path, help="raiz do app instalado")
    parser.add_argument("--espera", type=int, default=60,
                        help="segundos de espera pelo sidecar (padrao 60)")
    args = parser.parse_args()

    print(f"Mangaba — teste do app instalado ({platform.platform()})")

    raizes = [args.app] if args.app else locais_provaveis()
    sidecar = None
    for raiz in raizes:
        if raiz and raiz.exists():
            sidecar = achar_sidecar(raiz)
            if sidecar:
                print(f"  app encontrado: {raiz}")
                break

    if not sidecar:
        print("\nFALHA: nao encontrei o app instalado.")
        print("Procurei em:")
        for r in raizes:
            print(f"  - {r}")
        print("\nInforme o caminho com --app.")
        return 1

    falhas = testar(sidecar, args.espera)

    if falhas:
        print("\nFALHAS:")
        for f in falhas:
            print(f"  - {f}")
        return 1

    print("\nO app instalado funciona: o sidecar sobe e a API responde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
