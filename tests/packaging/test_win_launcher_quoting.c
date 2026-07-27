/* Testa a montagem da linha de comando do lançador Windows
 * (packaging/win_launcher.c).
 *
 * Roda NATIVAMENTE no host (macOS/Linux): a função de quoting é C puro, sem nada
 * do Windows, então dá para exercitá-la sem cross-compilar e sem ter Windows.
 * Isso importa porque o instalador Windows é gerado por cross-compile e não há
 * como testá-lo de verdade antes de publicar — esta é a parte que dá para provar.
 *
 * São dois níveis:
 *
 *   1. casos fixos, legíveis, que documentam o que se espera;
 *   2. round-trip contra uma reimplementação das regras de parsing do
 *      CommandLineToArgvW — para cada conjunto de argumentos, montar a linha e
 *      parsear de volta tem que devolver exatamente os mesmos argumentos.
 *
 * O round-trip é o que vale: casos escolhidos a dedo só cobrem o que o autor já
 * imaginou. Barras invertidas antes de aspas seguem uma regra que quase ninguém
 * acerta de primeira, e é justamente onde um caminho do Windows tropeça.
 *
 * Uso:
 *   sed -n '/^static void anexar_arg/,/^}/p' packaging/win_launcher.c > /tmp/q.inc
 *   cc -I/tmp -o /tmp/t tests/packaging/test_win_launcher_quoting.c && /tmp/t
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "q.inc"

/* ------------------------------------------------------------------ */
/* Reimplementação das regras de parsing do CommandLineToArgvW.
 *
 * É o algoritmo que o Windows aplica do outro lado: 2n barras + aspa => n
 * barras e a aspa abre/fecha; 2n+1 barras + aspa => n barras e uma aspa
 * literal; barras que não precedem aspa são literais.
 *
 * Escrever isto (em vez de conferir a string montada a olho) é o que permite
 * afirmar que o Python recebe exatamente os argumentos que passamos.         */
static int parsear(const char *linha, char saida[][1024], int maximo) {
    int qtd = 0;
    const char *p = linha;
    while (*p) {
        while (*p == ' ') p++;
        if (!*p) break;
        if (qtd >= maximo) return -1;

        char *destino = saida[qtd];
        size_t fim = 0;
        int dentro_de_aspas = 0;
        while (*p && (dentro_de_aspas || *p != ' ')) {
            if (*p == '\\') {
                size_t barras = 0;
                while (p[barras] == '\\') barras++;
                if (p[barras] == '"') {
                    for (size_t i = 0; i < barras / 2; i++) destino[fim++] = '\\';
                    if (barras % 2) {
                        destino[fim++] = '"';      /* aspa literal */
                        p += barras + 1;
                    } else {
                        p += barras;
                        dentro_de_aspas = !dentro_de_aspas;
                        p++;                        /* consome a aspa */
                    }
                } else {
                    for (size_t i = 0; i < barras; i++) destino[fim++] = '\\';
                    p += barras;
                }
            } else if (*p == '"') {
                dentro_de_aspas = !dentro_de_aspas;
                p++;
            } else {
                destino[fim++] = *p++;
            }
        }
        destino[fim] = '\0';
        qtd++;
    }
    return qtd;
}

static int falhas = 0;

static void checar_roundtrip(const char *const *args, int n, const char *rotulo) {
    char linha[8192];
    linha[0] = '\0';
    for (int i = 0; i < n; i++) anexar_arg(linha, sizeof(linha), args[i]);

    char obtidos[16][1024];
    int qtd = parsear(linha, obtidos, 16);
    if (qtd != n) {
        printf("FALHOU %s\n  linha:  %s\n  esperava %d argumentos, obtive %d\n",
               rotulo, linha, n, qtd);
        falhas++;
        return;
    }
    for (int i = 0; i < n; i++) {
        if (strcmp(obtidos[i], args[i]) != 0) {
            printf("FALHOU %s\n  linha:    %s\n  arg %d esperado: [%s]\n  arg %d obtido:   [%s]\n",
                   rotulo, linha, i, args[i], i, obtidos[i]);
            falhas++;
            return;
        }
    }
    printf("PASSOU %s\n", rotulo);
}

int main(void) {
    /* --- 1. casos fixos: documentam a saída esperada --- */
    struct { const char *args[4]; const char *esperado; } fixos[] = {
      {{"C:\\Prog\\python.exe", "-u", "C:\\Prog\\server_entry.py", NULL},
       "\"C:\\Prog\\python.exe\" \"-u\" \"C:\\Prog\\server_entry.py\""},
      {{"C:\\Users\\Joao Silva\\python.exe", "--port", "51456", NULL},
       "\"C:\\Users\\Joao Silva\\python.exe\" \"--port\" \"51456\""},
      {{"C:\\dir com espaco\\", NULL},
       "\"C:\\dir com espaco\\\\\""},
      {{"tem\"aspa", NULL},
       "\"tem\\\"aspa\""},
    };
    for (size_t i = 0; i < sizeof(fixos) / sizeof(fixos[0]); i++) {
        char buf[4096]; buf[0] = '\0';
        for (int j = 0; j < 4 && fixos[i].args[j]; j++)
            anexar_arg(buf, sizeof(buf), fixos[i].args[j]);
        if (strcmp(buf, fixos[i].esperado) == 0) {
            printf("PASSOU fixo %zu\n", i + 1);
        } else {
            printf("FALHOU fixo %zu\n  saida:    %s\n  esperado: %s\n",
                   i + 1, buf, fixos[i].esperado);
            falhas++;
        }
    }

    /* --- 2. round-trip: monta e parseia de volta --- */
    /* Peças escolhidas para gerar exatamente os casos difíceis: sequências de
     * barras de vários tamanhos, coladas ou não em aspas e espaços. */
    static const char *pecas[] = {
        "", "a", " ", "  ", "\\", "\\\\", "\\\\\\", "\\\\\\\\",
        "\"", "\\\"", "\\\\\"", "a b", "a\\b", "a\\\\b",
        "C:\\Users\\Joao Silva", "C:\\dir\\", "--port", "51456",
        "fim\\", "fim\\\\", "\"inicio", "meio\"meio",
    };
    const int total_pecas = (int)(sizeof(pecas) / sizeof(pecas[0]));

    /* Todos os pares e trios de peças: cobre interação entre argumentos
     * (um terminando em barra seguido de outro começando com aspa, etc.). */
    char rotulo[256];
    for (int i = 0; i < total_pecas; i++) {
        const char *um[] = {pecas[i]};
        snprintf(rotulo, sizeof(rotulo), "roundtrip 1x [%s]", pecas[i]);
        checar_roundtrip(um, 1, rotulo);
    }
    for (int i = 0; i < total_pecas; i++) {
        for (int j = 0; j < total_pecas; j++) {
            const char *dois[] = {pecas[i], pecas[j]};
            snprintf(rotulo, sizeof(rotulo), "roundtrip 2x [%s][%s]", pecas[i], pecas[j]);
            checar_roundtrip(dois, 2, rotulo);
        }
    }
    /* O caso real: python.exe -u script.py --host H --port P */
    for (int i = 0; i < total_pecas; i++) {
        const char *reais[] = {pecas[i], "-u", "C:\\a b\\server_entry.py",
                               "--host", "127.0.0.1", "--port", "51456"};
        snprintf(rotulo, sizeof(rotulo), "roundtrip linha real com [%s]", pecas[i]);
        checar_roundtrip(reais, 7, rotulo);
    }

    printf("\n%d falha(s)\n", falhas);
    return falhas != 0;
}
