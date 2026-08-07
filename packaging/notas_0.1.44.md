# Mangaba 0.1.44

## No Windows, o agente agora sabe em que shell está

O Mangaba sempre usou o terminal nativo de cada sistema — bash no Mac, PowerShell no Windows
—, mas **isso nunca era dito ao modelo**. Sem saber onde pisava, ele escrevia comandos no
estilo do Mac e, no Windows, uma parte simplesmente não funcionava. Na prática o agente
acertava por padrão num sistema e errava por padrão no outro.

Agora a plataforma e o shell são informados de forma explícita, e as orientações internas
usam os comandos certos de cada sistema. É a diferença mais relevante desta versão para quem
usa Windows.

## Instrução impossível no OCR do Windows

Ao pedir leitura de texto em imagem sem um provedor com visão configurado, quem tinha
instalado pelo instalador do Windows recebia uma sugestão de comando que **não havia como
executar** naquele formato de instalação. Agora a orientação corresponde ao jeito que o
Mangaba foi realmente instalado.

## Ressalvas de sempre

Build do Windows cross-compilado no Mac, sem teste em hardware Windows real; DMG sem
notarização.
