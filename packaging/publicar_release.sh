#!/usr/bin/env bash
# Publica uma release COMPLETA — instaladores, checksums e o manifesto de auto-update.
#
# POR QUE ESTE SCRIPT EXISTE
# --------------------------
# Da v0.1.20 à v0.1.26 as releases saíram só com os instaladores. O `latest.json` (o
# manifesto que o Tauri updater consulta) nunca foi publicado, então o endpoint devolvia
# 404 e NENHUM usuário jamais viu aviso de atualização: quem instalou a 0.1.20 ficou nela,
# sem as correções das sete versões seguintes. O `gerar_latest_json.sh` já existia e fazia
# a coisa certa — só dependia de alguém lembrar de chamá-lo, e ninguém lembrava.
#
# A regra aqui é simples: ou a release sai com o manifesto, ou não sai. Publicar sem ele é
# publicar uma versão que ninguém vai receber.
#
# Uso:
#   bash packaging/publicar_release.sh 0.1.28 "Título da release" [arquivo-de-notas.md]
#
# Pré-requisito: build_dmg.sh e build_windows_cross.sh já rodados COM a chave do updater
# (TAURI_SIGNING_PRIVATE_KEY) — os .sig ao lado dos artefatos são a prova, e o
# gerar_latest_json.sh recusa assinatura órfã ou de versão trocada.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
V="${1:?informe a versão, ex.: 0.1.28}"
TITULO="${2:-Mangaba $V}"
NOTAS_ARQ="${3:-}"
GH_REPO="dheiver2/mangaba-openworker"

GUI="$REPO/surfaces/gui"
DMG="$GUI/src-tauri/target/release/bundle/dmg/Mangaba_${V}_aarch64.dmg"
EXE="$GUI/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis/Mangaba_${V}_x64-setup.exe"
MAC_TGZ="$GUI/src-tauri/target/release/bundle/macos/Mangaba.app.tar.gz"

echo "==> [1/4] conferindo os artefatos da $V"
for f in "$DMG" "$EXE"; do
    [ -f "$f" ] || { echo "FALTA: $(basename "$f") — rode os dois builds antes." >&2; exit 1; }
done
echo "    ok  $(basename "$DMG")"
echo "    ok  $(basename "$EXE")"

echo "==> [2/4] gerando o manifesto de auto-update"
# Sem isto a release é invisível para quem já tem o app instalado. As guardas do script
# (assinatura órfã, versão trocada dentro do tar.gz) abortam antes de publicar algo que
# colocaria os clientes em loop de atualização.
bash "$REPO/packaging/gerar_latest_json.sh" "$V"
[ -f "$REPO/latest.json" ] || { echo "ERRO: latest.json não foi gerado." >&2; exit 1; }

echo "==> [3/4] checksums"
( cd "$REPO" && shasum -a 256 "$DMG" "$EXE" \
    | awk '{n=split($2,a,"/"); print $1"  "a[n]}' > "checksums-$V.txt" )
cat "$REPO/checksums-$V.txt"

echo "==> [4/4] publicando a release v$V"
NOTAS_ARGS=()
if [ -n "$NOTAS_ARQ" ] && [ -f "$NOTAS_ARQ" ]; then
    NOTAS_ARGS=(--notes-file "$NOTAS_ARQ")
else
    NOTAS_ARGS=(--notes "Mangaba v$V")
fi

gh release create "v$V" -R "$GH_REPO" --title "$TITULO" "${NOTAS_ARGS[@]}" \
    "$DMG" "$EXE" \
    "$REPO/checksums-$V.txt" \
    "$REPO/latest.json" \
    "$MAC_TGZ" "$MAC_TGZ.sig" \
    "$EXE.sig"

echo
echo "==> verificando que o updater enxerga a versão nova"
# O teste que importa não é "subiu o arquivo", é "o endpoint que o app consulta responde".
sleep 3
CODIGO="$(curl -sL -o /tmp/latest-publicado.json -w '%{http_code}' \
    "https://github.com/$GH_REPO/releases/latest/download/latest.json")"
if [ "$CODIGO" != "200" ]; then
    echo "AVISO: o endpoint do updater respondeu HTTP $CODIGO — os usuários NÃO receberão" >&2
    echo "       aviso de atualização. Confira os assets da release." >&2
    exit 1
fi
VERSAO_ANUNCIADA="$(python3 -c "import json;print(json.load(open('/tmp/latest-publicado.json'))['version'])")"
if [ "$VERSAO_ANUNCIADA" != "$V" ]; then
    echo "AVISO: o endpoint anuncia $VERSAO_ANUNCIADA, não $V." >&2
    exit 1
fi

echo "    ok  updater anuncia $VERSAO_ANUNCIADA"
echo
echo "Release publicada: https://github.com/$GH_REPO/releases/tag/v$V"
