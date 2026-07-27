<p align="center">
  <img src="docs/assets/mangaba-logo.png" alt="mangaba.ai" width="380">
</p>

<p align="center">
  <b>IA que entrega o trabalho pronto — não só a conversa.</b><br>
  <sub>Agente de IA que roda no seu desktop, com o seu modelo e os seus dados · interface 100% em português</sub>
</p>

<p align="center">
  <a href="#instalar">Instalar</a> ·
  <a href="#como-funciona">Como funciona</a> ·
  <a href="#rodando-a-partir-do-código">Rodar do código</a> ·
  <a href="#privacidade">Privacidade</a>
</p>

---

> **Beta.** Totalmente usável e em polimento ativo. Este é um fork brasileiro do
> [OpenWorker](https://github.com/andrewyng/openworker), com a interface, os prompts e a
> documentação em **português do Brasil** — veja [Créditos](#créditos).

O Mangaba vive no seu desktop e devolve **trabalho terminado**: um documento
pronto, uma resposta no Slack com os números, a agenda organizada, a caixa de
entrada triada. Ele roda na sua máquina e não te prende a nenhum modelo — traga a
sua chave da OpenAI, Anthropic, Google, DeepSeek e afins, ou rode tudo local com o
Ollama. Seus dados só saem daqui pelo modelo e pelas integrações que **você**
escolher.

[![Como o Mangaba funciona](docs/assets/how-it-works.png)](https://mangaba.ai)

## Instalar

### Com Docker (recomendado)

Um container só: o servidor Python serve a própria interface.

```shell
docker compose up -d
```

Abra http://127.0.0.1:8765, crie a senha e pronto. A porta é publicada apenas em
`127.0.0.1` — o agente nunca fica exposto na rede local. Os dados (senha,
conversas, segredos de conectores) persistem no volume `mangaba-dados`, e a
pasta `~/Mangaba` da máquina fica visível ao agente.

**Atalho na Área de Trabalho (via Docker + navegador):**

```shell
# macOS
bash packaging/instalar_atalho_docker.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File packaging\instalar_atalho_docker.ps1
```

Cria um atalho com o logo mangaba.ai: dois cliques sobem o Docker Desktop se
preciso, rodam o compose e abrem o navegador em `http://127.0.0.1:8765`.
Requer o [Docker Desktop](https://www.docker.com/products/docker-desktop/).

### App desktop nativo (sem Docker)

O app nativo (Tauri) é distribuído pelas releases —
**não assinado**: no macOS, clique com o botão direito ▸ Abrir na primeira vez
(o Gatekeeper bloqueia apps sem assinatura Apple); no Windows, o SmartScreen
avisa — clique em "Mais informações" ▸ "Executar assim mesmo".

- **Windows (x64)** —
  [`Mangaba_0.1.10_x64-setup.exe`](https://github.com/dheiver2/mangaba-openworker/releases/download/v0.1.10/Mangaba_0.1.10_x64-setup.exe)
  ([release v0.1.10](https://github.com/dheiver2/mangaba-openworker/releases/tag/v0.1.10)).
  Gerado por cross-compile a partir do macOS
  (`packaging/build_windows_cross.sh`), porque não há máquina nem runner Windows
  disponível. O sidecar Python vem do runtime *embeddable* oficial do Windows
  com wheels `win_amd64` — não do PyInstaller, que exigiria rodar em Windows.

  > **Use a v0.1.10.** A v0.1.8 nem abre (`libstdc++-6.dll não foi encontrado`) e
  > a v0.1.9 abre mas não conecta ao sidecar.

- **macOS (Apple Silicon)** —
  [`Mangaba_0.1.8_aarch64.dmg`](https://github.com/dheiver2/mangaba-openworker/releases/download/v0.1.8/Mangaba_0.1.8_aarch64.dmg)
  ([release v0.1.8](https://github.com/dheiver2/mangaba-openworker/releases/tag/v0.1.8)),
  gerado via `packaging/build_dmg.sh`. A v0.1.9 corrigiu só o lado Windows, então
  o `.dmg` da v0.1.8 continua sendo o atual.

Quem tiver uma máquina Windows pode gerar um build nativo (com PyInstaller e
instalador Unicode) usando `packaging/build_windows.ps1`.

Abra o app, crie a senha de acesso, aponte para um modelo (ou para o Ollama) e
peça algo de verdade.

## Como funciona

1. Diga o **resultado** que você quer — "prepare um resumo do cliente",
   "desembarace minha agenda", "veja como está o release entre o Jira e o GitHub".
2. Ele divide a tarefa em etapas e trabalha nos seus arquivos, no terminal e nos
   apps conectados.
3. Antes de qualquer coisa séria — mandar uma mensagem, mexer na agenda, rodar um
   comando — ele pergunta, e você aprova ou redireciona.
4. Você recebe o entregável pronto, não uma lista de tarefas.

Por dentro:

```text
┌────────────────────────────────────────────────┐
│              app desktop Mangaba               │  shell nativo + interface React
├────────────────────────────────────────────────┤
│      servidor de agente local (Python)         │  motor · ferramentas · conectores (sobre aisuite)
├───────────────┬────────────────┬───────────────┤
│  seus         │  suas          │  seu          │  tudo roda com as suas chaves,
│  arquivos     │  ferramentas   │  modelo       │  na sua máquina
│  & terminal   │  40 conectores │  qualquer um  │
└───────────────┴────────────────┴───────────────┘
```

## O que ele faz

- **Entregáveis de verdade** — documentos, planilhas, relatórios e páginas web
  aparecem como arquivos prontos para abrir e compartilhar.
- **Trabalha pelo Slack** — mencione o `@Mangaba` num canal: a sessão abre no seu
  desktop, o trabalho acontece com as suas ferramentas e a resposta volta na thread.
- **Usa suas ferramentas do dia a dia** — 40 conectores, entre eles GitHub, Slack,
  Jira, Notion, Linear, HubSpot, Outlook, monday.com, Gmail e Google Agenda, além
  do seu **terminal e arquivos locais**. Qualquer ferramenta que fale
  [MCP](https://modelcontextprotocol.io/) também entra, com controle por ferramenta.
- **Roda no horário** — automações para o que é recorrente: briefing matinal,
  relatório semanal, vigília num canal. Cada execução vira uma conversa com
  transcrição completa.
- **Pergunta antes de agir** — escritas, envios e comandos de shell passam por
  aprovação. Rodando sem supervisão, os pedidos ficam na caixa de entrada em vez
  de o agente decidir sozinho.

## Segurança e acesso

O app abre atrás de uma **senha local**. O token do sidecar prova que a chamada
saiu desta máquina; a senha prova que é a **pessoa** certa nela.

- Guardada como hash PBKDF2-HMAC-SHA256 (salt de 16 bytes, 480 mil iterações) em
  `<state-dir>/passcode.json`, com permissão `0600`. A senha em claro nunca é
  gravada nem registrada em log.
- As sessões vivem **só em memória** e duram 12h: reiniciar o servidor exige a
  senha de novo.
- Cinco tentativas erradas bloqueiam novas tentativas por 60 segundos.
- Trocar a senha (Configurações ▸ Senha de acesso) exige a atual e derruba as
  outras sessões.

Esqueceu a senha? Apague `~/.config/mangaba/passcode.json` e o app pede uma nova
na próxima abertura.

## Escolha o seu modelo

O acesso ao modelo é seu: escolha o provedor, cole a chave, troque quando quiser.

**OpenAI · Anthropic · Google Gemini · DeepSeek · Qwen · Kimi (Moonshot) · GLM
(Z.ai) · MiniMax · Mistral · Grok (xAI)** — mais modelos de peso aberto via
**Together** e **Fireworks**, e modelos totalmente locais via **Ollama**.

A lista curada marca o que já foi verificado para trabalho com ferramentas.
Qualquer outro identificador de modelo funciona por sua conta e risco.

## Privacidade

O Mangaba é local-first. Tudo mora na sua máquina: o laço do agente, suas
conversas, os tokens dos conectores e as chaves de modelo — no armazenamento
local de segredos do app. A única peça na nuvem é um serviço pequeno que
intermedeia o OAuth dos conectores, e ele é opcional: dá para usar o app sem
entrar em conta nenhuma, conectando tudo com credenciais criadas à mão.

Além disso: filtros de privacidade removem remetentes e campos sensíveis antes de
o agente ver os resultados, e cada chamada de conector fica registrada na aba
Atividade.

## Rodando a partir do código

Pré-requisitos: Python 3.10+, Node 20+ e — para o shell desktop — o toolchain do
Rust via [rustup](https://rustup.rs/).

```shell
git clone https://github.com/dheiver2/mangaba-openworker
cd mangaba-openworker

# 1. Bootstrap único — cria o venv Python em .venv
#    (no Windows, rode pelo Git Bash ou WSL)
bash packaging/setup_dev_env.sh

# 2. Suba o servidor de agente local
.venv/bin/mangaba-server --cwd ~/algum/projeto --port 8765
#    (Windows: .venv\Scripts\mangaba-server.exe)

# 3. Em outro terminal, suba a interface
cd surfaces/gui
npm install
npm run dev        # interface no navegador, na porta do Vite
```

> Se o `python3` do sistema for anterior ao 3.10, crie o venv com uma versão mais
> nova antes do passo 1 — por exemplo `uv venv --python 3.12 .venv`.

O servidor standalone cria um token por execução em
`<state-dir>/sidecar-8765.token`; o Vite lê esse arquivo (de leitura restrita ao
usuário) ao iniciar. Para chamadas diretas à API, mande o valor no cabeçalho
`X-Mangaba-Token` — e, se já houver senha configurada, a sessão em
`X-Mangaba-Session`. O app desktop usa um token em memória e nunca o grava em
disco.

Para rodar o app desktop completo em vez da interface no navegador, troque o
passo 3 por `npm run tauri dev` (dentro de `surfaces/gui/`) — o shell Tauri abre a
janela e supervisiona o servidor.

### Landing page

A página de apresentação é estática e autocontida em `surfaces/landing/`:

```shell
python3 -m http.server 4321 --directory surfaces/landing
```

Quando o app está aberto na mesma máquina, os botões da landing viram
"Abrir o Mangaba" e levam direto para a sessão.

### Testes

```shell
.venv/bin/pytest                      # backend Python
cd surfaces/gui && npm test           # unidade da interface (vitest)
cd surfaces/gui && npm run e2e        # ponta a ponta com rede mockada (Playwright)
```

Estado atual: **899 testes Python** e **79 de unidade** passando. Na suíte e2e,
**131 passam** e cerca de 31 ainda esperam textos em inglês — dívida da tradução
das assertivas, não regressão de comportamento. A jornada de entrada tem
cobertura dedicada em `surfaces/gui/e2e/login-journey.spec.ts`.

Os pacotes desktop saem de `packaging/build_dmg.sh` e
`packaging/build_windows.ps1`.

## Estrutura do repositório

| Diretório | O que tem dentro |
|---|---|
| `mangaba/` | Backend Python — motor do agente, provedores de modelo, conectores, cliente MCP, memória, automações, senha local |
| `surfaces/gui/` | App desktop — interface React + shell Tauri que supervisiona o servidor |
| `surfaces/landing/` | Landing page estática (PT-BR, responsiva, tema claro/escuro) |
| `stt/` | Sidecar de fala para texto (Rust), para a entrada de voz |
| `darktok/` | App experimental estilo TikTok do ecossistema Mangaba |
| `packaging/` | Builds de instalador (DMG do macOS, Windows), manifesto de atualização, bootstrap de desenvolvimento |
| `docs/` | Especificações de design e registros de decisão |
| `tests/` | Suíte de testes do backend |

## Créditos

Este projeto é um fork do [**OpenWorker**](https://github.com/andrewyng/openworker),
de Andrew Ng e colaboradores, rebrandizado como Mangaba e traduzido para o
português do Brasil. Todo o crédito pela arquitetura original é deles.

O motor é construído sobre o [**aisuite**](https://github.com/andrewyng/aisuite),
biblioteca Python leve que oferece uma API unificada de chat-completions entre
provedores de LLM, além de uma camada de agentes com ferramentas, toolkits e
suporte a MCP. Se você quer montar o seu próprio arcabouço de agente em vez de
usar este, comece por lá.

## Licença

MIT — veja [LICENSE](LICENSE).
