# Mangaba 0.1.42

## Correção da correção: o silêncio do Telegram agora funciona de verdade

A 0.1.41 prometia que duas cópias do app com o mesmo bot do Telegram parariam de brigar —
mas o conserto foi ligado no lugar errado e o efeito não existia: o app instalado continuava
inundando o log com dezenas de erros por minuto, verificado ao vivo logo após a atualização.

A causa: erros de *polling* do Telegram passam por um caminho próprio (`error_callback` do
`start_polling`), e a 0.1.41 tinha registrado o tratamento no caminho de erros de
*mensagem* — que nunca vê o conflito. Agora o tratamento está no caminho certo, provado
lendo o código da biblioteca, e o teste de regressão prende exatamente esse detalhe para o
erro não voltar disfarçado.

Comportamento correto (agora real): a instância que chegou por último percebe o conflito,
avisa numa única linha e cede a vez — as mensagens continuam chegando na instância principal.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização.
