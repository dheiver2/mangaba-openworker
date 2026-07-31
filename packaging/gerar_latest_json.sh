#!/usr/bin/env bash
# Gera o latest.json do auto-update (Tauri updater) a partir dos artefatos assinados
# dos dois builds. Publicar este arquivo na release é o que faz apps instalados
# enxergarem a versão nova — sem ele, o banner de atualização nunca aparece.
#
# Pré-requisito: build_dmg.sh e build_windows_cross.sh já rodados COM a chave do
# updater (os .sig ao lado dos artefatos são a prova).
#
# Uso: bash packaging/gerar_latest_json.sh <versao>   # ex.: 0.1.16
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
V="${1:?informe a versão, ex.: 0.1.16}"
GUI="$REPO/surfaces/gui"
BASE="https://github.com/dheiver2/mangaba-openworker/releases/download/v$V"

MAC_TGZ="$GUI/src-tauri/target/release/bundle/macos/Mangaba.app.tar.gz"
WIN_EXE="$GUI/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis/Mangaba_${V}_x64-setup.exe"

for f in "$MAC_TGZ" "$MAC_TGZ.sig" "$WIN_EXE" "$WIN_EXE.sig"; do
    [ -f "$f" ] || { echo "FALTA: $f (build sem a chave do updater?)" >&2; exit 1; }
done

# ---- guardas contra publicar assinatura que não corresponde ao binário ----
# Dois modos de falha reais, ambos silenciosos no lado do publisher e fatais no cliente:
#
# (1) `Mangaba.app.tar.gz` NÃO tem versão no nome. Se o build do macOS rodar sem a chave do
#     updater (o script só avisa e segue), o tar.gz+sig da versão ANTERIOR continuam no
#     diretório: o latest.json sairia dizendo "0.1.17" apontando para o binário 0.1.16 —
#     todo Mac atualizaria, continuaria se vendo como 0.1.16 e entraria em loop de update.
# (2) Um rebuild da MESMA versão sem a chave regrava o .exe mas NÃO o .sig: a assinatura
#     antiga fica ao lado do binário novo e todo cliente Windows falha na verificação.
#
# Verificar a assinatura em si exigiria a chave privada, que não fica aqui. Duas checagens
# baratas pegam os dois casos: (a) o .sig precisa ser pelo menos tão recente quanto o
# binário que assina — um .sig mais velho é órfão; (b) o .app dentro do tar.gz precisa
# declarar exatamente a versão que estamos publicando.
mais_novo_que() { [ "$1" -nt "$2" ]; }
for par in "$MAC_TGZ" "$WIN_EXE"; do
    if mais_novo_que "$par" "$par.sig"; then
        echo "ERRO: $(basename "$par") é mais novo que sua assinatura .sig." >&2
        echo "      Rebuild sem TAURI_SIGNING_PRIVATE_KEY deixa .sig órfão — todo cliente" >&2
        echo "      falharia na verificação. Refaça o build COM a chave do updater." >&2
        exit 1
    fi
done

VERSAO_NO_TGZ="$(tar -xOzf "$MAC_TGZ" Mangaba.app/Contents/Info.plist 2>/dev/null \
    | plutil -extract CFBundleShortVersionString raw - 2>/dev/null || true)"
if [ -n "$VERSAO_NO_TGZ" ] && [ "$VERSAO_NO_TGZ" != "$V" ]; then
    echo "ERRO: o Mangaba.app.tar.gz contém a versão $VERSAO_NO_TGZ, não $V." >&2
    echo "      (o nome do arquivo não tem versão — é sobra de um build anterior)" >&2
    exit 1
fi
[ -n "$VERSAO_NO_TGZ" ] || echo "  aviso: não consegui ler a versão dentro do tar.gz"

python3 - "$V" "$MAC_TGZ.sig" "$WIN_EXE.sig" "$BASE" > "$REPO/latest.json" << 'EOF'
import json, pathlib, sys
from datetime import datetime, timezone

v, mac_sig, win_sig, base = sys.argv[1:5]
print(json.dumps({
    "version": v,
    "notes": f"Mangaba v{v} — https://github.com/dheiver2/mangaba-openworker/releases/tag/v{v}",
    "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "platforms": {
        "darwin-aarch64": {
            "signature": pathlib.Path(mac_sig).read_text().strip(),
            "url": f"{base}/Mangaba.app.tar.gz",
        },
        "windows-x86_64": {
            "signature": pathlib.Path(win_sig).read_text().strip(),
            "url": f"{base}/Mangaba_{v}_x64-setup.exe",
        },
    },
}, indent=2))
EOF

echo "Gerado: $REPO/latest.json"
python3 -c "import json; d=json.load(open('$REPO/latest.json')); print('  versão', d['version'], '· plataformas:', ', '.join(d['platforms']))"
