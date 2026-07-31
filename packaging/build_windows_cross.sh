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

# Qual Python roda o pip. NÃO pode ser o `python3` do PATH: no macOS isso costuma ser o
# 3.9.6 do sistema, e o `aisuite` (dependência git) exige >=3.10 — o download aborta com
# "requires a different Python", o build segue e termina SEM instalador. Preferimos o venv
# do repo, que é o mesmo interpretador usado no build do macOS.
# Precisa ser >=3.10 E ter pip: as duas faltas produzem exatamente a mesma falha silenciosa
# (o passo aborta, `set -e` não pega dentro do `if`, e o build termina sem instalador).
_py_serve() {
    [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
    "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null || return 1
    "$1" -m pip --version >/dev/null 2>&1 || return 1
    return 0
}
PY=""
for cand in "$REPO/.venv/bin/python" "$HOME/.pyenv/shims/python3" python3; do
    if _py_serve "$cand"; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "Nenhum Python >= 3.10 COM pip encontrado (o do sistema costuma ser 3.9)." >&2
    echo "Resolva com: python3 -m venv .venv && .venv/bin/python -m ensurepip && .venv/bin/pip install -e ." >&2
    exit 1
fi
echo "==> Python de build: $PY ($("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))'))"

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
# As faixas abaixo são soltas (">=") e, sozinhas, resolvem para o MAIS NOVO de cada
# pacote. O que segurava isso era o cache de wheels: enquanto ele existia, a release saía
# com as versões da primeira vez. Limpar o cache mudava silenciosamente o conteúdo do
# instalador — foi assim que o `mcp` pulou 1.28 → 2.0 (major!) só no Windows, enquanto o
# macOS continuava em 1.28 pelo venv. Duas plataformas com dependências diferentes é
# exatamente como nasce um bug que só aparece em uma delas.
# O venv é a referência testada: exportamos as versões dele como constraints. `-c` só
# fixa a versão de quem já foi pedido — não acrescenta pacote nenhum.
CONSTRAINTS="$TRABALHO/constraints-do-venv.txt"
"$PY" -m pip freeze 2>/dev/null \
    | grep -E '^[A-Za-z0-9._-]+==' \
    > "$CONSTRAINTS" || true
if [ ! -s "$CONSTRAINTS" ]; then
    echo "Não consegui exportar as versões do venv ($PY) para travar o build." >&2
    exit 1
fi

# pywin32 tem de ser pedido EXPLICITAMENTE: o mcp o declara como
# `pywin32; sys_platform == 'win32'`, mas o pip avalia marcadores de ambiente contra o
# interpretador que está RODANDO (macOS), não contra o --platform alvo — a dependência era
# descartada em silêncio. No Windows real, `import mcp` → mcp/os/win32/utilities →
# `import pywintypes` → ModuleNotFoundError, e como o manager importa mcp no TOPO, o
# servidor morria no boot com o app preso em "Não conectado". Enviado assim na v0.1.12
# e v0.1.13; pego rodando o payload sob Wine (o dep-check em macOS não exercita o ramo
# win32 do mcp).
if [ ! -d "$TRABALHO/wheels" ]; then
    "$PY" -m pip download --platform win_amd64 --python-version "$PY_TAG" \
        --only-binary=:all: -d "$TRABALHO/wheels" -c "$CONSTRAINTS" \
        "openai>=1.0" "anthropic>=0.40" "google-genai>=1.0" "textual>=1.0" \
        "fastapi>=0.110" "uvicorn>=0.27" httptools python-dotenv watchfiles colorama \
        docstring_parser "pyyaml>=6" "pydantic>=2" "mcp>=1.1" "httpx>=0.27" \
        "websockets>=13" "ddgs>=9" "croniter>=2" certifi tzdata pypdf pypdfium2 \
        "pywin32>=306"
fi

# aisuite é dependência git (sem wheel publicada) — baixa como sdist e extrai.
if [ ! -d "$TRABALHO/aisuite-ext" ]; then
    AISUITE_PIN="1b4bbf303ec21968230b1ec869a144d054e9b3c4"
    "$PY" -m pip download --no-deps -d "$TRABALHO/aisuite-dl" \
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

