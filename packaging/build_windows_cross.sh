#!/usr/bin/env bash
# Gera o instalador Windows (.exe) FAZENDO CROSS-COMPILE A PARTIR DO macOS.
#
# Existe porque build_windows.ps1 precisa rodar em Windows (PyInstaller não faz
# cross-compile) e não temos runner Windows disponível: o GitHub Actions está
# desabilitado neste repo e a conta esbarra em bloqueio de faturamento.
#
# As duas metades do app são resolvidas por caminhos diferentes:
#
#   1. App Tauri (Rust) -> cargo --target x86_64-pc-windows-gnu com mingw-w64.
#   2. Sidecar Python   -> runtime "embeddable" oficial do Windows + wheels
#                          win_amd64 (pip download --platform), em vez do
#                          PyInstaller. Um shim em C (win_launcher.c) dá a esse
#                          runtime o nome `mangaba-server.exe` que o Tauri procura.
#
# LIMITE IMPORTANTE: nada disso é executável no macOS. O resultado é verificado
# estruturalmente (o instalador é aberto com 7z e os arquivos-chave conferidos),
# mas o teste funcional de verdade só acontece rodando em Windows.
#
# Pré-requisitos (via Homebrew):
#   brew install mingw-w64 makensis cmake sevenzip
#   rustup target add x86_64-pc-windows-gnu
#
# Uso: bash packaging/build_windows_cross.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GUI="$REPO/surfaces/gui"
TRABALHO="${MANGABA_WIN_BUILD_DIR:-/tmp/mangaba-winbuild}"
PY_VER="3.11.9"
PY_TAG="311"

MINGW_DIR="$(ls -d /opt/homebrew/Cellar/mingw-w64/*/toolchain-x86_64/x86_64-w64-mingw32 2>/dev/null | head -1)"
if [ -z "$MINGW_DIR" ]; then
    echo "mingw-w64 não encontrado. Rode: brew install mingw-w64" >&2
    exit 1
fi

mkdir -p "$TRABALHO"

echo "==> [1/6] runtime Python embeddable do Windows"
if [ ! -d "$TRABALHO/pyembed" ]; then
    curl -fsSL -o "$TRABALHO/python-embed.zip" \
        "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-embed-amd64.zip"
    unzip -o -q "$TRABALHO/python-embed.zip" -d "$TRABALHO/pyembed"
fi

echo "==> [2/6] wheels win_amd64"
# uvicorn[standard] NÃO pode ser pedido como extra: ele arrasta uvloop, que é
# Unix-only, e o resolvedor do pip aborta mesmo com --platform win_amd64. Os
# componentes do extra que existem no Windows entram nomeados um a um.
if [ ! -d "$TRABALHO/wheels" ]; then
    python3 -m pip download --platform win_amd64 --python-version "$PY_TAG" \
        --only-binary=:all: -d "$TRABALHO/wheels" \
        "openai>=1.0" "anthropic>=0.40" "google-genai>=1.0" "textual>=1.0" \
        "fastapi>=0.110" "uvicorn>=0.27" httptools python-dotenv watchfiles colorama \
        docstring_parser "pyyaml>=6" "pydantic>=2" "mcp>=1.1" "httpx>=0.27" \
        "websockets>=13" "ddgs>=9" "croniter>=2" certifi tzdata pypdf pypdfium2
fi

# aisuite é dependência git (sem wheel publicada) — baixa como sdist e extrai.
if [ ! -d "$TRABALHO/aisuite-ext" ]; then
    AISUITE_PIN="1b4bbf303ec21968230b1ec869a144d054e9b3c4"
    python3 -m pip download --no-deps -d "$TRABALHO/aisuite-dl" \
        "aisuite @ git+https://github.com/andrewyng/aisuite.git@$AISUITE_PIN"
    unzip -o -q "$TRABALHO"/aisuite-dl/aisuite-*.zip -d "$TRABALHO/aisuite-ext"
fi

