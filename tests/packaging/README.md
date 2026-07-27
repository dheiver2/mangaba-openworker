# Verificação de empacotamento

Testes que rodam **no macOS** e verificam os artefatos de macOS e Windows antes
de publicar. Existem porque o instalador Windows é gerado por cross-compile
(`packaging/build_windows_cross.sh`) e não há máquina Windows para testá-lo:
sem estas checagens, o primeiro a descobrir que o build está quebrado é o
usuário.

Cada uma nasceu de um build quebrado que chegou às pessoas:

| Verificação | O que deixou passar |
|---|---|
| DLLs importadas resolvem | v0.1.8: o app não abria — `libstdc++-6.dll não foi encontrado`. O instalador tinha todos os arquivos; o problema era uma dependência pendurada, que "conferir os arquivos" não vê |
| Ícone embutido é o atual | v0.1.10: trocar `icons/icon.ico` e rebuildar **não** re-embute o ícone (o recurso fica em cache). Só se via na barra de tarefas do Windows |
| Sealed Resources na assinatura | v0.1.8 (macOS): o build do Tauri sem identidade Apple sai só "linker-signed" — cobre o Mach-O, não os Resources. Assinatura estruturalmente quebrada, app recusado |
| Sidecar completo | um arquivo faltando vira uma tela girando para sempre, sem mensagem |
| Dependências do sidecar | as wheels são extraídas na mão, então nada valida o fecho: um pacote ausente mata o servidor no import |

## Rodando

```shell
# Artefato Windows (payload, DLLs, subsistema, ._pth, ícone)
python3 tests/packaging/verificar_windows.py caminho/Mangaba_x.y.z_x64-setup.exe

# Bundle macOS (arquivos, assinatura, arquitetura, versão)
python3 tests/packaging/verificar_macos.py caminho/Mangaba.app --versao 0.1.11

# Dependências do sidecar — estático e, opcionalmente, subindo o servidor
python3 tests/packaging/verificar_deps_sidecar.py --site-packages <sidecar>/Lib/site-packages
python3 tests/packaging/verificar_deps_sidecar.py --venv /caminho/venv/bin/python

# Quoting da linha de comando do lançador Windows (C puro, roda no host)
sed -n '/^static void anexar_arg/,/^}/p' packaging/win_launcher.c > /tmp/q.inc
cc -I/tmp -o /tmp/t tests/packaging/test_win_launcher_quoting.c && /tmp/t
```

`build_windows_cross.sh` e `build_dmg.sh` já chamam o que lhes cabe e **abortam**
quando algo não confere.

Requisitos: Python 3.10+ e, para o instalador Windows, o 7-Zip
(`brew install sevenzip`). A leitura dos PE é feita por `pe.py`, em Python puro,
justamente para não exigir o `objdump` do mingw.

## O que isto NÃO garante

Verifica o **artefato**, não o comportamento. Um instalador aprovado aqui pode
mesmo assim falhar em Windows por algo que só aparece em execução — foi o caso
do lançador do sidecar, cujo defeito (`_execv` não substitui o processo no
Windows) nenhuma checagem estática pegaria. Para isso não há substituto para
rodar em Windows de verdade; na falta disso, o app grava
`%APPDATA%\mangaba\logs\mangaba-launcher.log` e `mangaba-server.log` com o motivo
exato da falha.
