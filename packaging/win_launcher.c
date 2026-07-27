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
 * Usa CreateProcess + espera, e NÃO _execv. No Windows _execv não substitui o
 * processo como no Unix: o CRT cria um processo novo (com outro PID) e encerra o
 * atual. Isso quebrava duas coisas — o Tauri fica com um handle de filho que
 * morre no mesmo instante em que o sidecar sobe, e a linha de comando montada
 * pelo CRT não cita os argumentos, então qualquer caminho com espaço (um usuário
 * chamado "João Silva", por exemplo) era partido ao meio. Ficando vivo à espera
 * do Python, o PID que o Tauri conhece continua válido pelo tempo todo e o
 * código de saída é propagado.
 *
 * Console app de propósito: um build "windowed" deixaria stdout/stderr nulos e
 * travaria o log de inicialização do uvicorn. O Tauri esconde a janela ao
 * spawnar com CREATE_NO_WINDOW.
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Acrescenta um argumento à linha de comando com as aspas que o CreateProcess
 * espera (regras de quoting do CommandLineToArgvW: aspas ao redor, barras
 * invertidas dobradas quando precedem uma aspa). Sem isso, caminhos com espaço
 * chegam ao Python partidos em vários argumentos. */
static void anexar_arg(char *destino, size_t tamanho, const char *arg) {
    size_t fim = strlen(destino);
    if (fim > 0 && fim + 1 < tamanho) destino[fim++] = ' ';

    if (fim + 1 < tamanho) destino[fim++] = '"';
    for (const char *p = arg; *p && fim + 2 < tamanho; p++) {
        if (*p == '\\') {
            /* Conta a sequência de barras; ela só precisa ser dobrada se vier
             * imediatamente antes de uma aspa (inclusive a de fechamento). */
            size_t barras = 0;
            while (p[barras] == '\\') barras++;
            int antes_de_aspa = (p[barras] == '"' || p[barras] == '\0');
            size_t repetir = antes_de_aspa ? barras * 2 : barras;
            for (size_t i = 0; i < repetir && fim + 2 < tamanho; i++) destino[fim++] = '\\';
            p += barras - 1;
        } else if (*p == '"') {
            if (fim + 3 < tamanho) { destino[fim++] = '\\'; destino[fim++] = '"'; }
        } else {
            destino[fim++] = *p;
        }
    }
    if (fim + 1 < tamanho) destino[fim++] = '"';
    destino[fim] = '\0';
}

int main(int argc, char **argv) {
    char exePath[MAX_PATH];
    if (!GetModuleFileNameA(NULL, exePath, MAX_PATH)) {
        fprintf(stderr, "mangaba-server: nao consegui descobrir o proprio caminho\n");
        return 1;
    }

    /* Corta o nome do executável, ficando só com o diretório. */
    char *ultimaBarra = strrchr(exePath, '\\');
    if (ultimaBarra) *ultimaBarra = '\0';

    char pythonExe[MAX_PATH];
    char entryScript[MAX_PATH];
    snprintf(pythonExe, MAX_PATH, "%s\\python.exe", exePath);
    snprintf(entryScript, MAX_PATH, "%s\\server_entry.py", exePath);

    /* Falhar aqui com uma mensagem clara vale muito: o stderr vai para
     * %APPDATA%\mangaba\logs\mangaba-server.log, que é a única janela de
     * diagnóstico quando o app não conecta. */
    if (GetFileAttributesA(pythonExe) == INVALID_FILE_ATTRIBUTES) {
        fprintf(stderr, "mangaba-server: python.exe nao encontrado em %s\n", pythonExe);
        return 1;
    }
    if (GetFileAttributesA(entryScript) == INVALID_FILE_ATTRIBUTES) {
        fprintf(stderr, "mangaba-server: server_entry.py nao encontrado em %s\n", entryScript);
        return 1;
    }

    /* -u: saída sem buffer, para o log do uvicorn aparecer na hora em vez de
     * ficar preso no buffer quando o processo é encerrado. */
    static char cmdline[32768];
    cmdline[0] = '\0';
    anexar_arg(cmdline, sizeof(cmdline), pythonExe);
    anexar_arg(cmdline, sizeof(cmdline), "-u");
    anexar_arg(cmdline, sizeof(cmdline), entryScript);
    for (int i = 1; i < argc; i++) anexar_arg(cmdline, sizeof(cmdline), argv[i]);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    /* Repassa os handles padrão que o Tauri nos deu (stdout/stderr apontam para
     * o arquivo de log), senão a saída do Python se perde. */
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput  = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError  = GetStdHandle(STD_ERROR_HANDLE);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(pythonExe, cmdline, NULL, NULL,
                        TRUE,            /* herda os handles acima */
                        CREATE_NO_WINDOW, /* nada de janela de console piscando */
                        NULL, exePath, &si, &pi)) {
        fprintf(stderr, "mangaba-server: falha ao iniciar %s (erro %lu)\n",
                pythonExe, (unsigned long)GetLastError());
        return 1;
    }

    WaitForSingleObject(pi.hProcess, INFINITE);

    DWORD codigo = 1;
    GetExitCodeProcess(pi.hProcess, &codigo);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)codigo;
}
