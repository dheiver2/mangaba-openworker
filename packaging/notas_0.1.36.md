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

### O que este provedor **não** faz: imagem e PDF nativo

Sondamos os 14 modelos da cadeia antes de publicar. Todos fazem **tool calling** — é isso
que sustenta usar o gateway como agente de verdade. Mas **nenhum** aceita imagem: pedindo o
Gemini explicitamente e mandando conteúdo multimodal, a resposta é `HTTP 400`, porque o
gateway **troca o modelo em silêncio** (a mesma chamada voltou respondida pelo GPT-OSS-120B).

Ou seja, escolher um modelo na lista é **melhor esforço, não garantia**. Por isso nenhuma
entrada do gateway declara visão no catálogo — declarar faria o app anexar a imagem numa
conversa que ia falhar, e você veria o erro cru sem entender o motivo. Para trabalhar com
imagem, use o **Mangaba Local** ou um provedor com chave própria (Claude, Gemini, OpenAI).

Pela mesma razão a janela de contexto declarada para o `auto` é a do **menor elo plausível**
(64k), e não a do primeiro da cadeia (o Gemini tem 1M): estourar contexto no meio de uma
tarefa é pior do que compactar um pouco mais cedo.

## OCR local: lendo imagem e PDF escaneado sem modelo de visão

Como os dois provedores gratuitos são de texto puro, o app ganhou uma saída que não depende
de chave nenhuma: **OCR rodando na sua máquina**.

- **Imagem anexada** — antes o modelo recebia só `[image attachment — not viewable by this
  model]`: honesto e inútil. Agora o texto é extraído localmente e entra na conversa. Print
  de erro, nota fiscal, slide, etiqueta, contrato fotografado — tudo passa a ser legível.
- **PDF escaneado** — antes terminava em "sem texto extraível, use um modelo com visão", um
  beco sem saída para quem não tem chave. Agora as páginas são rasterizadas e passam por OCR
  (até 20 páginas; OCR é pesado de CPU).
- **Nova ferramenta `ler_imagem`** — o agente lê, por conta própria, uma imagem que já está
  no disco: um print que ele mesmo tirou, uma pasta de comprovantes a conferir. Read-only e
  presa à área de trabalho, igual ao `read_file`.

**O que o OCR não faz:** descrever cena. Ele lê *texto*. "Quantas pessoas aparecem na foto?"
ou "essa cor combina?" continuam exigindo um provedor com visão — e quando não há texto, a
resposta diz isso em vez de fingir que a imagem estava vazia.

**Instalação:** é um extra, não vem por padrão —

```bash
pip install 'mangaba[ocr]'
```

O motor é o RapidOCR sobre onnxruntime: só pip, sem binário de sistema (ao contrário do
Tesseract), roda offline. Ficou de fora do pacote base porque onnxruntime + opencv passam de
200 MB, e quem nunca anexa imagem não deve carregar esse peso. Sem o extra instalado, nada
quebra: a mensagem explica como instalar ou sugere um provedor com visão.

## Notas técnicas

- O gateway **não** é OpenAI-compatível no transporte: a rota é `POST /api/chat` e a resposta
  não-streaming vem embrulhada em `{"provider", "model", "data"}` (o streaming já é SSE
  OpenAI cru). O app fala esse dialeto num cliente próprio e reaproveita todo o parsing já
  testado do provedor OpenAI.
- O endpoint continua editável, para quem aponta o app a um gateway próprio.
- O pré-aquecimento de cache introduzido na 0.1.34 **não** se aplica a este provedor: ele
  roteia para GPUs, onde o prefill não domina, e aquecer gastaria cota compartilhada à toa.
