# Mangaba 0.1.41

**Três consertos vindos de uma caça a bugs na instalação real** — investigando os logs que o
app de verdade escreve em uso, não o que o código promete.

## Fechar a janela não é mais tratado como falha

Fechar (ou recarregar) o app com uma resposta em andamento gerava um rastro de erro completo
no log do servidor, como se algo tivesse quebrado — para a ação mais corriqueira que existe.
Agora o app entende que a janela se foi e segue em frente em silêncio; o trabalho da sessão
continua salvo e reaparece ao reabrir.

## Telegram: duas cópias do app não brigam mais pelo mesmo bot

Com duas instâncias abertas usando o mesmo bot do Telegram (uma reinstalação que deixou a
antiga rodando, por exemplo), as duas disputavam as mensagens sem parar — e o log era
inundado por dezenas de erros por minuto, escondendo qualquer problema real. Agora quem
chegou por último percebe o conflito, avisa numa única linha e cede a vez: as mensagens
continuam chegando normalmente na instância principal.

## Login pendente de conector não parece mais um crash

Quando uma automação rodando sozinha encontra um conector que precisa de login (sessão
expirada do Notion, Linear etc.), o comportamento certo é parar e pedir para você reconectar
pela página do conector — e é o que o app já fazia. Mas isso era registrado no log como um
erro grave, com rastro completo. Fluxo esperado agora é registrado como fluxo esperado;
erros reais de login continuam aparecendo por inteiro.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização (o macOS pede confirmação na primeira execução).
