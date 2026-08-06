# Mangaba 0.1.39

**A release do trabalho agêntico.** Uma bateria de tarefas reais — medida, versionada no
repositório e usada como critério de aceite — guiou cada mudança abaixo. Duas otimizações
foram **rejeitadas** por ela no caminho; o que entrou é o que provou melhorar.

## Mangaba Local: de inutilizável a utilizável de verdade

Quatro correções e duas otimizações, todas com números:

- **O seletor de modelo agora funciona.** Escolher `qwen3-4b` na interface e receber
  respostas do 14B era o comportamento normal — nada ligava o nome escolhido ao motor, que
  carregava o último modelo baixado. Numa máquina de 16 GB isso significava rodar, sem
  saber, um modelo **3,2× mais lento**. O motor passa a carregar o modelo pedido e só
  reinicia quando ele de fato muda.
- **Um slot em vez de quatro.** O llama-server reservava 65 mil tokens de cache para usar
  16 mil; a pressão de memória aparecia como variância de 2× no mesmo prompt. Com um slot, a
  variância sumiu.
- **A compactação de contexto conhece a janela real.** Antes ela só dispararia em 102 mil
  tokens — contra os 16 mil que o motor serve. Uma sessão longa estourava a janela **seis
  vezes** antes de a compactação agir, e a tarefa morria com "exceeds context size".
- **Reiniciar o motor não o mata mais.** A troca de modelo reinicia o servidor, e o novo
  podia morrer no arranque porque a porta ainda estava presa — deixando o provedor local
  fora do ar em silêncio. Agora ele espera a porta liberar.
- **Sem "pensar em voz alta" no laço agêntico.** O Qwen3 deliberava 435 caracteres antes de
  cada chamada de ferramenta — ~78% de tudo que gerava, a cada passo. Desligado no laço:
  **11× mais rápido** na bateria (mediana de 208 s → 25 s por tarefa), com o mesmo acerto.
  A variante "pensar só na abertura do turno" foi testada e **rejeitada pela bateria**
  (ficou mais lenta E menos correta).
- **Chamadas de ferramenta em lote.** O modelo agora pode pedir várias ferramentas numa
  geração só — "ler três arquivos" custava três voltas ao modelo, a ~30 tokens/s cada.

Resultado na bateria de 12 tarefas: **12/12** na melhor execução (11/12 na outra), mediana
de ~31–36 s por tarefa — contra 3/4 com mediana de 208 s antes destas mudanças (e, antes das
correções, 0/4: o motor nem subia). Na tarefa de aritmética, o modelo agora chama o shell
para calcular em vez de somar de cabeça.

## Mangaba (nuvem): blindado contra o defeito do roteador

A cadeia de fallback do gateway às vezes anuncia ids de modelo malformados
(`nvidia/nvidia/...`); quando o roteador caía num desses, o turno morria no meio da tarefa
com HTTP 400 — um defeito que não é do app nem seu. Agora o app **detecta o 400 de
roteamento e refaz a chamada entregando a escolha de volta à cadeia**, que cai num elo são.
Erros de outra natureza continuam aparecendo (repetir um pedido malformado só duplicaria o
erro).

Resultado na bateria: **12/12 em duas execuções seguidas**, medianas de 13,3 s e 15,5 s
(uma execução anterior fez 9/12, com um soluço de rede do túnel no meio).

## Agentes que conferem o próprio trabalho

As famílias de entrega (Cowork e Negócio) ganharam duas regras de ofício no prompt:

- **aritmética vai para o shell** — conta com mais de duas parcelas, porcentagem ou casas
  decimais é calculada por comando, nunca de cabeça. Somar mentalmente e escrever o total
  errado num entregável era o erro mais comum do modelo local;
- **verificar antes de declarar pronto** — reler o arquivo escrito (ou conferi-lo por
  comando) antes de marcar a tarefa como concluída.

## A régua agora faz parte do produto

`packaging/bateria_agentica.py`: 12 tarefas de ponta a ponta (aritmética, multi-arquivo,
recuperação de erro, edição preservando conteúdo, verificação do próprio resultado),
pontuadas pelo que fica no disco — nunca pela auto-declaração do modelo. É a régua que
aceitou e rejeitou as mudanças desta versão, e é rodável por qualquer pessoa:

```bash
python packaging/bateria_agentica.py local:qwen3-4b negocio --execucoes 3
```

## Ressalvas de sempre

Build do Windows sem teste em hardware real; DMG ad-hoc sem notarização (o macOS e o
SmartScreen pedem confirmação na primeira execução).
