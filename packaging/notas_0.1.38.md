# Mangaba 0.1.38

**Release de correção urgente.** Se você usa o **Mangaba Local**, atualize: nas versões
0.1.34 a 0.1.37 ele simplesmente **não ligava**.

## 🔴 O motor local não subia — e não dizia por quê

O app passava a opção de Flash Attention sem valor (`-fa`). As versões atuais do llama-server
exigem `on`, `off` ou `auto`, e a opção solta engolia o argumento seguinte como se fosse o
valor. O motor morria no arranque com:

```
error while handling argument "-fa": error: unknown value for --flash-attn: '-b'
```

O efeito para quem usa era brutal e mudo: o **único provedor que roda sem internet** nunca
ficava pronto, e nada na tela explicava a causa. O erro nasceu na 0.1.34, junto de uma
otimização de latência, e passou por três releases sem ser notado — porque um motor já em
execução continuava funcionando; só quem reiniciava o app descobria.

Corrigido, com um teste que trava o valor da opção.

## Também nesta versão

**A compactação de contexto voltava a contar certo.** A estimativa de tamanho subestimava
mensagens pequenas em até 67% (ignorava campos como horário e identificador de ferramenta).
Contexto subestimado atrasa a compactação — e essa é a direção cara do erro: compactar cedo
demais custa um resumo, estourar a janela mata a tarefa no meio.

**Respostas longas não são mais cortadas por impaciência.** O limite de leitura das conexões
tinha caído de 600 s para 60 s para todos os provedores. No motor local, um contexto grande
leva mais que isso só para processar o prompt — a resposta morria no meio mesmo indo bem.

Os três defeitos vieram do mesmo commit de otimização da 0.1.34, encontrados por uma auditoria
com bisect: os testes que apontavam para eles estavam certos desde o começo.

## Ressalvas de sempre

O build do Windows continua **sem teste em hardware Windows real** (impossível a partir do
macOS) — as checagens automatizadas cobrem o artefato, não o funcionamento. O DMG é ad-hoc,
sem notarização: na primeira execução o macOS e o SmartScreen pedem confirmação.
