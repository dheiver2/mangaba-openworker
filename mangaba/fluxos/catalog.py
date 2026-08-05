"""Catálogo de problemas do dia a dia e os fluxos agênticos que os resolvem.

DADO, não código — no mesmo padrão de `mcp/catalog.py`, `skills/defaults.py` e
`connectors/descriptors.py`. A UI lista, a pessoa escolhe o problema, depois escolhe entre
os fluxos, e o app monta a configuração.

Como escrever um fluxo que presta:

- **Título diz o CAMINHO, não o problema.** O problema já está no cartão de cima. "Do CRM,
  toda segunda" e "Da planilha, quando eu pedir" resolvem a mesma dor por rotas diferentes.
- **`entrega` é o que aparece na mão da pessoa.** Não "processa os dados" — "e-mails em
  rascunho, para você revisar antes de enviar".
- **`aprovacao` é honestidade sobre o risco.** Fluxo que manda mensagem para cliente ou
  mexe em dado externo NUNCA roda sem aprovação, e o cartão diz isso antes do clique.
- **Peça listada é peça verificada.** O resolvedor cruza estas listas com o que está
  instalado e autenticado; declarar peça que o fluxo não usa produz "pronto" mentiroso.
"""

from __future__ import annotations

from typing import Any, Optional


def _fluxo(
    id: str,
    titulo: str,
    resumo: str,
    *,
    entrega: str,
    skills: Optional[list[str]] = None,
    mcps: Optional[list[str]] = None,
    conectores: Optional[list[str]] = None,
    agendado: Optional[str] = None,
    modelo: str = "qualquer",
    aprovacao: bool = True,
    prompt: str = "",
) -> dict[str, Any]:
    """Um caminho para resolver o problema.

    `modelo`: "qualquer" (qualquer provedor agêntico serve), "local" (roda sem nuvem — para
    dado que não pode sair da máquina) ou "forte" (pede modelo de ponta; o resultado degrada
    de verdade num modelo pequeno).
    """
    return {
        "id": id,
        "titulo": titulo,
        "resumo": resumo,
        "entrega": entrega,
        "skills": skills or [],
        "mcps": mcps or [],
        "conectores": conectores or [],
        "agendado": agendado,
        "modelo": modelo,
        "aprovacao": aprovacao,
        "prompt": prompt,
    }


