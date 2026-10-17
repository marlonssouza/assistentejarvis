# GitHub no Jarvis — integração inicial somente leitura

A ferramenta `github_get_file_contents(owner, repo, path, ref="")` lê arquivos e lista diretórios pelo servidor MCP oficial do GitHub. Caminho vazio lista a raiz. `ref` opcional seleciona branch, tag ou commit; omitido, usa a branch padrão do repositório.

Exemplos na conversa:

- “Leia LICENSE de github/github-mcp-server e diga qual é a licença.”
- “Liste os arquivos da raiz do repositório github/github-mcp-server.”
- “Leia pyproject.toml do repositório DONO/PROJETO.”

Reinicie o aplicativo e o backend do Jarvis, se já estavam abertos quando a integração foi instalada. O launcher compacto pode reutilizar um backend existente; fechar apenas a janela pode não recarregar o servidor.

## Autenticação

Usa `gh auth token --hostname github.com`, capturando o resultado somente em memória. É necessário ter `gh` no PATH e estar autenticado com `gh auth login` sob o usuário que executa o Jarvis. Credencial opcional dedicada: variável `JARVIS_GITHUB_TOKEN`; não forneça pelo chat nem inclua em arquivos versionados. Não existe token no arquivo de configuração MCP.

A ferramenta não pode escolher URL, cabeçalhos ou nome de operação do servidor. O endpoint é fixo em `https://api.githubcopilot.com/mcp/readonly`, com `X-MCP-Readonly: true` e somente `get_file_contents`. O acesso de leitura acompanha as permissões da credencial; os testes reais cobriram apenas repositório público.

## Limites desta etapa

- Não cria issues, branches ou pull requests; não escreve em repositórios.
- Arquivos em recursos textuais MCP são extraídos; imagens e blobs binários não são enviados ao modelo.
- Conteúdo limitado a 6.000 caracteres por chamada, com `truncated` e tamanho original. Não considerar o restante como lido.
- Não há sessão persistente ou cache de conteúdo nesta etapa. Cada consulta abre e encerra uma sessão; resultados não ficam obsoletos por cache.
- Operação MCP limitada a 25 segundos, com limite externo de 30 segundos; obtenção de credencial tem limite de 5 segundos. Interrupção verifica o cancelamento antes e depois da leitura; a leitura em curso pode terminar em segundo plano até o limite, sem executar ações adicionais.
- Erros de conexão são resumidos sem propagar cabeçalhos ao modelo. Erros retornados pela ferramenta (por exemplo, arquivo inexistente) mantêm `is_error=true`.
- SDK fixado em `mcp==1.30.0`, validado com o cliente existente. O SDK 2.x requer adaptação.

## Desativar e restaurar

Para desativar a consulta GitHub, defina `JARVIS_GITHUB_ENABLED=false` no ambiente e reinicie o backend. `JARVIS_MCP_ENABLED=false` também bloqueia a integração.

Arquivos anteriores preservados em `C:\Jarvis\jarvis_cross_platform\backups\github-mcp-20261016-215341`. Para restauração do código anterior, copie `jarvis/hands.py`, `jarvis/brain.py`, `jarvis/mcp.py`, `pyproject.toml` e `requirements.txt` desse backup para os mesmos caminhos no projeto e reinicie o backend. Os novos arquivos `jarvis/github_mcp.py` e `tests/test_github_mcp.py` pertencem a esta integração. A instalação adicionou 10 pacotes e não atualizou os pacotes existentes; desativar a integração não exige desinstalá-los.

## Validação da instalação

Suíte completa: 343 testes executados, 341 aprovados e 2 ignorados. Inclui 11 novos testes de extração de recursos, limite de conteúdo, validação de parâmetros, restrição de endpoint/ferramenta, tratamento de credenciais, sanitização de erros, desativação e cancelamento antes da consulta. `uv pip check`: 94 pacotes compatíveis.

Leituras autenticadas pelo handler real: LICENSE em 4,40 s; arquivo inexistente em 3,05 s; raiz em 3,76 s (listagem truncada e explicitamente sinalizada). Fluxo completo com OllamaChat, todas as ferramentas e instruções estáticas do Jarvis: Qwen 27,22 s e Llama 37,11 s; ambos escolheram github_get_file_contents, leram LICENSE e identificaram MIT. Não foi usada memória pessoal, histórico persistido, microfone ou síntese de voz nesses testes. Tempos são observações de uma tentativa por cenário, não garantia de latência.
