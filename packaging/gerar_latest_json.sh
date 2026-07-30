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
