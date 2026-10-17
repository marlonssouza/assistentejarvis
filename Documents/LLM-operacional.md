# Ollama local no Jarvis

Servidor web encerrado a pedido do usuário; não reiniciado após a migração.
Principal: qwen2.5:7b-instruct-q4_K_M. Alternativa: llama3.1:8b.
API nativa: http://127.0.0.1:11434/api/chat. Sem chave de API.
Integrações e configuração OpenCode/Zen/OpenAI removidas do aplicativo.
O OpenCode instalado na máquina não foi desinstalado nem suas credenciais alteradas.
Gemini permanece opcional; não participa da cadeia local padrão.

Planejamento extra desligado para reduzir chamadas. Confirmações por ação
continuam de acordo com JARVIS_CONFIRM_MODE. Após uma ferramenta ser executada,
o pedido não é repetido em outro modelo. Antes da primeira ferramenta, falhas
de modelo, memória, conexão ou timeout tentam o próximo modelo.

Ollama mantém o modelo por 5 minutos; contexto 8192, lote 128, saída até 384 tokens.
Pode ajustar esses valores no .env conforme RAM/VRAM e tamanho das respostas.
O histórico e a memória do usuário são preservados. Modelos não foram baixados,
removidos ou modificados. Para iniciar manualmente: python main.py --ui.

## Validação

310 testes executados: 308 aprovados, 2 ignorados. Testes reais com o catálogo de 49 ferramentas e leitura da hora:
- Qwen: conversa inicial 19,07 s; chamada get_datetime 1,42 s; resposta ao resultado 1,91 s.
- Llama: chamada get_datetime 13,76 s; resposta ao resultado 2,41 s.
Esses tempos variam com carregamento, RAM/VRAM e outros aplicativos.
O teste não abriu aplicativos nem gravou conversa na memória do usuário.
