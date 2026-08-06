# Mangaba 0.1.37

**Release de correção.** Uma auditoria da 0.1.36, publicada horas antes, encontrou sete
defeitos — dois deles graves o bastante para justificar esta versão sozinhos. Se você
instalou a 0.1.36, **atualize**.

## 🔴 PDF escaneado travava o app inteiro

Anexar um PDF sem texto embutido congelava o servidor — **todas** as sessões, todo o
streaming — por dezenas de segundos.

A adaptação de anexos (extrair texto de PDF, rasterizar páginas, rodar OCR) acontecia direto
no laço de eventos. Medido: uma página A4 cheia custa ~4,4 s de CPU, então o teto de 20
páginas dava ~90 s de app parado. Agora esse trabalho roda numa thread, como todo o resto do
processamento pesado.

Três consertos no mesmo caminho:

- o motor de OCR passa a ser aquecido também ao anexar **PDF** — antes só imagem aquecia, ou
  seja, o caminho barato estava protegido e o caro, descoberto;
- o teto caiu de 20 para **8 páginas**;
- e o corte agora é **dito em voz alta**: *"só as 8 primeiras de 40 páginas foram lidas — as
  demais NÃO estão neste texto"*. Um teto silencioso é pior que teto nenhum: o agente leria 8
  de 40 páginas e responderia como se tivesse lido o documento inteiro.

## 🟠 O card do Mangaba (nuvem) media a coisa errada

O card do provedor decidia se ele estava "configurado" olhando se havia **modelo local
baixado** — algo sem relação nenhuma com um gateway de nuvem. O resultado era um card que
mentia nos dois sentidos: ✗ num provedor que funciona sem setup algum, e ✓ pelo motivo
errado. Pior, incoerente com o próprio app, já que o seletor de modelos considerava o gateway
pronto.

A causa era uma suposição embutida: "sem chave" significava "é o provedor local". Agora cada
provedor declara a própria prontidão, então a armadilha não fica armada para o próximo.

## Também nesta versão

- **~148 ms a menos por chamada** ao gateway: a conexão HTTP passa a ser reaproveitada em vez
  de refeita a cada passo. Num turno agêntico de 10 passos, ~1,5 s de espera pura.
- **A chave do provedor aposentado é apagada.** Quem usava o Mangaba Nordeste tinha o modelo
  migrado, mas a chave-cliente ficava órfã no cofre — um segredo válido de um serviço que o
  app não sabe mais usar, guardado para sempre sem nada que o exibisse ou apagasse.
- **`ler_imagem` agora reconhece `.webp`, `.bmp` e `.gif`** corretamente. O OCR já funcionava
  nesses formatos, mas a nota saía sem formato e sem dimensões.
- **Erro de HTTP no streaming** chega a quem sabe repetir a chamada, em vez de estourar tarde,
  no meio da iteração; e parar uma resposta pela metade fecha a conexão em vez de deixá-la
  pendurada.
- Documentação interna corrigida: eu havia registrado "~19 s para carregar o motor de OCR" e
  usado esse número para justificar decisões de projeto. Medido em processo limpo: **0,4 s**.
  O 19 s era uma leitura fria única, não o custo real.

## Primeira resposta mais rápida

Cada turno reenvia um "prefixo" fixo ao modelo: as instruções do agente mais o catálogo de
ferramentas. Medindo o custo real disso:

- no **motor local**, o prefill frio custa **~5 ms por token** — 3.675 tokens levaram 18,9 s
  (a mesma chamada com o cache quente cai para 1,3 s);
- no **gateway**, um prompt curto responde em **0,55 s** de forma estável, mas a partir de
  alguns milhares de tokens a cadeia de fallback desvia para modelos **5× mais lentos**
  (2 s a 4,8 s).

Ou seja: o prefixo sozinho já tirava toda sessão da faixa rápida. Esta versão corta a gordura
que dava para cortar **sem remover nenhuma capacidade** — o gerador de esquemas emitia campos
vazios (`description: ""`, `default: null`) para cada parâmetro, e o modelo relia esse lixo em
todo turno. São ~4% do prefixo, ~1,3 s a menos de espera na primeira resposta de cada sessão
local.

Entra junto um **teto de tamanho por família de agente**, verificado automaticamente. Sem ele
o prefixo volta a crescer sem ninguém perceber — foi exatamente o que aconteceu desde a
0.1.33, e agora a build falha antes de a lentidão chegar até você.

## Ressalvas de sempre

O build do Windows continua **sem teste em hardware Windows real** (impossível a partir do
macOS) — as checagens automatizadas cobrem o artefato, não o funcionamento. O DMG é ad-hoc,
sem notarização: na primeira execução o macOS e o SmartScreen pedem confirmação.
