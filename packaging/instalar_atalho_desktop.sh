#!/usr/bin/env bash
# Cria o Mangaba.app na Área de Trabalho (macOS): dois cliques → sobe o Docker
# Desktop se preciso, roda `docker compose up -d` e abre http://127.0.0.1:8765.
#
# Uso: bash packaging/instalar_atalho_desktop.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$HOME/Desktop"
APP="$DESKTOP/Mangaba.app"
TRABALHO="$(mktemp -d)"
trap 'rm -rf "$TRABALHO"' EXIT

# -- 1. o script que o .app executa -------------------------------------------------
# AppleScript puro: mostra progresso, espera o daemon do Docker acordar (até 90s),
# sobe o compose e abre o navegador. Erros aparecem em diálogo, não somem.
cat > "$TRABALHO/mangaba.applescript" <<APPLESCRIPT
on run
    try
        do shell script "open -ga Docker"
        -- o daemon leva alguns segundos depois do app abrir
        set pronto to false
        repeat 45 times
            try
                do shell script "/usr/local/bin/docker info >/dev/null 2>&1 || /opt/homebrew/bin/docker info >/dev/null 2>&1 || docker info >/dev/null 2>&1"
                set pronto to true
                exit repeat
            on error
                delay 2
            end try
        end repeat
        if not pronto then error "O Docker não respondeu em 90 segundos. Abra o Docker Desktop e tente de novo."

        do shell script "PATH=/usr/local/bin:/opt/homebrew/bin:\$PATH docker compose -f '$REPO/docker-compose.yml' up -d"

        -- espera o Mangaba responder antes de abrir o navegador (primeiro build demora)
        repeat 60 times
            try
                do shell script "curl -s -o /dev/null --max-time 2 http://127.0.0.1:8765/v1/health"
                exit repeat
            on error
                delay 2
            end try
        end repeat
        do shell script "open http://127.0.0.1:8765"
    on error mensagem
        display dialog "Mangaba: " & mensagem buttons {"OK"} default button 1 with icon caution
    end try
end run
APPLESCRIPT

rm -rf "$APP"
osacompile -o "$APP" "$TRABALHO/mangaba.applescript"

# -- 2. o ícone da manga -------------------------------------------------------------
# O applet usa Contents/Resources/applet.icns; trocamos pelo nosso, gerado do PNG
# oficial (quadrado, transparente) em todos os tamanhos que o macOS espera.
ORIGEM="$REPO/docs/assets/mangaba-icon-1024.png"
ICONSET="$TRABALHO/mangaba.iconset"
mkdir -p "$ICONSET"
for lado in 16 32 64 128 256 512; do
    sips -z "$lado" "$lado" "$ORIGEM" --out "$ICONSET/icon_${lado}x${lado}.png" >/dev/null
    dobro=$((lado * 2))
    sips -z "$dobro" "$dobro" "$ORIGEM" --out "$ICONSET/icon_${lado}x${lado}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$TRABALHO/mangaba.icns"
cp "$TRABALHO/mangaba.icns" "$APP/Contents/Resources/applet.icns"

# O osacompile também gera Contents/Resources/Assets.car (um asset catalog compilado
# com o ícone padrão de applet AppleScript) — e o Finder/IconServices PRIORIZA esse
# arquivo sobre o applet.icns solto quando os dois existem. Sem remover o .car, a
# troca de ícone acima é ignorada silenciosamente (raiz de um bug real: o app
# continuava mostrando o ícone genérico de script mesmo com o .icns já correto).
rm -f "$APP/Contents/Resources/Assets.car"

# O Finder guarda ícone em cache por caminho, e o IconServices mantém um cache
# PRÓPRIO (fora do alcance de um simples killall Finder) em
# $(getconf DARWIN_USER_CACHE_DIR)/com.apple.iconservices*. Sem derrubar os dois,
# a troca de ícone não aparece mesmo com o Assets.car já removido.
touch "$APP"
CACHE_ICONES="$(getconf DARWIN_USER_CACHE_DIR 2>/dev/null)"
if [ -n "$CACHE_ICONES" ]; then
    rm -rf "$CACHE_ICONES/com.apple.dock.iconcache" \
           "$CACHE_ICONES/com.apple.iconservicesagent" \
           "$CACHE_ICONES/com.apple.iconservices" 2>/dev/null || true
fi
killall iconservicesagent >/dev/null 2>&1 || true
killall Dock >/dev/null 2>&1 || true
killall Finder >/dev/null 2>&1 || true

echo "Pronto: $APP"
echo "Dois cliques nele sobem o Docker e abrem o Mangaba em http://127.0.0.1:8765"
