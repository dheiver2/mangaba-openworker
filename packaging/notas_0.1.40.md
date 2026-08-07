# Mangaba 0.1.40

## Motor local mais rápido no Windows, com GPU (Vulkan)

Uma auditoria comparando Windows e macOS achou uma diferença real de desempenho, não só
cosmética: o **Mangaba Local** sempre baixava a build **CPU-only** no Windows
(`win-cpu-x64`), enquanto no macOS ele já usa Metal desde sempre. Numa GPU AMD, Intel ou
NVIDIA decente, isso significava rodar sem aceleração nenhuma, sem que ninguém soubesse.

A partir desta versão, com uma GPU real detectada, o app baixa a build **Vulkan** do
llama.cpp — cobre os três fabricantes sem exigir instalar o CUDA Toolkit.

**Com fallback automático, não uma aposta.** A detecção de GPU é melhor esforço (consulta os
controladores de vídeo do Windows e ignora o adaptador de software que toda máquina virtual
tem). Se, mesmo assim, a build Vulkan não conseguir subir — driver incompatível, GPU
diferente do esperado —, o app **percebe sozinho, reinstala em CPU e tenta de novo**, uma
única vez. O motor local nunca fica morto em silêncio por causa disso.

## Ressalvas de sempre

Esta mudança ainda não foi medida em hardware Windows real — é lógica testada (13 testes
novos cobrindo seleção de build, detecção de GPU e o fallback de ponta a ponta), não
performance comprovada. O build do Windows continua sendo cross-compilado no Mac e sem teste
em máquina física; o DMG segue sem notarização.
