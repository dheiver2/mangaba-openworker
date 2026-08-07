# Mangaba 0.1.43

## Fechar a janela: agora sem rastro de erro, de verdade

A 0.1.41 fez o app parar de tratar "cliente foi embora" como falha no momento de **enviar**
— mas isso apenas mudou onde o problema aparecia: o fluxo seguia adiante e estourava no
momento de **receber**, com outro erro no log (`WebSocket is not connected`), visto no app
instalado logo depois de atualizar.

Agora as duas pontas estão cobertas: fechar ou recarregar o app com uma resposta em
andamento não deixa mais nenhum rastro de erro. Apenas o caso "conexão encerrada" é tratado
como normal — qualquer outro erro continua aparecendo por inteiro, para não esconder
problema de verdade.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização.
