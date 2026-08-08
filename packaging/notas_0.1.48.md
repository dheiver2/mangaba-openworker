# Mangaba 0.1.48

## Conversa longa no modelo local não morre mais estourada

No modelo local, uma conversa que crescia demais — tipicamente ao baixar e analisar um
documento grande — terminava num erro de "janela de contexto" pedindo para você começar
uma sessão nova, jogando o trabalho fora. O mecanismo de resumo automático existia, mas
não reconhecia o erro do motor local e não entrava em ação.

Agora ele entra: a conversa é resumida na hora e o trabalho **continua**. E o medidor de
contexto passou a mostrar ao assistente o tamanho real da janela do modelo local (16 mil
tokens, não os 128 mil que ele imaginava), então ele se organiza antes de encher.

Dica que continua valendo: no modelo local, prefira uma sessão por tarefa e desligue
conectores que não estiver usando — resumo automático salva a sessão, mas trabalho
enxuto rende mais. Para análises pesadas de documentos, um modelo de nuvem com janela
grande continua sendo a escolha certa.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização.
