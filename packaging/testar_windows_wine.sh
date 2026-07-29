#!/usr/bin/env bash
# Fumaça do instalador Windows SOB WINE, direto do macOS — o mais perto de "rodar em
# Windows" que dá sem uma máquina Windows.
#
# Por que existe: a verificação estrutural (verificar_windows.py) confere o ARTEFATO,
# não o comportamento. A v0.1.12 e a v0.1.13 passaram nela e mesmo assim iam a óbito no
# boot em Windows real: `import mcp` → pywintypes ausente (o pip descarta dependências
# com marcador `sys_platform == 'win32'` quando roda no macOS). Este script pegou esse
# bug — e pegou também a poda agressiva do pywin32 (_win32sysloader apagado) — ANTES de
# chegar a usuários.
#
# O que cobre: o SIDECAR (Python embeddable + mangaba-server.exe): boot, imports, bind
# de porta e /v1/providers respondendo. O que NÃO cobre: a GUI Tauri (WebView2 não roda
# de forma confiável sob Wine) — para ela, a lógica por plataforma é testada no
# Playwright (e2e/platform-variants.spec.ts) e o teste real exige Windows/VM.
#
# Pré-requisito: brew install --cask wine-stable
#   (se o Gatekeeper apagar o app não assinado: reinstale e rode logo em seguida
#    xattr -dr com.apple.quarantine "/Applications/Wine Stable.app")
#
# Uso: bash packaging/testar_windows_wine.sh [caminho/do/Mangaba_X.Y.Z_x64-setup.exe]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
WINE="/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine"
if [ ! -x "$WINE" ]; then
    echo "Wine não encontrado. Rode: brew install --cask wine-stable" >&2
    exit 1
fi

INSTALADOR="${1:-}"
if [ -z "$INSTALADOR" ]; then
    INSTALADOR="$(ls -t "$REPO"/surfaces/gui/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis/Mangaba_*_x64-setup.exe 2>/dev/null | head -1)"
fi
[ -f "$INSTALADOR" ] || { echo "Instalador não encontrado: $INSTALADOR" >&2; exit 1; }
echo "==> testando sob Wine: $(basename "$INSTALADOR")"

export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-mangaba-smoke}" WINEDEBUG=-all
TRAB="$(mktemp -d /tmp/mangaba-wine-smoke.XXXXXX)"
trap 'pkill -f "mangaba-server.exe" 2>/dev/null; rm -rf "$TRAB"' EXIT

7zz x -y -o"$TRAB" "$INSTALADOR" >/dev/null
cd "$TRAB/sidecar"

echo "==> [1/3] imports fatais (a classe de bug da v0.1.12/13)"
"$WINE" python.exe -c "
import mcp, fastapi, uvicorn, httpx, pydantic, openai, anthropic, yaml
import mangaba.server.app
print('IMPORTS_OK')" > "$TRAB/out.txt" 2>&1
grep -q IMPORTS_OK "$TRAB/out.txt" || {
    echo "FALHOU no import — traceback:"; grep -A2 -E "Error|Traceback" "$TRAB/out.txt" | head -10
    exit 1
}
echo "  ok"

echo "==> [2/3] boot do mangaba-server.exe + porta"
# Porta aleatória: uma sobra de execução anterior segurando uma porta fixa produz um 401
# do servidor VELHO (token diferente) + bind error 10048 do novo — diagnóstico confuso.
PORTA=$((20000 + RANDOM % 20000))
MANGABA_API_TOKEN=winesmoke "$WINE" mangaba-server.exe --host 127.0.0.1 --port "$PORTA" \
    > "$TRAB/server.log" 2>&1 &
R=000
for _ in $(seq 1 45); do
    R="$(curl -s -o /dev/null -w '%{http_code}' -H 'x-mangaba-token: winesmoke' \
        "http://127.0.0.1:$PORTA/v1/providers" 2>/dev/null)" || true
    [ "$R" = "200" ] && break
    sleep 2
done
[ "$R" = "200" ] || { echo "FALHOU: servidor não respondeu (HTTP $R)"; tail -5 "$TRAB/server.log"; exit 1; }
echo "  ok (HTTP 200)"

echo "==> [3/3] /v1/providers responde com conteúdo"
N="$(curl -s -H 'x-mangaba-token: winesmoke' "http://127.0.0.1:$PORTA/v1/providers" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))')"
[ "$N" -ge 10 ] || { echo "FALHOU: só $N provedores"; exit 1; }
echo "  ok ($N provedores)"

echo ""
echo "Fumaça sob Wine PASSOU. Lembrete: isto exercita o sidecar de verdade, mas a GUI"
echo "(WebView2) e o instalador NSIS em si só são testáveis em Windows real."
