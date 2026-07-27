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

/* Folga sobre MAX_PATH: o diretorio ja cabe em MAX_PATH, e concatenar o nome do
 * arquivo pode passar do limite. Sem essa folga o gcc avisa de truncamento. */
#define CAMINHO_MAX (MAX_PATH + 64)

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

/* Devolve um handle padrão pronto para ser herdado pelo Python.
 *
 * Dois cuidados que o servidor não perdoa. Primeiro, o handle precisa estar
 * marcado como herdável: sem isso o CreateProcess com bInheritHandles=TRUE não
 * repassa nada e o Python nasce com stdout/stderr inválidos — o uvicorn morre
 * poucos segundos depois, na primeira linha de log que tenta escrever (é a
 * trava "Starting mangaba…" que já apareceu neste projeto). Segundo, se o
 * handle vier nulo/inválido (o app Tauri roda sem console), abrimos NUL: um
 * descritor válido que descarta, muito melhor que um handle quebrado. */
static HANDLE handle_herdavel(DWORD qual) {
    HANDLE h = GetStdHandle(qual);
    if (h == NULL || h == INVALID_HANDLE_VALUE) {
        DWORD acesso = (qual == STD_INPUT_HANDLE) ? GENERIC_READ : GENERIC_WRITE;
        SECURITY_ATTRIBUTES sa;
        sa.nLength = sizeof(sa);
        sa.lpSecurityDescriptor = NULL;
        sa.bInheritHandle = TRUE;
        h = CreateFileA("NUL", acesso, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        &sa, OPEN_EXISTING, 0, NULL);
        return (h == INVALID_HANDLE_VALUE) ? NULL : h;
    }
    SetHandleInformation(h, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    return h;
}

/* Registra a falha em %APPDATA%\mangaba\logs\mangaba-launcher.log.
 *
 * O stderr é o canal normal de diagnóstico (o Tauri o aponta para o log do
 * servidor), mas quando o que falha é justamente a herança de handles, escrever
 * nele não chega a lugar nenhum. Este arquivo é a rede de segurança: sem ele,
 * uma falha de inicialização vira uma tela girando para sempre, sem pista. */
static void registrar_falha(const char *mensagem, DWORD erro) {
    fprintf(stderr, "mangaba-server: %s (erro %lu)\n", mensagem, (unsigned long)erro);

    const char *appdata = getenv("APPDATA");
    if (!appdata) return;

    /* Um buffer só, dimensionado a partir do %APPDATA% mais o maior sufixo que
     * anexamos — assim o compilador enxerga que nunca há truncamento. */
    char caminho[CAMINHO_MAX];
    size_t base = strlen(appdata);
    if (base + sizeof("\\mangaba\\logs\\mangaba-launcher.log") > sizeof(caminho)) return;

    snprintf(caminho, sizeof(caminho), "%s\\mangaba", appdata);
    CreateDirectoryA(caminho, NULL);
    snprintf(caminho, sizeof(caminho), "%s\\mangaba\\logs", appdata);
    CreateDirectoryA(caminho, NULL);
    snprintf(caminho, sizeof(caminho), "%s\\mangaba\\logs\\mangaba-launcher.log", appdata);
    const char *arquivo = caminho;

    FILE *f = fopen(arquivo, "a");
    if (!f) return;
    fprintf(f, "mangaba-server: %s (erro %lu)\n", mensagem, (unsigned long)erro);
    fclose(f);
}

int main(int argc, char **argv) {
    char exePath[CAMINHO_MAX];
    if (!GetModuleFileNameA(NULL, exePath, MAX_PATH)) {
        fprintf(stderr, "mangaba-server: nao consegui descobrir o proprio caminho\n");
        return 1;
    }

    /* Corta o nome do executável, ficando só com o diretório. */
    char *ultimaBarra = strrchr(exePath, '\\');
    if (ultimaBarra) *ultimaBarra = '\0';

    char pythonExe[CAMINHO_MAX];
    char entryScript[CAMINHO_MAX];
    if (strlen(exePath) + sizeof("\\server_entry.py") > sizeof(pythonExe)) {
        registrar_falha("caminho de instalacao longo demais", 0);
        return 1;
    }
    snprintf(pythonExe, sizeof(pythonExe), "%s\\python.exe", exePath);
    snprintf(entryScript, sizeof(entryScript), "%s\\server_entry.py", exePath);

    /* Falhar aqui com mensagem clara vale muito: sem isso, um sidecar
     * incompleto vira uma tela girando para sempre, sem nenhuma pista. */
    if (GetFileAttributesA(pythonExe) == INVALID_FILE_ATTRIBUTES) {
        registrar_falha("python.exe nao encontrado ao lado do mangaba-server.exe", 0);
        return 1;
    }
    if (GetFileAttributesA(entryScript) == INVALID_FILE_ATTRIBUTES) {
        registrar_falha("server_entry.py nao encontrado ao lado do mangaba-server.exe", 0);
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
    si.hStdInput  = handle_herdavel(STD_INPUT_HANDLE);
    si.hStdOutput = handle_herdavel(STD_OUTPUT_HANDLE);
    si.hStdError  = handle_herdavel(STD_ERROR_HANDLE);
    ZeroMemory(&pi, sizeof(pi));

    /* Se nem NUL abriu, é melhor deixar o Python herdar o que houver do que
     * entregar handles nulos com STARTF_USESTDHANDLES — nesse caso o Windows
     * daria descritores inválidos e o uvicorn morreria no primeiro log. */
    if (!si.hStdInput || !si.hStdOutput || !si.hStdError) {
        si.dwFlags = 0;
    }

    if (!CreateProcessA(pythonExe, cmdline, NULL, NULL,
                        TRUE,             /* herda os handles acima */
                        CREATE_NO_WINDOW, /* nada de janela de console piscando */
                        NULL, exePath, &si, &pi)) {
        registrar_falha("falha ao iniciar o python", GetLastError());
        return 1;
    }

    WaitForSingleObject(pi.hProcess, INFINITE);

    DWORD codigo = 1;
    GetExitCodeProcess(pi.hProcess, &codigo);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    /* O servidor só termina quando o app fecha; sair com erro significa que ele
     * caiu. Registrar isso transforma "a tela fica girando" em uma pista — o
     * traceback em si vai para o mangaba-server.log, ao qual este aponta. */
    if (codigo != 0) {
        registrar_falha("o servidor python encerrou com erro; veja mangaba-server.log", codigo);
    }
    return (int)codigo;
}