# pywin32 vem inteiro na wheel, mas o mcp (único consumidor) importa SÓ pywintypes,
# win32api, win32con e win32job (mcp/os/win32/utilities.py). O resto — MAPI/Exchange,
# DirectSound, ADSI, ODBC, Pythonwin — é peso morto que ainda por cima dispara o detector
# de DLLs (exchange.pyd quer MSVCP140, adsi.pyd quer ACTIVEDS…). Podamos ao núcleo:
# mantemos win32/lib (Python puro: win32con vive lá), os .pyd realmente importados e as
# DLLs de runtime em pywin32_system32. A poda é VERIFICADA: o payload roda sob Wine no
# fim (import mcp) — se faltar um módulo, quebra aqui e não na máquina do usuário.
(
    cd "$SIDECAR/Lib/site-packages"
    rm -rf win32comext Pythonwin pythonwin isapi win32/Demos win32/test
    # _win32sysloader.pyd fica: e' o carregador que o pywintypes.py usa para achar a
    # pywintypes311.dll — sem ele, ModuleNotFoundError no import (pego sob Wine).
    find win32 -maxdepth 1 -name "*.pyd" \
        ! -name "win32api.pyd" ! -name "win32job.pyd" ! -name "win32event.pyd" \
        ! -name "win32process.pyd" ! -name "_win32sysloader.pyd" -delete
)

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

# Nada aqui valida o fecho de dependências: as wheels são extraídas na mão
# (`pip install --target` recusa wheels de outra plataforma), então um pacote
# faltando só apareceria em Windows, com o servidor morrendo no import e o app
# preso em "Não conectado". Falhar agora custa segundos; falhar lá custa uma
# release.
"$PY" "$REPO/tests/packaging/verificar_deps_sidecar.py" \
    --site-packages "$SIDECAR/Lib/site-packages"

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

# whisper-rs-sys emite `cargo:rustc-link-lib=dylib=stdc++`, e esse "dylib=" vence
# o -static-libstdc++ da linha de comando: o .exe sai pedindo libstdc++-6.dll e
# o app nem abre (foi o que derrubou a v0.1.8). O que resolve é o ld não achar a
# import lib: este diretório vem primeiro no -L e carrega SÓ a versão estática,
# sem o libstdc++.dll.a ao lado.
cp -f "$MINGW_DIR/lib/libstdc++.a" "$ALIAS/libstdc++.a"

export CC_x86_64_pc_windows_gnu=x86_64-w64-mingw32-gcc
export CXX_x86_64_pc_windows_gnu=x86_64-w64-mingw32-g++
export AR_x86_64_pc_windows_gnu=x86_64-w64-mingw32-ar
export BINDGEN_EXTRA_CLANG_ARGS="--target=x86_64-w64-mingw32 -I$MINGW_DIR/include"
export CMAKE_TOOLCHAIN_FILE="$TRABALHO/mingw-toolchain.cmake"
# -static-libstdc++/-static-libgcc: sem isso o whisper-rs-sys pede
# `dylib=stdc++` e o .exe sai dependendo de libstdc++-6.dll, que não existe em
# Windows nenhum — o app morre no start com "libstdc++-6.dll não foi
# encontrado". A conferência de DLLs no fim deste script existe para pegar
# justamente esse tipo de dependência pendurada.
export RUSTFLAGS="-L $ALIAS -C link-arg=-static-libstdc++ -C link-arg=-static-libgcc"

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
"$PY" - "$TRABALHO/nsis/installer.nsi" <<'PY'
import sys

caminho = sys.argv[1]
dados = open(caminho, "rb").read()
if dados.startswith(b"\xef\xbb\xbf"):
    dados = dados[3:]
dados = dados.replace(b"Unicode true", b"Unicode false", 1)

