"""Skills-padrão empresariais semeadas no primeiro uso (SessionManager).

Embutidas como dados Python (não arquivos .md) para o PyInstaller as recolher
automaticamente no sidecar Windows/macOS. O SkillStore.seed_defaults() as escreve
em state_dir()/skills uma vez; edições e remoções do usuário são preservadas.
"""

from __future__ import annotations

DEFAULT_SKILLS: list[dict[str, str]] = [
    {
        "name": 'email-profissional',
        "description": 'Redigir e-mails profissionais em PT-BR (follow-up, proposta, cobrança cordial, resposta a cliente)',
        "instructions": '1. Pergunte (ou infira do contexto) o objetivo, o destinatário e o tom desejado (formal, cordial, firme).\n2. Escreva um e-mail claro e objetivo em português do Brasil: assunto direto, saudação, corpo em 2–4 parágrafos curtos, call-to-action explícito e assinatura.\n3. Se houver dados/números, confira com um cálculo via shell — nunca invente valores.\n4. NUNCA envie sozinho. Entregue o rascunho para revisão; só envie (via conector de e-mail) depois de aprovação explícita.\n5. Ofereça 1 variação de tom quando fizer sentido (ex.: mais formal x mais próxima).',
    },
    {
        "name": 'ata-de-reuniao',
        "description": 'Transformar notas ou transcrição de reunião em ata com decisões, responsáveis e prazos',
        "instructions": '1. Leia as notas/transcrição fornecidas (arquivo ou texto colado).\n2. Produza uma ata em markdown, salva como artefato, com: Participantes; Pauta; Decisões tomadas; Itens de ação (tabela com Tarefa | Responsável | Prazo); Pontos em aberto.\n3. Seja fiel — não invente decisões nem responsáveis que não estejam nas notas; marque como "(não definido)" o que faltar.\n4. Feche com um resumo de 3 bullets do que foi acordado.',
    },
    {
        "name": 'relatorio-status-semanal',
        "description": 'Relatório semanal de status padronizado: feito, em andamento, bloqueios e próximos passos',
        "instructions": '1. Reúna as fontes (arquivos, conectores como GitHub/Jira/Slack se disponíveis, ou o que o usuário fornecer).\n2. Gere um relatório em markdown (artefato) com as seções: ✅ Concluído; 🔄 Em andamento; ⛔ Bloqueios/riscos; ➡️ Próximos passos; e uma linha de destaque da semana.\n3. Números vêm de cálculo/consulta real, nunca de estimativa de cabeça.\n4. Mantenha conciso — bullets curtos, no máximo uma página.',
    },
    {
        "name": 'analise-financeira',
        "description": 'Analisar DRE, fluxo de caixa ou balancete e calcular indicadores contábeis, sem inventar números',
        "instructions": '1. Comece com todo_write listando as etapas.\n2. Leia o arquivo de dados (CSV/xlsx). Se o dado tiver inconsistência (ex.: balancete que não fecha), REPORTE honestamente em vez de forçar números.\n3. Calcule os indicadores com um script Python via shell — nunca aritmética de cabeça. Cubra, quando aplicável: liquidez corrente e seca, margem bruta e líquida, EBITDA, ROE, grau de endividamento, capital de giro.\n4. Gere um parecer em markdown (artefato) com: resumo em 3 bullets; tabela Indicador | Valor | Interpretação (bom/atenção/crítico); riscos; recomendações.\n5. Valores em R$ com separador de milhar; percentuais com 1 casa decimal. Feche com metodologia (ferramentas usadas).',
    },
    {
        "name": 'proposta-comercial',
        "description": 'Montar proposta comercial estruturada: escopo, entregáveis, prazo, investimento e condições',
        "instructions": '1. Levante (ou pergunte) cliente, dor/objetivo, escopo e orçamento-alvo.\n2. Produza uma proposta em markdown (artefato) com: Contexto/objetivo; Escopo e entregáveis; Cronograma; Investimento (tabela de itens e total em R$); Condições comerciais; Próximos passos.\n3. Some os valores com cálculo real via shell.\n4. Tom profissional e persuasivo, mas honesto — não prometa o que o escopo não cobre.',
    },
    {
        "name": 'revisao-contrato',
        "description": 'Revisar contratos apontando cláusulas de risco e pontos de atenção (não é aconselhamento jurídico)',
        "instructions": '1. Leia o contrato (arquivo).\n2. Produza um parecer de revisão em markdown (artefato) com: Resumo do objeto; Cláusulas de atenção (tabela Cláusula | Risco | Sugestão); Prazos e multas; Pontos ausentes que costumam faltar.\n3. Deixe explícito no topo: "Este é um apontamento de pontos de atenção, não substitui a análise de um advogado."\n4. Seja específico — cite o número/trecho da cláusula. Não invente cláusulas que não existam no texto.',
    },
    {
        "name": 'cobranca-inadimplencia',
        "description": 'Régua de cobrança: mensagens escalonadas e cordiais para clientes inadimplentes',
        "instructions": '1. Levante os dados do débito (valor, vencimento, dias de atraso, cliente) do arquivo ou do que for fornecido.\n2. Gere uma régua com 3 mensagens escalonadas: (a) lembrete amigável (1–5 dias); (b) cobrança firme e cordial (7–15 dias); (c) aviso formal antes de medidas (30+ dias). Cada uma pronta para e-mail e para WhatsApp/Telegram (versão curta).\n3. Valores em R$ com separador de milhar, conferidos por cálculo.\n4. NUNCA envie sozinho — entregue os textos e só dispare após aprovação.',
    },
    {
        "name": 'limpeza-planilha',
        "description": 'Limpar e padronizar planilhas (CSV/xlsx): corrigir formato, deduplicar e validar',
        "instructions": '1. Leia a planilha e descreva o que encontrou (colunas, linhas, problemas: duplicatas, formatos inconsistentes, valores faltantes).\n2. Faça a limpeza com um script Python via shell: padronizar datas/números, remover duplicatas, aparar espaços, normalizar maiúsculas/minúsculas, sinalizar linhas inválidas.\n3. Salve o resultado como novo arquivo (artefato) — nunca sobrescreva o original sem avisar.\n4. Entregue um resumo do que mudou: quantas linhas removidas/corrigidas e o que ficou pendente de decisão humana.',
    },
    {
        "name": 'pesquisa-mercado',
        "description": 'Pesquisa de mercado e de concorrentes usando busca na web e documentação (MCP), citando fontes',
        "instructions": '1. Defina as perguntas-chave da pesquisa.\n2. Use a busca na web e, quando útil, os servidores MCP de documentação (context7, deepwiki) para levantar dados — sempre citando a fonte de cada afirmação. Não invente números de mercado.\n3. Gere um relatório em markdown (artefato) com: panorama; concorrentes (tabela); oportunidades; riscos; fontes consultadas.\n4. Separe claramente FATO (com fonte) de INTERPRETAÇÃO sua.',
    },
    {
        "name": 'post-redes-sociais',
        "description": 'Criar posts para redes sociais (LinkedIn, Instagram) a partir de um tema, produto ou notícia',
        "instructions": '1. Pergunte (ou infira) a rede, o objetivo (engajamento, venda, autoridade) e o tom da marca.\n2. Gere 3 variações de post em PT-BR, cada uma com: gancho na 1ª linha, corpo curto, chamada para ação e 3–5 hashtags relevantes.\n3. Adapte o formato à rede (LinkedIn mais textual; Instagram mais direto).\n4. Nada de promessas falsas ou dados inventados sobre o produto.',
    },
]
