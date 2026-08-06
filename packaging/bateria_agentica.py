#!/usr/bin/env python3
"""Bateria agêntica — a régua das notas dos provedores, versionada e rodável por comando.

Por que ela existe como arquivo do repositório e não como script solto: as notas dos
provedores Mangaba passaram a guiar decisões (o que otimizar, o que publicar), e uma régua
que vive em /tmp muda de mão em mão sem ninguém perceber. Aqui ela é fixa, comparável entre
execuções e crítica de mudanças — a fase A.2 do plano de latência foi REJEITADA por esta
bateria, e a A.1 aceita, ambas com números.

O que ela mede: tarefas de ponta a ponta pelo engine REAL (SessionManager → TurnEngine →
provedor), pontuadas por VERIFICAÇÃO do resultado no disco — nunca pela auto-declaração do
modelo de que terminou. Cada tarefa roda numa sessão nova.

As 12 tarefas cobrem as classes de falha vistas ao vivo:
- aritmética sobre dados (a tarefa que o modelo local mais erra — soma de cabeça);
- multi-passo e multi-arquivo;
- shell;
- extração de fato de texto (incluindo distinguir o fato certo do parecido);
- recuperação de erro (arquivo inexistente → seguir instrução alternativa);
- edição de arquivo existente sem destruir o resto;
- verificação do próprio resultado.

Uso:
    .venv/bin/python packaging/bateria_agentica.py <modelo> [agente] [--execucoes N]
    .venv/bin/python packaging/bateria_agentica.py local:qwen3-4b negocio --execucoes 3
    .venv/bin/python packaging/bateria_agentica.py mangaba:auto cowork
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time
from pathlib import Path


def preparar(ws: Path) -> None:
    (ws / "vendas.csv").write_text(
        "produto,qtd,preco\nfibra,10,120.50\nlink,3,890.00\nip,7,45.25\n",
        encoding="utf-8",
    )
    (ws / "notas.txt").write_text(
        "Reuniao 12/03: cliente pediu desconto de 10%.\n"
        "Reuniao 20/03: fechado em 5%.\n",
        encoding="utf-8",
    )
    (ws / "clientes.csv").write_text(
        "nome,cidade\nAna,Maceio\nBruno,Recife\nCarla,Maceio\n", encoding="utf-8"
    )
    (ws / "config.ini").write_text(
        "[app]\nporta=8080\nmodo=teste\n", encoding="utf-8"
    )


def _tem(ws: Path, arquivo: str, *trechos: str) -> bool:
    alvo = ws / arquivo
    if not alvo.exists():
        return False
    texto = alvo.read_text(encoding="utf-8", errors="replace")
    normalizado = texto.replace(".", "").replace(",", "")
    return all(t in texto or t in normalizado for t in trechos)


# (nome, prompt, verificador). Total de vendas.csv: 10*120.50 + 3*890.00 + 7*45.25 = 4191.75
TAREFAS = [
    (
        "aritmetica",
        "Leia vendas.csv e escreva resumo.txt contendo apenas a linha "
        "'TOTAL=<soma de qtd*preco>' com duas casas decimais.",
        lambda ws: _tem(ws, "resumo.txt", "419175"),
    ),
    (
        "aritmetica-parcial",
        "Leia vendas.csv e escreva fibra.txt contendo apenas o faturamento do produto "
        "fibra (qtd*preco), com duas casas decimais.",
        lambda ws: _tem(ws, "fibra.txt", "120500"),
    ),
    (
        "multi-passo",
        "Liste os arquivos da pasta e crie inventario.md com uma lista markdown dos nomes "
        "de todos os arquivos .csv e .txt que encontrar.",
        lambda ws: _tem(ws, "inventario.md", "vendas.csv", "notas.txt", "clientes.csv"),
    ),
    (
        "shell",
        "Use o shell para contar quantas linhas tem notas.txt e grave só o número em "
        "linhas.txt.",
        lambda ws: _tem(ws, "linhas.txt", "2"),
    ),
    (
        "extrair-fato",
        "Leia notas.txt e escreva desconto.txt contendo apenas o percentual de desconto "
        "que foi FECHADO (só o número e o símbolo, ex.: 5%).",
        lambda ws: _tem(ws, "desconto.txt", "5%")
        and not _tem(ws, "desconto.txt", "10%"),
    ),
    (
        "filtrar-dados",
        "Leia clientes.csv e escreva maceio.txt com os nomes (um por linha) dos clientes "
        "de Maceio.",
        lambda ws: _tem(ws, "maceio.txt", "Ana", "Carla")
        and not _tem(ws, "maceio.txt", "Bruno"),
    ),
    (
        "editar-preservando",
        "No arquivo config.ini, mude o valor de porta para 9090 sem alterar mais nada.",
        lambda ws: _tem(ws, "config.ini", "porta=9090", "modo=teste"),
    ),
    (
        "recuperar-de-erro",
        "Leia o arquivo intencionalmente-inexistente.txt. Se ele não existir, escreva "
        "aviso.txt com exatamente a palavra AUSENTE.",
        lambda ws: _tem(ws, "aviso.txt", "AUSENTE"),
    ),
    (
        "multiarquivo",
        "Crie relatorio.md juntando: o número de clientes de clientes.csv e o desconto "
        "fechado de notas.txt, em duas linhas.",
        lambda ws: _tem(ws, "relatorio.md", "3", "5%"),
    ),
    (
        "transformar",
        "Converta clientes.csv em clientes.json — uma lista de objetos com as chaves "
        "nome e cidade.",
        lambda ws: _tem(ws, "clientes.json", "Ana", "Recife", "cidade"),
    ),
    (
        "contar-ocorrencias",
        "Conte quantas vezes a palavra 'Reuniao' aparece em notas.txt e grave só o número "
        "em reunioes.txt.",
        lambda ws: _tem(ws, "reunioes.txt", "2"),
    ),
    (
        "verificar-proprio-trabalho",
        "Escreva soma.txt com o resultado de 17*23+101. Depois confira o arquivo relendo-o "
        "e, se o valor estiver certo, acrescente a linha CONFERIDO.",
        lambda ws: _tem(ws, "soma.txt", "492", "CONFERIDO"),
    ),
]


async def _rodar_tarefa(manager, modelo: str, agente: str, indice: int, prompt: str):
    from mangaba.engine import ApprovalOutcome
    from mangaba.events import EventType

    async def aprovar(_req):
        return ApprovalOutcome.ALWAYS_TOOL

    eng = manager.get_engine(f"__bateria__{indice}", agent=agente)
    eng.model = modelo
    eng.approver = aprovar
    ferramentas = 0
    erro = None
    try:
        async for ev in eng.run(prompt):
            if ev.type == EventType.TOOL_STARTED:
                ferramentas += 1
            if ev.type == EventType.ERROR:
                erro = str(ev.data)[:100]
    except Exception as exc:  # noqa: BLE001 — a bateria reporta, não decide
        erro = f"{type(exc).__name__}: {exc}"[:100]
    return ferramentas, erro


def executar(modelo: str, agente: str, execucoes: int) -> int:
    from mangaba.server.manager import SessionManager

    acertos_por_execucao: list[int] = []
    medianas: list[float] = []
    for rodada in range(execucoes):
        ws = Path(tempfile.mkdtemp(prefix="bateria-"))
        preparar(ws)
        manager = SessionManager(workspace=str(ws))
        tempos: list[float] = []
        acertos = 0
        for i, (nome, prompt, verifica) in enumerate(TAREFAS):
            t0 = time.time()
            ferramentas, erro = asyncio.run(
                _rodar_tarefa(manager, modelo, agente, i + rodada * 100, prompt)
            )
            dt = time.time() - t0
            tempos.append(dt)
            try:
                ok = bool(verifica(ws))
            except Exception:
                ok = False
            acertos += ok
            print(
                f"  {'PASSOU' if ok else 'FALHOU':7s} {nome:26s} {dt:6.1f}s "
                f"{ferramentas:2d} tools" + (f"  erro={erro}" if erro else ""),
                flush=True,
            )
        mediana = statistics.median(tempos)
        acertos_por_execucao.append(acertos)
        medianas.append(mediana)
        print(
            f"execução {rodada + 1}/{execucoes}: {acertos}/{len(TAREFAS)} | "
            f"mediana {mediana:.1f}s | total {sum(tempos):.0f}s\n",
            flush=True,
        )

    print(f"== {modelo} ({agente}) ==")
    print(f"acertos por execução: {acertos_por_execucao} (de {len(TAREFAS)})")
    print(f"medianas: {[f'{m:.1f}s' for m in medianas]}")
    pior = min(acertos_por_execucao)
    return 0 if pior == len(TAREFAS) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modelo")
    parser.add_argument("agente", nargs="?", default="cowork")
    parser.add_argument("--execucoes", type=int, default=1)
    args = parser.parse_args()
    return executar(args.modelo, args.agente, args.execucoes)


if __name__ == "__main__":
    raise SystemExit(main())
