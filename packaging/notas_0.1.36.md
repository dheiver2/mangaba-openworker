# Mangaba 0.1.36

## IA na nuvem sem chave, para todo mundo que instala

O provedor **Mangaba Nordeste** saiu e no lugar entrou o **Mangaba (nuvem)** — um gateway
compartilhado, o mesmo para todas as instalações, que **não pede chave nem cadastro**.

Era esse o problema: o Nordeste exigia uma chave-cliente gerada à mão no Swagger do gateway
(`/docs → /admin/keys`). Na prática, quem só baixava o app não conseguia usar o provedor sem
falar com o administrador — ou seja, o app tinha um provedor "nosso" que quase ninguém usava.

Agora são **dois** caminhos sem custo e sem cadastro na galeria de provedores, os dois com o
selo **Grátis** e os dois no topo da lista:

- **Mangaba Local** — roda neste computador, privado, sem internet.
- **Mangaba (nuvem)** — roda no gateway da Mangaba AI, sem chave.

### Modelo `auto` (recomendado)

O `auto` não escolhe um modelo: ele entrega a escolha ao gateway, que percorre a **própria
cadeia de fallback**. Se um provedor da cadeia estiver fora do ar ou sem cota, ele cai para o
próximo sozinho. Escolher um modelo específico na lista desliga esse failover — é uma troca
consciente, não um defeito.

### Verificado como agente, não só como chat

Testado contra o gateway real antes de publicar: `tools` no corpo, `tool_calls` na resposta,
mensagens `role:"tool"` aceitas na volta e `tool_calls` também **dentro do streaming**. O
botão **Testar** repete essa prova na sua máquina e avisa em texto claro se o gateway
responder sem executar ferramenta — um modelo assim conversa, mas não lê arquivos, não roda
comandos e não usa conectores, e alguns chegam a *inventar* o resultado da ferramenta.

### Se você já usava o Mangaba Nordeste

Suas preferências são migradas sozinhas ao abrir o app: o modelo padrão passa a ser
`mangaba:auto` e os ids antigos saem da lista. Isso não é cosmético — sem a migração, um
modelo com prefixo desconhecido seria roteado para o provedor **padrão** (OpenAI), e a sua
mensagem sairia cobrada na chave da OpenAI, ou falharia sem explicação.

## Notas técnicas

- O gateway **não** é OpenAI-compatível no transporte: a rota é `POST /api/chat` e a resposta
  não-streaming vem embrulhada em `{"provider", "model", "data"}` (o streaming já é SSE
  OpenAI cru). O app fala esse dialeto num cliente próprio e reaproveita todo o parsing já
  testado do provedor OpenAI.
- O endpoint continua editável, para quem aponta o app a um gateway próprio.
- O pré-aquecimento de cache introduzido na 0.1.34 **não** se aplica a este provedor: ele
  roteia para GPUs, onde o prefill não domina, e aquecer gastaria cota compartilhada à toa.
