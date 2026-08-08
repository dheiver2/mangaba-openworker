# Mangaba 0.1.46

## O histórico das automações fecha todas as pontas

A 0.1.45 corrigiu o caso principal: automação que entregava pela metade era registrada
como concluída. Três auditorias depois, esta versão fecha os caminhos que faltavam —
todos com o mesmo sintoma, o histórico dizendo uma coisa e a realidade sendo outra:

- **Rodar agora.** Uma execução manual interrompida no meio era registrada como
  concluída, mesmo com o aviso aparecendo na tela. Agora o histórico registra o que
  você viu. E o "Rodar agora" também continua de onde a execução anterior parou, em
  vez de refazer do zero o que a madrugada deixou pela metade.
- **Modelo caiu no meio.** Se o provedor de IA falhou durante a execução (limite de
  uso, chave expirada, serviço fora), a execução era registrada como sucesso. Agora
  aparece como erro, com a mensagem real no histórico.
- **Reinício no meio de uma aprovação.** Uma execução que ficou aguardando sua
  aprovação e atravessou um reinício do app era retomada e concluída — mas ficava
  marcada como "executando" para sempre. Agora é fechada com o resultado verdadeiro.

## Fluxos criados por você respondem na API

Um fluxo guardado pelo assistente ("Meus fluxos") não aparecia na consulta de detalhe
da API local. Agora responde igual aos de fábrica.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização.
