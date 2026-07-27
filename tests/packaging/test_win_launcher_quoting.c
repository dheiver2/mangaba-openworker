/* Testa a montagem da linha de comando do lançador Windows
 * (packaging/win_launcher.c).
 *
 * Roda NATIVAMENTE no host (macOS/Linux): a função de quoting é C puro, sem nada
 * do Windows, então dá para exercitá-la sem cross-compilar e sem ter Windows.
 * Isso importa porque o instalador Windows é gerado por cross-compile e não há
 * como testá-lo de verdade antes de publicar — esta é a parte que dá para provar.
 *
 * Sob teste estão as regras de quoting do CommandLineToArgvW: caminho com espaço
 * (o caso real, "C:\Users\Joao Silva\..."), barra invertida no fim (precisa ser
 * dobrada antes da aspa de fechamento, senão escaparia a aspa) e aspa embutida.
 *
 * Uso:
 *   sed -n '/^static void anexar_arg/,/^}/p' packaging/win_launcher.c > /tmp/q.inc
 *   cc -I/tmp -o /tmp/t tests/packaging/test_win_launcher_quoting.c && /tmp/t
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "q.inc"

int main(void) {
    struct { const char *args[4]; const char *esperado; } casos[] = {
      {{"C:\\Prog\\python.exe", "-u", "C:\\Prog\\server_entry.py", NULL},
       "\"C:\\Prog\\python.exe\" \"-u\" \"C:\\Prog\\server_entry.py\""},
      {{"C:\\Users\\Joao Silva\\python.exe", "--port", "51456", NULL},
       "\"C:\\Users\\Joao Silva\\python.exe\" \"--port\" \"51456\""},
      {{"C:\\dir com espaco\\", NULL},
       "\"C:\\dir com espaco\\\\\""},
      {{"tem\"aspa", NULL},
       "\"tem\\\"aspa\""},
    };
    int falhas = 0;
    for (size_t i = 0; i < sizeof(casos)/sizeof(casos[0]); i++) {
        char buf[4096]; buf[0] = '\0';
        for (int j = 0; j < 4 && casos[i].args[j]; j++)
            anexar_arg(buf, sizeof(buf), casos[i].args[j]);
        int ok = strcmp(buf, casos[i].esperado) == 0;
        printf("%s caso %zu\n  saida:    %s\n  esperado: %s\n",
               ok ? "PASSOU" : "FALHOU", i+1, buf, casos[i].esperado);
        if (!ok) falhas++;
    }
    printf("\n%d falha(s)\n", falhas);
    return falhas != 0;
}
