# Mangaba 0.1.47

## WhatsApp agora envia de verdade

O conector de WhatsApp existia na tela, mas o envio não estava ligado — o assistente
sabia escrever a cobrança e não tinha como mandá-la. Agora o `send_message` entrega
por WhatsApp pela Cloud API oficial da Meta: conecte o WhatsApp na tela de conectores
(token e ID do número, do seu app na Meta) e os fluxos de cobrança e triagem por
WhatsApp passam a funcionar de ponta a ponta.

Detalhe que evita confusão: fora da janela de 24 horas desde a última mensagem **do
cliente**, o WhatsApp só entrega modelos aprovados pela Meta — e agora o erro diz
exatamente isso, em vez de um código críptico.

## Fluxos criados por você podem ser removidos

Um fluxo guardado em "Meus fluxos" agora tem botão de remover, com confirmação. Antes,
um fluxo criado errado ficava na tela para sempre. Os fluxos de fábrica não podem ser
removidos — vêm com o app.

## Validado com modelo de verdade

O caminho completo — fluxo com passos, plano de execução, verificação de conclusão e
entregável — foi validado de ponta a ponta com um modelo real e uma planilha real: o
assistente seguiu os passos na ordem, calculou os totais por script (sem aritmética de
cabeça), separou o que estava vencido do que não estava e aplicou o tom certo por
faixa de atraso. Não é mudança de comportamento; é a confirmação de que o que as
últimas versões construíram funciona fora do laboratório.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização. O envio de WhatsApp foi testado contra a API simulada — o primeiro envio
real depende das suas credenciais da Meta.
