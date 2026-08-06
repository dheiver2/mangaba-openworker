# Mangaba 0.1.33

> Primeira release publicada desde a **v0.1.7**. Reúne 26 versões de trabalho — quem estava
> na 0.1.7 recebe tudo abaixo de uma vez. Atualização automática restaurada (o manifesto
> `latest.json` volta a ser publicado junto da release).

## Destaques desta versão (0.1.33)
- **Primeira resposta mais rápida nos fluxos locais.** Os fluxos que rodam só na máquina
  (sem conector/MCP) agora iniciam numa família de agente enxuta ("Negócio", ~20 ferramentas
  no lugar de ~47). No modelo local em CPU isso corta milhares de tokens do *prefill* da
  primeira mensagem — que é o que se sente como "demora".
- **Automação agendada que depende de MCP agora funciona.** Corrigido um bug em que a
  execução agendada headless rodava sem as ferramentas de MCP/conector — um fluxo que lê
  Granola/Intercom no horário marcado falhava em silêncio. Agora recebe a mesma superfície
  de ferramentas da sessão ao vivo.
- **Conectar por uma via satisfaz a outra.** Nove serviços existem como conector nativo *e*
  como servidor MCP (Linear, HubSpot, monday, Asana, Attio, Close, ClickUp, Notion, Stripe).
  O card do fluxo parava de pedir a mesma conta duas vezes: ter qualquer uma das vias
  conectada já conta como pronto.
- **Descoberta na jornada.** O Mangaba Local ganha selo "Grátis" na galeria de provedores
  (é o único caminho sem chave e sem custo), e Conectores/MCP e Automações agora têm atalho
  dentro de Configurações — onde as pessoas os procuram.

## Provedor Mangaba-Nordeste-30B
- Provedor de IA **agêntico pleno** servido no Brasil (Nossa Telecom/AL), OpenAI-compatível.
- **Verificado por teste**, não por rótulo: tool calling estruturado, retorno de `role:tool`,
  streaming, `tool_calls` dentro do streaming e chamadas em paralelo — todos passando.
- Janela de contexto **real de 32.768 tokens** (medida e alinhada com o que o gateway anuncia).
- Logo própria, endpoint pré-preenchido, erro legível quando falta chave.
- Trata o **429 de ritmo** do gateway distinguindo de falta de crédito.

## Primeiro uso e motor local
- App abre direto, sem tela de login (protegido pelo token do sidecar).
- **Mangaba Local** como llama.cpp embutido com tool calling nativo; baixa o modelo adequado
  à máquina e dimensiona o contexto pela memória disponível.
- Card mostra "✓ Conectado" quando há modelo no disco; erro do motor vira diagnóstico com os
  dados da máquina.

## Fluxos, MCP e conectores
- Tela **"Resolver um problema"**: a pessoa escolhe a dor, não o mecanismo. "Pronto" só
  quando VERIFICADO — cadastro não conta, conexão real sim.
- Galeria de **servidores MCP** agrupada por categoria (inclui CRM e vendas — 8 servidores
  testados), HTTP-first, com selo do que exige login; ferramentas read-only rodam sem aprovação.
- Kit empresarial de **skills-padrão** semeado em toda instalação nova.
- Conectores de messaging empacotados; Mangaba Cloud removida.

## Correções e robustez
- Corrige bugs que falhavam em silêncio no Windows e macOS (motor local, guarda, compactação,
  skills, instalador que fecha o app antes de sobrescrever).
- Sincronização com o upstream OpenWorker (Skills, compactação, guarda SSRF).
- **Pipeline de release** corrigido: o manifesto de auto-update deixa de depender de memória —
  ou a release sai com ele, ou não sai.