echo "==> [3/6] montando o sidecar"
SIDECAR="$TRABALHO/sidecar"
rm -rf "$SIDECAR"
mkdir -p "$SIDECAR/Lib/site-packages"
cp -R "$TRABALHO/pyembed/"* "$SIDECAR/"

# `pip install --target` recusa wheels win_amd64 rodando no macOS ("not a
# supported wheel on this platform"). Como aqui só queremos *posicionar* os
# arquivos, não instalar de fato, extrair o .whl (que é um zip) faz o serviço.
( cd "$SIDECAR/Lib/site-packages" && for w in "$TRABALHO"/wheels/*.whl; do unzip -o -q "$w"; done )

cp -R "$(find "$TRABALHO/aisuite-ext" -maxdepth 3 -type d -name aisuite | tail -1)" \
      "$SIDECAR/Lib/site-packages/aisuite"
cp -R "$REPO/mangaba" "$SIDECAR/Lib/site-packages/"
rm -rf "$SIDECAR/Lib/site-packages/mangaba/connectors/experimental"
find "$SIDECAR/Lib/site-packages/mangaba" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp "$REPO/packaging/server_entry.py" "$SIDECAR/"

# O runtime embeddable ignora site-packages e o `site` por padrão; ambos são
# necessários (as wheels trazem .pth de namespace, ex. google).
cat > "$SIDECAR/python$PY_TAG._pth" <<PTH
python$PY_TAG.zip
.
Lib\\site-packages

import site
PTH

x86_64-w64-mingw32-gcc -O2 -o "$SIDECAR/mangaba-server.exe" "$REPO/packaging/win_launcher.c"

echo "==> [4/6] libs do whisper.cpp (aliases + stub BLAS)"
# Três atritos reais do whisper-rs no cross-compile, todos resolvidos aqui:
#  (a) o bindgen procura headers do macOS -> BINDGEN_EXTRA_CLANG_ARGS aponta o mingw;
#  (b) com CMAKE_SYSTEM_NAME=Windows o cmake nomeia as libs no padrão MSVC
#      (ggml.a), mas o ld do mingw quer libggml.a. Forçar o prefixo no toolchain
#      não pega no subprojeto ggml, e cópias dentro de out/lib somem quando o
#      cargo re-roda o build script — por isso os aliases moram FORA da árvore
#      do target e entram via -L;
#  (c) o build.rs manda linkar ggml-blas, que o cmake nunca constrói (backend
#      desligado); como nenhum símbolo BLAS é referenciado, um archive vazio
#      satisfaz o linker.
ALIAS="$TRABALHO/libalias"
mkdir -p "$ALIAS"
cat > "$TRABALHO/mingw-toolchain.cmake" <<CMK
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER   x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_RC_COMPILER  x86_64-w64-mingw32-windres)
set(CMAKE_AR           x86_64-w64-mingw32-ar)
set(CMAKE_RANLIB       x86_64-w64-mingw32-ranlib)
set(CMAKE_FIND_ROOT_PATH $MINGW_DIR)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
CMK

echo "" > "$ALIAS/empty.c"
x86_64-w64-mingw32-gcc -c "$ALIAS/empty.c" -o "$ALIAS/empty.o"
x86_64-w64-mingw32-ar rcs "$ALIAS/libggml-blas.a" "$ALIAS/empty.o"

export CC_x86_64_pc_windows_gnu=x86_64-w64-mingw32-gcc
export CXX_x86_64_pc_windows_gnu=x86_64-w64-mingw32-g++
export AR_x86_64_pc_windows_gnu=x86_64-w64-mingw32-ar
export BINDGEN_EXTRA_CLANG_ARGS="--target=x86_64-w64-mingw32 -I$MINGW_DIR/include"
export CMAKE_TOOLCHAIN_FILE="$TRABALHO/mingw-toolchain.cmake"
export RUSTFLAGS="-L $ALIAS"

# Primeira passada: só para o cmake produzir ggml*.a e podermos criar os aliases.
# Ela falha no link do whisper-rs-sys — esperado, por isso o `|| true`.
rm -rf "$GUI/src-tauri/binaries/sidecar"
cp -R "$SIDECAR" "$GUI/src-tauri/binaries/sidecar"
( cd "$GUI/src-tauri" && cargo build --release --target x86_64-pc-windows-gnu 2>/dev/null ) || true

GGML_LIB="$(ls -d "$GUI"/src-tauri/target/x86_64-pc-windows-gnu/release/build/whisper-rs-sys-*/out/lib 2>/dev/null | head -1)"
if [ -n "$GGML_LIB" ]; then
    for f in ggml ggml-base ggml-cpu; do
        [ -f "$GGML_LIB/$f.a" ] && cp -f "$GGML_LIB/$f.a" "$ALIAS/lib$f.a"
    done
