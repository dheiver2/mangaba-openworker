#!/usr/bin/env bash
# Instala o app nativo Mangaba (Tauri) em /Applications e cria um atalho de
# verdade — um Finder ALIAS, não um lançador de navegador — na Área de
# Trabalho, com o logo mangaba.ai completo como ícone.
#
# Dois cliques abrem a JANELA NATIVA do app (o sidecar Python sobe embutido,
# sem depender de Docker). Para o caminho via Docker/navegador, veja
# packaging/instalar_atalho_docker.sh.
#
# Uso: bash packaging/instalar_atalho_desktop.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO="/Applications/Mangaba.app"
BUILD_LOCAL="$REPO/surfaces/gui/src-tauri/target/release/bundle/macos/Mangaba.app"

echo "==> Localizando o app nativo"
if [ -d "$BUILD_LOCAL" ]; then
    echo "    build local encontrado: $BUILD_LOCAL"
    ORIGEM="$BUILD_LOCAL"
else
    echo "    sem build local — baixando o .dmg da release mais recente do GitHub"
    TRABALHO="$(mktemp -d)"
    trap 'rm -rf "$TRABALHO"' EXIT
    DMG="$TRABALHO/Mangaba.dmg"

    if command -v gh >/dev/null 2>&1; then
        gh release download --repo dheiver2/mangaba-openworker --pattern '*.dmg' --output "$DMG" --clobber
    else
        URL="$(curl -fsSL https://api.github.com/repos/dheiver2/mangaba-openworker/releases/latest \
            | grep -o '"browser_download_url": *"[^"]*\.dmg"' \
            | head -1 | sed 's/.*"\(https[^"]*\)"/\1/')"
        if [ -z "$URL" ]; then
            echo "Não achei um .dmg na release mais recente. Instale o GitHub CLI (gh) ou" >&2
            echo "rode packaging/build_dmg.sh para gerar um build local." >&2
            exit 1
        fi
        curl -fsSL "$URL" -o "$DMG"
    fi

    MONTAGEM="$TRABALHO/mnt"
    hdiutil attach "$DMG" -nobrowse -mountpoint "$MONTAGEM" >/dev/null
    ORIGEM="$MONTAGEM/Mangaba.app"
    # copia antes do detach (que desmontaria a origem)
    rm -rf "$DESTINO"
    cp -R "$ORIGEM" "$DESTINO"
    hdiutil detach "$MONTAGEM" >/dev/null
    ORIGEM=""  # já copiado
fi

if [ -n "${ORIGEM:-}" ]; then
    echo "==> Instalando em $DESTINO"
    rm -rf "$DESTINO"
    cp -R "$ORIGEM" "$DESTINO"
fi

# Tira o "quarantine" de arquivo baixado — sem isso o Gatekeeper reclama mesmo
# de um app que o próprio usuário mandou instalar.
xattr -cr "$DESTINO" 2>/dev/null || true

# Reforço defensivo: builds do Tauri sem identidade Apple às vezes saem só
# "linker-signed" (cobre o Mach-O, não os Resources — spctl acusa "code has no
# resources but signature indicates they must be present"). build_dmg.sh já
# corrige isso na origem, mas um .dmg baixado de outro lugar (ou de antes dessa
# correção) pode não ter passado por lá — reassinar aqui garante o bundle
# sempre íntegro, não custa nada quando já está correto.
codesign --force --deep --sign - "$DESTINO" 2>/dev/null || true

echo "==> Criando o atalho na Área de Trabalho (Finder alias, não symlink)"
rm -f "$HOME/Desktop/Mangaba" "$HOME/Desktop/Mangaba.app"
osascript <<OSA
tell application "Finder"
    set srcApp to POSIX file "$DESTINO" as alias
    make new alias file to srcApp at desktop
    set name of result to "Mangaba"
end tell
OSA

# Mesmo cache "fantasma" de ícone do IconServices que afeta apps recém-instalados
# (ver o histórico do commit anterior) — reinicia os serviços de ícone pra o
# alias mostrar o ícone certo de primeira, sem precisar de um segundo clique.
CACHE_ICONES="$(getconf DARWIN_USER_CACHE_DIR 2>/dev/null)"
if [ -n "$CACHE_ICONES" ]; then
    rm -rf "$CACHE_ICONES/com.apple.dock.iconcache" \
           "$CACHE_ICONES/com.apple.iconservicesagent" \
           "$CACHE_ICONES/com.apple.iconservices" 2>/dev/null || true
fi
killall iconservicesagent >/dev/null 2>&1 || true
killall Dock >/dev/null 2>&1 || true
killall Finder >/dev/null 2>&1 || true

echo "Pronto: $HOME/Desktop/Mangaba → $DESTINO"
echo "Dois cliques abrem a janela nativa do Mangaba (sem navegador, sem Docker)."