# "Error opening file for writing: ...\mangaba-desktop.exe" (relatado 31/07/2026, v0.1.18):
# o instalador nao conseguia sobrescrever o executavel porque o app seguia aberto. A macro
# CheckIfAppIsRunning do Tauri e chamada, mas fecha o app pelo plugin `nsis_tauri_utils`,
# distribuido SOMENTE em x86-unicode — e este instalador e ANSI (o makensis do macOS estoura
# memoria em Unicode, veja acima). O `!addplugindir` do Tauri aponta direto para a pasta
# unicode, entao a DLL carrega sem erro de compilacao e recebe strings ANSI: o
# `FindProcessCurrentUser` nunca encontra o processo, ninguem e encerrado e a copia falha.
#
# Trocamos as CHAMADAS por codigo inline com `nsExec` + `taskkill`, que existem em ANSI.
# Nao adianta corrigir a macro no utils.nsh: o Tauri regenera esse arquivo e so honra o
# installer.nsi como template (verificado — o utils.nsh patchado era descartado).
FECHAR_APP = b'''
  ; --- encerra o app sem depender do plugin somente-Unicode (patch do build) ---
  ; taskkill devolve 128 quando o processo nem estava rodando: serve de deteccao.
  nsExec::Exec 'taskkill /IM "${MAINBINARYNAME}.exe"'
  Pop $R0
  ${If} $R0 == 0
    DetailPrint "Fechando o ${PRODUCTNAME} para atualizar..."
    Sleep 2000
    nsExec::Exec 'taskkill /F /IM "${MAINBINARYNAME}.exe"'
    Pop $R0
    Sleep 500
  ${EndIf}
  ; O sidecar Python vive no diretorio de instalacao e segura os proprios arquivos:
  ; sem encerra-lo, a copia falha do mesmo jeito, so que num arquivo diferente.
  nsExec::Exec 'taskkill /F /IM "mangaba-server.exe"'
  Pop $R0
  Sleep 500
'''

ALVO = b'  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"'
n = dados.count(ALVO)
if n == 0:
    raise SystemExit("ERRO: chamada de CheckIfAppIsRunning nao encontrada no installer.nsi")
dados = dados.replace(ALVO, FECHAR_APP)
open(caminho, "wb").write(dados)
print(f"    fechamento do app trocado por taskkill em {n} ponto(s) (ANSI-safe)")
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
# Chave do auto-update (minisign): mesma convenção do build_dmg.sh — sem ela o exe sai
# sem .sig e usuários instalados nunca receberão a atualização.
UPDATER_ENV="${OCW_UPDATER_ENV:-$REPO/../.ocw-updater.env}"
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ] && [ -z "${TAURI_SIGNING_PRIVATE_KEY_PATH:-}" ] && [ -f "$UPDATER_ENV" ]; then
  # shellcheck disable=SC1090
  source "$UPDATER_ENV"
fi
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ] && [ -z "${TAURI_SIGNING_PRIVATE_KEY_PATH:-}" ]; then
  echo "    WARNING: sem chave do updater — instalador NÃO ASSINADO para auto-update (não publique)."
fi
( cd "$GUI" && npm run tauri build -- --target x86_64-pc-windows-gnu \
    --bundles nsis --config "$TRABALHO/nsis-overlay.json" )

SAIDA="$GUI/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis"
# O diretório acumula os .exe de TODAS as versões já construídas, então o glob antigo
# ("$SAIDA"/*.exe) passava cinco caminhos para um verificador que aceita um só — o build
# morria com "unrecognized arguments" DEPOIS de já ter produzido o instalador, e a
# verificação (a única que temos aqui) nunca chegava a rodar.
VERSAO_ATUAL="$("$PY" -c "import json,sys; print(json.load(open('$GUI/src-tauri/tauri.conf.json'))['version'])")"
INSTALADOR="$SAIDA/Mangaba_${VERSAO_ATUAL}_x64-setup.exe"
if [ ! -f "$INSTALADOR" ]; then
    echo "Instalador da versão $VERSAO_ATUAL não foi produzido em $SAIDA." >&2
    exit 1
fi
echo ""
echo "Pronto:"
ls -la "$INSTALADOR"

# Verificação do artefato. É o que substitui o teste que não dá para fazer daqui
# (rodar em Windows), e cada checagem existe por um build quebrado que chegou aos
# usuários — DLL pendurada, ícone em cache, sidecar incompleto. Falhar aqui é o
# ponto: um instalador que não passa não deve ser publicado.
echo ""
echo "==> verificando o instalador"
"$PY" "$REPO/tests/packaging/verificar_windows.py" "$INSTALADOR" \
    --icone "$GUI/src-tauri/icons/icon.ico"

echo ""
echo "AVISO: build não assinado e NÃO testado em Windows (impossível a partir do"
echo "macOS) — as checagens acima cobrem o ARTEFATO, não o funcionamento."
echo "Na primeira execução o SmartScreen pede 'Mais informações' > 'Executar assim mesmo'."
