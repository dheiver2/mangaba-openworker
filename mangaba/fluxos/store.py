"""Fluxos gravados — os que nasceram de um pedido, e não de um release.

O catálogo de `catalog.py` é dado escrito à mão: acrescentar um fluxo exigia editar Python
e publicar versão nova. Isso é aceitável para os fluxos que vêm de fábrica e inaceitável
como único caminho — quem descobre um procedimento que funciona na operação dele não tem
como guardá-lo, e o mesmo trabalho é reexplicado toda vez.

Aqui os fluxos criados em runtime moram em disco, num JSON só, e se juntam ao catálogo de
fábrica na mesma listagem. O formato é EXATAMENTE o de `_fluxo()`: quem consome (o
resolvedor, a tela, o roteamento) não distingue um do outro — um fluxo gravado é um fluxo,
não um cidadão de segunda classe.

Nada entra sem passar por `validacao.validar_fluxo`. É o que impede este arquivo de virar
depósito de cartões travados: peça que não existe conta como faltando para sempre.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

# Problema-guarda-chuva dos fluxos criados na máquina. Fica junto dos de fábrica na tela,
# com dor própria — quem criou sabe por que criou.
PROBLEMA_PROPRIO = {
    "id": "meus-fluxos",
    "titulo": "Meus fluxos",
    "dor": "Procedimentos que você montou aqui, a partir do que pediu — em vez de "
           "reexplicar o mesmo trabalho toda vez.",
    "area": "Meus",
}


class FluxoStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _ler(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            dados = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return dados if isinstance(dados, dict) else {}

    def _gravar(self, dados: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def listar(self) -> list[dict[str, Any]]:
        return list(self._ler().values())

    def get(self, fluxo_id: str) -> Optional[dict[str, Any]]:
        return self._ler().get(fluxo_id)

    def salvar(self, fluxo: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            dados = self._ler()
            dados[fluxo["id"]] = fluxo
            self._gravar(dados)
        return fluxo

    def apagar(self, fluxo_id: str) -> bool:
        with self._lock:
            dados = self._ler()
            if fluxo_id not in dados:
                return False
            del dados[fluxo_id]
            self._gravar(dados)
        return True

    def problema(self) -> Optional[dict[str, Any]]:
        """Os fluxos gravados como um problema a mais na tela — `None` quando não há nenhum
        (um cartão "Meus fluxos" vazio só ocuparia espaço)."""
        fluxos = self.listar()
        if not fluxos:
            return None
        return {**PROBLEMA_PROPRIO, "fluxos": fluxos}
