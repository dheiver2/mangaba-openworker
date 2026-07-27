/* Lançador do sidecar no Windows.
 *
 * O shell Tauri (src-tauri/src/lib.rs) espera um executável chamado
 * `mangaba-server.exe` e o invoca com `--host 127.0.0.1 --port N`, herdando as
 * variáveis de ambiente (MANGABA_API_TOKEN etc.).
 *
 * No macOS/Linux esse binário é produzido pelo PyInstaller, que precisa rodar no
 * SO alvo. Como o build oficial do Windows é feito por cross-compile a partir do
 * macOS, aqui o sidecar é o runtime "embeddable" oficial do Python somado às
 * wheels win_amd64 — e este shim é a peça que dá a ele o nome e a interface de
 * linha de comando que o Tauri procura: repassa argv para
 * `python.exe server_entry.py ...`, no mesmo diretório deste executável.
 *
 * Console app de propósito: um build "windowed" deixaria stdout/stderr nulos e
 * travaria o log de inicialização do uvicorn. O Tauri esconde a janela ao
 * spawnar com CREATE_NO_WINDOW.
 */
#include <windows.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    char exePath[MAX_PATH];
    if (!GetModuleFileNameA(NULL, exePath, MAX_PATH)) {
        fprintf(stderr, "mangaba-server: nao consegui descobrir o proprio caminho\n");
        return 1;
    }

    /* Corta o nome do executável, ficando só com o diretório. */
    char *lastSep = strrchr(exePath, '\\');
    if (lastSep) *lastSep = '\0';

    char pythonExe[MAX_PATH];
    char entryScript[MAX_PATH];
    snprintf(pythonExe, MAX_PATH, "%s\\python.exe", exePath);
    snprintf(entryScript, MAX_PATH, "%s\\server_entry.py", exePath);

    /* argv repassado: python.exe server_entry.py <args originais> + NULL */
    char **args = (char **)malloc((argc + 2) * sizeof(char *));
    if (!args) {
        fprintf(stderr, "mangaba-server: sem memoria\n");
        return 1;
    }
    args[0] = pythonExe;
    args[1] = entryScript;
    for (int i = 1; i < argc; i++) args[i + 1] = argv[i];
    args[argc + 1] = NULL;

    /* _execv substitui este processo pelo Python, preservando o PID — importante
     * porque o Tauri mata o sidecar por handle do processo que ele spawnou. */
    _execv(pythonExe, (const char *const *)args);

    /* Só chega aqui se o exec falhar. */
    fprintf(stderr, "mangaba-server: falha ao iniciar %s\n", pythonExe);
    return 1;
}
