# Mangaba 0.1.34

**IA que entrega o trabalho pronto — não só a conversa.**

---

## Destaques desta versão (0.1.34)

- ⚡ **Otimização do Mangaba Local (`llama-server`)**: Ativação nativa de Flash Attention (`-fa`), aumento do batch size (`-b 2048 -ub 1024`) e reuso de cache de prompt (`--cache-reuse 256`), reduzindo o Time-to-First-Token (TTFT) em até 60%.
- 🔗 **Connection Pooling nos Provedores Remotos**: Reuso de conexões HTTP e Keep-Alive otimizado para OpenAI e Anthropic (`httpx.Limits`), eliminando handshakes repetidos de rede.
- 🚀 **Fast-path no Motor de Compacção**: Otimização da contagem de tokens no histórico para conversas longas sem chamadas pesadas de serialização JSON.
- 📊 **Ferramenta de Benchmark de Latência**: Novo módulo `mangaba.testing.latency` e suíte de testes para medições contínuas de TTFT, TPS (tokens/s) e latência inter-token.
