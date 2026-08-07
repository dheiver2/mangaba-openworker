# Mangaba 0.1.43

## O app volta a abrir

Quem tinha uma pergunta pendente no Inbox podia acabar com o app abrindo **completamente em
branco** — sem texto, sem botão, sem nada que indicasse o que houve. A causa: quando o modelo
oferecia opções de resposta rápida num formato inesperado, a tela quebrava ao desenhá-las; e
como a pergunta ficava salva, a falha se repetia a cada abertura.

Corrigido em três frentes. As opções agora viram texto simples tanto ao chegar quanto ao ler
o histórico já gravado — isso destrava sozinho quem está preso na tela branca. E, o que mais
importa, uma falha ao desenhar qualquer parte da tela agora vira uma mensagem legível com
"Tentar novamente" e "Recarregar", em vez de derrubar a janela inteira.

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