fi

echo "==> [5/6] template NSIS em modo ANSI"
# O makensis do Homebrew estoura memória (std::bad_alloc) ao gerar as tabelas de
# idioma no modo Unicode — reproduzível até num script de 3 linhas sem arquivo
# nenhum, então não é o tamanho do payload. O modo ANSI funciona, e o instalador
# do Tauri só usa texto em inglês (ASCII puro), então não há perda de acentuação.
# O template precisa vir SEM BOM: em modo ANSI o makensis rejeita o BOM na linha 1.
( cd "$GUI" && npm run tauri build -- --target x86_64-pc-windows-gnu --bundles nsis 2>/dev/null ) || true

NSI_SRC="$GUI/src-tauri/target/x86_64-pc-windows-gnu/release/nsis/x64/installer.nsi"
if [ ! -f "$NSI_SRC" ]; then
    echo "Tauri não gerou o installer.nsi — veja o log acima." >&2
    exit 1
fi
rm -rf "$TRABALHO/nsis"
cp -R "$(dirname "$NSI_SRC")" "$TRABALHO/nsis"
python3 - "$TRABALHO/nsis/installer.nsi" <<'PY'
import sys
caminho = sys.argv[1]
dados = open(caminho, "rb").read()
if dados.startswith(b"\xef\xbb\xbf"):
    dados = dados[3:]
dados = dados.replace(b"Unicode true", b"Unicode false", 1)
open(caminho, "wb").write(dados)
PY

cat > "$TRABALHO/nsis-overlay.json" <<JSON
{
  "bundle": {
    "windows": {
      "nsis": {
        "compression": "zlib",
        "template": "$TRABALHO/nsis/installer.nsi"
      }
    }
  }
}
JSON

echo "==> [6/6] empacotando o instalador"
( cd "$GUI" && npm run tauri build -- --target x86_64-pc-windows-gnu \
    --bundles nsis --config "$TRABALHO/nsis-overlay.json" )

SAIDA="$GUI/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis"
echo ""
echo "Pronto:"
ls -la "$SAIDA"/*.exe

# Verificação estrutural — o mais perto de um teste que dá para fazer no macOS.
if command -v 7zz >/dev/null 2>&1; then
    echo ""
    echo "==> conferindo o conteúdo do instalador"
    LISTA="$TRABALHO/listagem.txt"
    7zz l "$SAIDA"/*.exe > "$LISTA" 2>&1
    for f in mangaba-desktop.exe sidecar/mangaba-server.exe sidecar/python.exe \
             "sidecar/python$PY_TAG.dll" "sidecar/python$PY_TAG._pth" sidecar/server_entry.py; do
        if grep -q " $f\$" "$LISTA"; then echo "  OK    $f"; else echo "  FALTA $f"; fi
    done
    echo "  módulos mangaba: $(grep -c "sidecar/Lib/site-packages/mangaba/" "$LISTA")"
fi

echo ""
echo "AVISO: build não assinado e NÃO testado em Windows (impossível a partir do"
echo "macOS). Na primeira execução o SmartScreen pede 'Mais informações' > 'Executar assim mesmo'."
