# Resposta pronta — "o instalador diz que é inseguro"

Texto de suporte para colar quando um usuário relatar o aviso de segurança na
instalação. Ajuste o tom à conversa; o conteúdo já está na ordem certa: acalmar,
explicar, destravar, provar.

---

Oi! Esse aviso é esperado e não é vírus — deixa eu explicar rapidinho.

O Windows e o macOS mostram esse alerta para **qualquer aplicativo novo de
desenvolvedor independente**, porque a "reputação" deles se compra com certificados
caros e se acumula com volume de downloads. É um "não conheço este publicador", não
um "encontrei algo malicioso". Antivírus nenhum acusou nada — você pode inclusive
conferir o instalador no VirusTotal, se quiser.

**Para instalar (só na primeira vez):**

- **Windows:** na janela "O Windows protegeu o computador", clique em
  **Mais informações** e depois em **Executar assim mesmo**.
- **Mac:** clique com o **botão direito** no app e escolha **Abrir** (em vez de
  clicar duas vezes), depois **Abrir** de novo. Ou vá em Ajustes do Sistema ▸
  Privacidade e Segurança ▸ **"Abrir Mesmo Assim"**.

**Como você pode verificar que o arquivo é o oficial:** cada versão é publicada em
https://github.com/dheiver2/mangaba-openworker/releases com o código-fonte aberto,
os checksums SHA-256 dos instaladores e assinatura criptográfica. E todo instalador
do Windows é instalado e executado automaticamente numa máquina Windows limpa antes
de ser anunciado.

Só um cuidado que vale para qualquer programa: baixe **somente** da página oficial
acima. Se alguém te mandou o instalador por outro canal, aí sim desconfie.

Estamos finalizando os certificados de assinatura (a notarização da Apple já está em
andamento) — em breve esse aviso some de vez. Obrigado por avisar e desculpa o susto!

---

## Contexto interno (não colar para o usuário)

- **macOS:** desde a v0.1.49 o app é assinado com Developer ID (time LM882MCDM4).
  O aviso só desaparece com a **notarização**, pendente da senha de app
  (`.ocw-notary.env`, caminho 2). Versões ≤0.1.48 eram totalmente sem assinatura.
- **Windows:** instalador sem assinatura de código. Eliminar o SmartScreen exige
  certificado (Azure Trusted Signing, ~US$ 10/mês) — decisão de custo em aberto.
- A cada release o workflow `smoke-windows` instala e executa o .exe publicado numa
  VM `windows-latest` e anexa o log do sidecar como artefato — é a base da frase
  "testado numa máquina Windows real".
