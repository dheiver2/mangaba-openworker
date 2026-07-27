"""Leitura mínima de executáveis PE (Windows), em Python puro.

Existe para que a verificação dos artefatos Windows rode em qualquer máquina —
inclusive no macOS, onde os builds são gerados — sem depender do `objdump` do
mingw estar instalado.

Só o necessário para as checagens de empacotamento: quais DLLs o binário importa
e se ele é console ou GUI.
"""

from __future__ import annotations

import struct

SUBSISTEMA_GUI = 2
SUBSISTEMA_CONSOLE = 3


class PEInvalido(ValueError):
    """O arquivo não é um PE legível."""


class _Secoes:
    """Converte RVA em offset de arquivo usando a tabela de seções."""

    def __init__(self, secoes: list[tuple[int, int, int, int]]) -> None:
        self._secoes = secoes

    def offset(self, rva: int) -> int | None:
        for virt_addr, virt_tam, raw_ptr, raw_tam in self._secoes:
            if virt_addr <= rva < virt_addr + max(virt_tam, raw_tam):
                deslocamento = rva - virt_addr
                if deslocamento < raw_tam:
                    return raw_ptr + deslocamento
        return None


def _abrir(dados: bytes):
    if len(dados) < 0x40 or dados[:2] != b"MZ":
        raise PEInvalido("sem assinatura MZ")
    inicio_pe = struct.unpack_from("<I", dados, 0x3C)[0]
    if dados[inicio_pe : inicio_pe + 4] != b"PE\0\0":
        raise PEInvalido("sem assinatura PE")

    # Cabeçalho COFF: NumberOfSections em +2, SizeOfOptionalHeader em +16.
    coff = inicio_pe + 4
    qtd_secoes = struct.unpack_from("<H", dados, coff + 2)[0]
    tam_opcional = struct.unpack_from("<H", dados, coff + 16)[0]

    opcional = coff + 20
    magica = struct.unpack_from("<H", dados, opcional)[0]
    if magica == 0x20B:  # PE32+
        pe32_mais = True
        base_diretorios = opcional + 112
    elif magica == 0x10B:  # PE32
        pe32_mais = False
        base_diretorios = opcional + 96
    else:
        raise PEInvalido(f"magic desconhecido: {magica:#x}")

    subsistema = struct.unpack_from("<H", dados, opcional + 68)[0]

    inicio_secoes = opcional + tam_opcional
    secoes = []
    for i in range(qtd_secoes):
        base = inicio_secoes + i * 40
        virt_tam, virt_addr, raw_tam, raw_ptr = struct.unpack_from("<IIII", dados, base + 8)
        secoes.append((virt_addr, virt_tam, raw_ptr, raw_tam))

    return _Secoes(secoes), base_diretorios, subsistema, pe32_mais


def subsistema(dados: bytes) -> int:
    """SUBSISTEMA_GUI ou SUBSISTEMA_CONSOLE."""
    return _abrir(dados)[2]


def dlls_importadas(dados: bytes) -> set[str]:
    """Nomes das DLLs na tabela de importação (a lista que o Windows precisa
    resolver no carregamento — se uma faltar, o processo nem inicia)."""
    secoes, base_diretorios, _, _ = _abrir(dados)

    # Data directory 1 = import table.
    rva_import, tam_import = struct.unpack_from("<II", dados, base_diretorios + 8)
    if not rva_import or not tam_import:
        return set()

    inicio = secoes.offset(rva_import)
    if inicio is None:
        return set()

    nomes: set[str] = set()
    # Cada descritor tem 20 bytes; a lista termina num descritor zerado.
    for i in range(inicio, len(dados) - 20, 20):
        descritor = dados[i : i + 20]
        if descritor == b"\0" * 20:
            break
        rva_nome = struct.unpack_from("<I", descritor, 12)[0]
        if not rva_nome:
            break
        offset_nome = secoes.offset(rva_nome)
        if offset_nome is None:
            break
        fim = dados.find(b"\0", offset_nome)
        if fim < 0:
            break
        try:
            nomes.add(dados[offset_nome:fim].decode("ascii"))
        except UnicodeDecodeError:
            break
    return nomes