PROBLEMAS: list[dict[str, Any]] = [
    # -- Financeiro -----------------------------------------------------------------
    {
        "id": "cobrar-atrasados",
        "titulo": "Cobrar quem está atrasado",
        "dor": "Toda semana alguém puxa a lista de vencidos e escreve e-mail por e-mail — "
               "e quando a semana aperta, ninguém cobra.",
        "area": "Financeiro",
        "fluxos": [
            _fluxo(
                "cobranca-crm-semanal",
                "Do CRM, toda segunda de manhã",
                "Lê os vencidos no CRM, separa por tempo de atraso e escreve uma cobrança "
                "para cada — tom mais firme conforme o atraso cresce.",
                entrega="E-mails em rascunho, agrupados por faixa de atraso, para você revisar",
                skills=["cobranca-inadimplencia", "email-profissional"],
                conectores=["hubspot", "gmail"],
                agendado="Segunda-feira, 9h",
                prompt="Liste no CRM os títulos vencidos, agrupe por faixa de atraso "
                       "(1-15, 16-30, 31+ dias) e escreva uma cobrança para cada cliente "
                       "seguindo a skill de cobrança. Deixe tudo em rascunho.",
            ),
            _fluxo(
                "cobranca-planilha",
                "Da planilha, quando eu pedir",
                "Você joga a planilha de contas a receber na conversa e ele faz o resto. "
                "Sem CRM, sem integração.",
                entrega="Um arquivo com as mensagens prontas, uma por cliente",
                skills=["cobranca-inadimplencia", "limpeza-planilha"],
                prompt="Leia a planilha de contas a receber que vou anexar, identifique os "
                       "vencidos e escreva uma mensagem de cobrança para cada um.",
            ),
            _fluxo(
                "cobranca-whatsapp",
                "Por WhatsApp, com aprovação uma a uma",
                "Para quem cobra por mensagem e não por e-mail. Cada envio passa por você.",
                entrega="Mensagens curtas prontas para enviar, uma aprovação por cliente",
                skills=["cobranca-inadimplencia"],
                conectores=["whatsapp"],
                prompt="A partir da lista de vencidos, escreva mensagens curtas de cobrança "
                       "para WhatsApp — cordiais, com o valor e o vencimento.",
            ),
        ],
    },
    {
        "id": "fechar-o-mes",
        "titulo": "Fechar o mês",
        "dor": "Os números estão espalhados em planilhas e no banco, e o resumo para a "
               "diretoria é montado na mão toda vez.",
        "area": "Financeiro",
        "fluxos": [
            _fluxo(
                "fechamento-completo",
                "Dossiê completo, com gráficos e comparativo",
                "Consolida as planilhas do mês, calcula os indicadores com script e monta "
                "o documento para a diretoria.",
                entrega="Dossiê em markdown com resumo, tabelas e recomendações",
                skills=["analise-financeira", "dossie-executivo", "limpeza-planilha"],
                modelo="forte",
                prompt="Consolide as planilhas financeiras do mês, calcule margem, fluxo de "
                       "caixa e os principais indicadores, e monte o dossiê executivo.",
            ),
            _fluxo(
                "fechamento-local",
                "Sem sair da máquina",
                "Mesma análise, com modelo local. Nenhum número da empresa vai para a nuvem.",
                entrega="Dossiê em markdown, gerado inteiramente offline",
                skills=["analise-financeira", "dossie-executivo"],
                modelo="local",
                prompt="Analise as planilhas financeiras do mês e monte o dossiê executivo. "
                       "Use apenas ferramentas locais.",
            ),
        ],
    },
    # -- Vendas ---------------------------------------------------------------------
    {
        "id": "responder-proposta",
        "titulo": "Responder pedido de proposta",
        "dor": "Chega um pedido de orçamento e a proposta leva dois dias para sair, "
               "porque começa do zero toda vez.",
        "area": "Vendas",
        "fluxos": [
            _fluxo(
                "proposta-do-crm",
                "Puxando o histórico do cliente no CRM",
                "Lê o que já foi conversado e proposto antes, e escreve a proposta nova "
                "coerente com esse histórico.",
                entrega="Proposta estruturada: escopo, entregáveis, prazo e investimento",
                skills=["proposta-comercial"],
                conectores=["hubspot"],
                prompt="Puxe o histórico deste cliente no CRM e monte uma proposta comercial "
                       "seguindo a skill, coerente com o que já foi conversado.",
            ),
            _fluxo(
                "proposta-do-zero",
                "A partir do que o cliente pediu",
                "Você cola o pedido — e-mail, transcrição de call, mensagem — e ele monta.",
                entrega="Proposta estruturada, pronta para revisar e enviar",
                skills=["proposta-comercial"],
                prompt="A partir do pedido que vou colar, monte uma proposta comercial "
                       "seguindo a skill.",
            ),
            _fluxo(
                "proposta-com-pesquisa",
                "Pesquisando o cliente antes de escrever",
                "Antes de propor, pesquisa a empresa na web para ajustar linguagem, porte "
                "e argumentos.",
                entrega="Proposta com um parágrafo de contexto sobre o cliente",
                skills=["proposta-comercial", "pesquisa-mercado"],
                prompt="Pesquise esta empresa na web, entenda o porte e o setor, e então "
                       "monte a proposta comercial ajustada ao perfil dela.",
            ),
        ],
    },
    # -- Gestão ---------------------------------------------------------------------
    {
        "id": "status-do-time",
        "titulo": "Saber como o time está",
        "dor": "O relatório de status depende de alguém lembrar de escrever — e a versão "
               "que chega na reunião já está desatualizada.",
        "area": "Gestão",
        "fluxos": [
            _fluxo(
                "status-das-tarefas",
                "Do quadro de tarefas, toda sexta",
                "Lê o que mudou na semana no Linear ou no monday e escreve o status sozinho.",
                entrega="Relatório com feito, em andamento, bloqueios e próximos passos",
                skills=["relatorio-status-semanal"],
                conectores=["linear", "monday"],
                agendado="Sexta-feira, 17h",
                prompt="Leia o que mudou nesta semana no quadro de tarefas e escreva o "
                       "relatório de status semanal seguindo a skill.",
            ),
            _fluxo(
                "status-no-slack",
                "Do quadro direto para o canal do Slack",
                "Mesmo relatório, publicado no canal — o time lê sem ninguém repassar.",
                entrega="Mensagem no canal, depois da sua aprovação",
                skills=["relatorio-status-semanal"],
                conectores=["linear", "slack"],
                agendado="Sexta-feira, 17h",
                prompt="Monte o relatório de status da semana a partir do quadro de tarefas "
                       "e publique no canal combinado.",
            ),
        ],
    },
    {
        "id": "reuniao-vira-tarefa",
        "titulo": "Reunião virar tarefa de verdade",
        "dor": "A reunião acaba com decisões combinadas, mas ninguém escreve — e na semana "
               "seguinte metade não aconteceu.",
        "area": "Gestão",
        "fluxos": [
            _fluxo(
                "ata-para-tarefas",
                "Da gravação para o quadro de tarefas",
                "Transforma as notas ou a transcrição em ata, e cria as tarefas com "
                "responsável e prazo.",
                entrega="Ata estruturada mais as tarefas criadas no quadro",
                skills=["ata-de-reuniao"],
                mcps=["granola"],
                conectores=["linear"],
                prompt="Leia as notas da reunião, monte a ata seguindo a skill e crie as "
                       "tarefas decididas no quadro, com responsável e prazo.",
            ),
            _fluxo(
                "ata-simples",
                "Só a ata, a partir das minhas notas",
                "Você cola as anotações e recebe a ata organizada. Sem integração nenhuma.",
                entrega="Ata com decisões, responsáveis, prazos e próximos passos",
                skills=["ata-de-reuniao"],
                prompt="A partir das notas que vou colar, monte a ata da reunião seguindo "
                       "a skill.",
            ),
        ],
    },
    # -- Marketing ------------------------------------------------------------------
    {
        "id": "conteudo-nas-redes",
        "titulo": "Manter as redes com conteúdo",
        "dor": "Todo mundo concorda que precisa publicar, e o post acaba saindo às pressas "
               "ou não sai.",
        "area": "Marketing",
        "fluxos": [
            _fluxo(
                "posts-da-semana",
                "Lote da semana, toda segunda",
                "Gera os posts da semana a partir dos temas do momento no seu setor.",
                entrega="Posts prontos para LinkedIn e Instagram, em rascunho",
                skills=["post-redes-sociais", "pesquisa-mercado"],
                agendado="Segunda-feira, 8h",
                prompt="Pesquise o que está em pauta no meu setor e gere os posts da semana "
                       "seguindo a skill de redes sociais.",
            ),
            _fluxo(
                "post-de-um-tema",
                "Um post, de um tema que eu der",
                "Você diz o assunto, ele escreve. Rápido, sob demanda.",
                entrega="Um post por rede, adaptado ao formato de cada uma",
                skills=["post-redes-sociais"],
                prompt="Escreva um post sobre o tema que vou dar, seguindo a skill de "
                       "redes sociais.",
            ),
        ],
    },
    {
        "id": "campanha-vale-a-pena",
        "titulo": "Saber se a campanha vale o que custa",
        "dor": "O painel de cada plataforma mostra número diferente, e ninguém compara "
               "canal com canal na mesma régua.",
        "area": "Marketing",
        "fluxos": [
            _fluxo(
                "analise-de-campanha",
                "Da exportação das plataformas",
                "Junta as exportações num só lugar e calcula custo por lead, custo por "
                "venda e retorno — tudo por script, nunca de cabeça.",
                entrega="Plano de mídia com tabela por canal e realocação de verba sugerida",
                skills=["analise-financeira", "dossie-executivo"],
                modelo="forte",
                prompt="Analise as exportações das campanhas, calcule CPL, CAC e ROAS por "
                       "canal com script Python e monte o plano de mídia.",
            ),
        ],
    },
    # -- Jurídico e operações -------------------------------------------------------
    {
        "id": "contrato-antes-de-assinar",
        "titulo": "Ler o contrato antes de assinar",
        "dor": "O contrato chega, todo mundo tem pressa, e ele acaba assinado sem alguém "
               "ler as cláusulas que doem depois.",
        "area": "Jurídico",
        "fluxos": [
            _fluxo(
                "revisao-de-contrato",
                "Apontando cláusulas de risco",
                "Lê o contrato e destaca multa, rescisão, exclusividade, foro e o que mais "
                "costuma pesar contra você.",
                entrega="Lista de pontos de atenção, com a cláusula citada e o porquê",
                skills=["revisao-contrato"],
                modelo="forte",
                prompt="Leia o contrato que vou anexar e aponte as cláusulas de risco "
                       "seguindo a skill de revisão.",
            ),
            _fluxo(
                "revisao-local",
                "Sem o contrato sair da máquina",
                "Mesma revisão com modelo local — para contrato que não pode subir para "
                "servidor de terceiro.",
                entrega="Lista de pontos de atenção, gerada offline",
                skills=["revisao-contrato"],
                modelo="local",
                prompt="Leia o contrato anexado e aponte as cláusulas de risco. Use apenas "
                       "o modelo local.",
            ),
        ],
    },
    {
        "id": "planilha-bagunçada",
        "titulo": "Arrumar planilha que chegou bagunçada",
        "dor": "A planilha vem do cliente ou do sistema com formato errado, duplicata e "
               "coluna faltando — e arrumar na mão leva a manhã inteira.",
        "area": "Operações",
        "fluxos": [
            _fluxo(
                "limpeza-com-relatorio",
                "Limpar e dizer o que mudou",
                "Corrige formato, remove duplicata, valida os dados e devolve um resumo do "
                "que foi alterado.",
                entrega="Planilha limpa mais um relatório do que mudou e por quê",
                skills=["limpeza-planilha"],
                prompt="Limpe a planilha que vou anexar seguindo a skill, e me diga o que "
                       "foi alterado.",
            ),
        ],
    },
    # -- Atendimento ----------------------------------------------------------------
    {
        "id": "caixa-de-entrada-cheia",
        "titulo": "Dar conta da caixa de entrada",
        "dor": "Chegam dezenas de mensagens por dia e as urgentes se perdem no meio das "
               "que podiam esperar.",
        "area": "Atendimento",
        "fluxos": [
            _fluxo(
                "triagem-diaria",
                "Triagem toda manhã, com rascunho de resposta",
                "Lê o que chegou, separa por urgência e já deixa a resposta escrita para "
                "as que dá para responder na hora.",
                entrega="Lista priorizada e rascunhos prontos, nada enviado sem você",
                skills=["email-profissional"],
                conectores=["gmail"],
                agendado="Todo dia, 8h",
                prompt="Leia os e-mails não lidos, separe por urgência e escreva rascunhos "
                       "de resposta para os que dão para responder direto.",
            ),
            _fluxo(
                "triagem-suporte",
                "Do sistema de tickets",
                "Para quem atende por Intercom em vez de e-mail.",
                entrega="Tickets priorizados com sugestão de resposta",
                skills=["email-profissional"],
                mcps=["intercom_mcp"],
                prompt="Leia os tickets abertos, priorize por urgência e sugira uma resposta "
                       "para cada.",
            ),
        ],
    },
]


FLUXOS: dict[str, dict[str, Any]] = {
    f["id"]: {**f, "problema_id": p["id"], "problema": p["titulo"]}
    for p in PROBLEMAS
    for f in p["fluxos"]
}


def problema_por_id(id: str) -> Optional[dict[str, Any]]:
    return next((p for p in PROBLEMAS if p["id"] == id), None)


def fluxo_por_id(id: str) -> Optional[dict[str, Any]]:
    return FLUXOS.get(id)


def listar_problemas() -> list[dict[str, Any]]:
    """Os problemas com seus fluxos, sem o estado de prontidão (que o manager resolve)."""
    return [dict(p) for p in PROBLEMAS]
