# Mangaba 0.1.45

## Automação que entregou pela metade agora diz isso

Uma automação que não terminava o trabalho — porque bateu o limite de passos de uma
execução — era registrada como **concluída com sucesso**, e você recebia o aviso de
que tinha terminado. O texto salvo como resultado parecia uma entrega de verdade,
porque o assistente escreve um resumo caprichado quando percebe que está no fim do
espaço. Na prática, o histórico dizia "ok" para um trabalho pela metade.

Agora essas execuções aparecem como **parcial**, com o motivo, e não disparam o aviso
de conclusão. É a mudança mais importante desta versão: o que o histórico diz voltou a
corresponder ao que aconteceu.

## E, na próxima vez, ela continua de onde parou

Antes, cada disparo de uma automação começava do zero. Um trabalho que não coubesse em
uma execução nunca terminava — recomeçava todo dia, para sempre. Agora o plano fica
guardado: a execução seguinte recebe o que já foi feito e continua pelos passos que
faltam, em vez de refazer tudo.

O mesmo vale para as conversas: fechar o app no meio de um trabalho longo não apaga
mais o progresso.

## Fluxos com passos, e fluxos seus

Cada fluxo da tela agora traz os passos do trabalho, na ordem — dá para acompanhar o
que está sendo feito e o que falta, em vez de esperar para ver o que sai no fim.

E o assistente pode **guardar um trabalho que deu certo como um fluxo novo**, seu, que
aparece na mesma tela em "Meus fluxos". Da próxima vez é um clique, em vez de explicar
tudo de novo. Ele confere antes de guardar que as peças declaradas existem mesmo nesta
máquina — um fluxo que promete algo que você não tem seria um cartão travado para
sempre.

## Aprendendo sem alguém olhando

O assistente aprendia com as suas correções. Numa automação que roda de madrugada não
há ninguém para corrigir, então o mesmo erro podia se repetir indefinidamente. Agora
ele registra também o que a própria execução mostrou — e uma automação que falha do
mesmo jeito todo dia deixa uma anotação, não trinta.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização.
