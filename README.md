# J.A.R.V.I.S. Multi-Plataforma (Windows e Linux)

Assistente pessoal em Python com conversa usando Gemini, entrada e saÃ­da de voz,
anÃ¡lise opcional da tela e automaÃ§Ãµes locais com confirmaÃ§Ã£o por risco. Identifica
automaticamente se vocÃª estÃ¡ rodando no Windows ou no Linux.

## Requisitos

- Python 3.10 ou superior.
- Uma chave da Gemini API.
- Para usar o microfone, PyAudio e um microfone disponÃ­vel. A dependÃªncia
  `SpeechRecognition[audio]` instala o suporte de Ã¡udio quando disponÃ­vel; no
  Linux, pode ser necessÃ¡rio instalar previamente os pacotes de desenvolvimento
  do PortAudio pela distribuiÃ§Ã£o.
- Para ouvir as respostas e falar, `ffplay` (recomendado), `mpg123` ou `mpv`.
  Sem um destes, no Windows o Jarvis usa o player padrÃ£o do sistema (sem
  bloquear) e no Linux a fala fica indisponÃ­vel.

## InstalaÃ§Ã£o

```bash
python -m venv .venv
```

Ative o ambiente virtual e instale as dependÃªncias:

```bash
python -m pip install -r requirements.txt
```

Para usar a **automaÃ§Ã£o de navegador** (ferramentas `browser_*`), instale tambÃ©m
o navegador do Playwright (o Chrome instalado Ã© usado quando disponÃ­vel):

```bash
python -m playwright install chromium
```

Os controles de sistema (`system_status`, `top_processes`, `set_volume`,
`set_brightness`, `power_action`) usam `psutil`, `pycaw` (Windows) e
`screen-brightness-control`, jÃ¡ incluÃ­dos em `requirements.txt`. Se algum estiver
ausente, a ferramenta responde com uma mensagem clara em vez de quebrar o assistente.

Para usar **ferramentas externas via MCP** (ferramentas `mcp_*`), o pacote `mcp`
Ã© necessÃ¡rio (`pip install mcp`). Ele Ã© importado sob demanda: sem o pacote, o
Jarvis continua funcionando normalmente, apenas as ferramentas MCP avisam que
precisam ser instaladas.

Para usar **outro provedor de LLM** (OpenAI/Ollama/LM Studio), defina
`JARVIS_PROVIDER=openai` e as variÃ¡veis `JARVIS_OPENAI_*` (veja `.env.example`).
O padrÃ£o continua sendo o Gemini.

Copie `.env.example` para `.env` e configure `GEMINI_API_KEY`:

```dotenv
GEMINI_API_KEY=sua-chave-da-gemini
JARVIS_SCREEN_CAPTURE_ENABLED=true
```

Execute o assistente:

```bash
python main.py
```

## Como conversar

- **Modo voz contÃ­nuo (padrÃ£o):** o Jarvis fica ouvindo; diga a palavra de
  ativaÃ§Ã£o (`JARVIS_WAKE_WORDS`, padrÃ£o `jarvis`, ou sÃ³ "Jarvis") e em seguida o
  pedido. Se o microfone nÃ£o estiver disponÃ­vel, ele cai automaticamente para a
  entrada por texto. Desative com `JARVIS_WAKE_ENABLED=false`.
- **Modo texto:** com `JARVIS_WAKE_ENABLED=false`, digite o pedido e pressione
  Enter. Deixar a linha em branco faz o Jarvis escutar uma fala curta.
- **Voz natural:** as respostas usam vozes neurais (`edge-tts`, grÃ¡tis e naturais
  em pt-BR). Escolha a voz em `JARVIS_TTS_VOICE` (`pt-BR-AntonioNeural` Ã© o padrÃ£o;
  tambÃ©m hÃ¡ `pt-BR-FranciscaNeural` e `pt-BR-ThalitaMultilingualNeural`) e a
  velocidade em `JARVIS_TTS_RATE`. Para voltar ao gTTS, use `JARVIS_TTS_BACKEND=gtts`.
- **Modo voz em tempo real (Live):** defina `JARVIS_LIVE_MODE=true` para falar
  naturalmente, com o modelo respondendo em Ã¡udio quase instantÃ¢neo (incluindo
  interrupÃ§Ã£o/barge-in). Ã‰ experimental e opcional; se a sessÃ£o nÃ£o puder iniciar,
  o Jarvis volta automaticamente ao modo padrÃ£o. Ajustes: `JARVIS_LIVE_MODEL`
  (padrÃ£o `gemini-3.8-live`) e `JARVIS_LIVE_VOICE` (padrÃ£o `Puck`). As ferramentas
  e o modelo de confirmaÃ§Ã£o continuam valendo. O **modo plano** tambÃ©m funciona no
  live: veja a nota na seÃ§Ã£o "MemÃ³ria, polÃ­ticas e integraÃ§Ãµes".
- **Limpar a conversa:** digite (ou fale) `limpar conversa` para apagar o
  histÃ³rico. `sair`, `desligar`, `encerrar` ou `tchau` encerram.
- A memÃ³ria da conversa e os fatos memorizados ficam em `JARVIS_MEMORY_FILE`
  (padrÃ£o `~/.jarvis/memory.json`) e sobrevivem entre sessÃµes.

## Ferramentas (o que o Jarvis pode fazer)

AÃ§Ãµes **seguras** (liberadas direto no modo graduado):

- `list_files` â€” lista nomes na pasta autorizada.
- `read_file` â€” lÃª o texto de um arquivo autorizado.
- `get_datetime` â€” data e hora atuais.
- `get_system_info` â€” sistema, versÃ£o, hostname, usuÃ¡rio, diretÃ³rio atual, home,
  Ãrea de Trabalho e pastas autorizadas.
- `open_url` â€” abre uma URL `http/https`.
- `web_search` â€” pesquisa na web (resultados atuais do Google) e resume com fontes.
- `read_webpage` â€” baixa uma pÃ¡gina e devolve o texto legÃ­vel dela.
- `search_web_browser` â€” abre o navegador (ex.: Chrome) em uma pesquisa do Google,
  mostrando a janela ao usuÃ¡rio.
- `browser_open` / `browser_read` / `browser_close` â€” navegador controlado
  (Playwright): abrir pÃ¡gina, ler o texto visÃ­vel e fechar.
- `open_special_folder` â€” abre uma pasta especial do usuÃ¡rio (Downloads, Documentos,
  Ãrea de Trabalho, Imagens, MÃºsica, VÃ­deos).
- `system_status` â€” uso atual de CPU, memÃ³ria e disco.
- `top_processes` â€” processos que mais consomem memÃ³ria.
- `generate_password` â€” gera uma senha forte e tenta copiÃ¡-la para a Ã¡rea de
  transferÃªncia.
- `set_reminder` / `list_reminders` â€” agenda, anuncia e lista lembretes.
- `list_skills` â€” lista as polÃ­ticas/skills do usuÃ¡rio.
- `mcp_list_tools` â€” lista as ferramentas dos servidores MCP configurados.
- `list_emails` / `read_email` â€” lista e lÃª os e-mails do Gmail (requer configuraÃ§Ã£o).
- `remember` / `recall` â€” memoriza fatos (com aspecto) e recupera os mais
  relevantes por busca, com histÃ³rico preservado.

AÃ§Ãµes de **risco** (pedem confirmaÃ§Ã£o):

- `open_application` â€” abre qualquer aplicativo por nome. Resolve navegadores
  (ex.: Chrome, mesmo fora do PATH), **protocolos do Windows** (ex.: "configuraÃ§Ãµes",
  "windows update", "bluetooth", "painel de controle"), pastas especiais e busca
  executÃ¡veis no PATH, no registro e nas pastas de programas.
- `capture_screen` â€” captura a tela (inteira ou uma regiÃ£o) e envia a imagem ao modelo.
- `click_at` â€” clica em uma coordenada.
- `type_text` â€” digita um texto.
- `press_hotkey` â€” pressiona um atalho permitido.
- `write_file` â€” escreve/sobrescreve um arquivo autorizado.
- `create_directory` â€” cria uma pasta em uma das pastas autorizadas.
- `browser_click` / `browser_type` â€” clica em / preenche elementos da pÃ¡gina aberta
  no navegador controlado.
- `set_volume` â€” ajusta o volume do sistema (`set`, `up`, `down`, `mute`, `unmute`).
- `set_brightness` â€” ajusta o brilho da tela (`set`, `up`, `down`).
- `power_action` â€” desliga, reinicia, suspende, hiberna ou bloqueia o computador
  (destrutiva; exige confirmaÃ§Ã£o).
- `mcp_call` â€” chama uma ferramenta de um servidor MCP externo (exige confirmaÃ§Ã£o).
- `run_command` â€” executa um comando de shell.

## Web e e-mail

- **Pesquisar e ler sites:** peÃ§a "pesquise X" (o Jarvis usa o Google e responde
  com dados atuais e fontes) ou "abra e leia o site Y" para ele baixar a pÃ¡gina e
  resumir o conteÃºdo.
- **Abrir o navegador e pesquisar:** peÃ§a "abra o Chrome e pesquise futebol". O
  Jarvis encontra o Chrome instalado (mesmo que nÃ£o esteja no PATH) e abre a
  pesquisa no Google, mostrando a janela. Para interagir com a pÃ¡gina (ler,
  clicar, preencher campos), ele usa o navegador controlado (`browser_open`,
  `browser_read`, `browser_click`, `browser_type`), que usa o Playwright.
- **Gmail:** para o Jarvis ler seus e-mails, faÃ§a isto uma vez:
  1. No Google Cloud Console, crie um projeto e habilite a **Gmail API**.
  2. Crie credenciais OAuth do tipo **App para computador** e baixe o JSON.
  3. Salve o arquivo como `credentials.json` na pasta do projeto.
  4. Rode `python gmail_setup.py` e autorize no navegador.
  O token fica em `~/.jarvis/token.json`. Depois Ã© sÃ³ pedir, por exemplo,
  "veja meus e-mails mais recentes" ou "leia o e-mail sobre X".

## Sistema e produtividade

- **Abrir pastas especiais:** "abra a minha pasta de Downloads", "abra os Documentos",
  "abra a Ãrea de Trabalho", "abra as Imagens".
- **Abrir apps e protocolos do Windows:** "abra o Chrome", "abra as configuraÃ§Ãµes",
  "abra o Windows Update", "abra o Bluetooth", "abra o painel de controle". O
  `open_application` procura no PATH, no registro e nas pastas de programas.
- **Monitorar o PC:** "como estÃ¡ o uso de memÃ³ria?" (`system_status`) e "o que estÃ¡
  consumindo mais memÃ³ria?" (`top_processes`).
- **Volumes e energia:** "coloque o volume em 30%", "diminua o brilho", "bloqueie o
  computador" â€” todas pedem confirmaÃ§Ã£o.
- **Senhas:** "gere uma senha de 20 caracteres" (`generate_password`).
- **Lembretes:** "me lembre de tomar Ã¡gua em 15 minutos" (`set_reminder`); o Jarvis
  anuncia quando chegar a hora. "quais lembretes eu tenho?" (`list_reminders`).

## MemÃ³ria, polÃ­ticas e integraÃ§Ãµes

- **MemÃ³ria estruturada:** cada fato guardado tem um **aspecto** (categoria:
  `identity`, `preference`, `directive`, `goal`, `decision`, `problem`, `knowledge`,
  `habit`, `relationship`, `belief`, `task`, `event`), data e origem. O histÃ³rico
  Ã© sempre preservado: quando vocÃª corrige um fato, o antigo Ã© marcado como
  **substituÃ­do** (supersessÃ£o) em vez de apagado. A recuperaÃ§Ã£o Ã© feita por
  **relevÃ¢ncia**, entÃ£o o Jarvis nÃ£o despeja a memÃ³ria inteira no contexto.
  Diga, por exemplo, "lembre que eu prefiro respostas curtas" e depois
  "vocÃª lembra das minhas preferÃªncias?".
- **Perfil automÃ¡tico:** a partir da memÃ³ria, o Jarvis monta um pequeno **perfil**
  (identidade, diretrizes, preferÃªncias, objetivosâ€¦) e injeta os fatos relevantes
  em cada conversa. Desative com `JARVIS_PERSONA_ENABLED=false`.
- **PolÃ­ticas/skills:** crie arquivos `.md` em `~/.jarvis/skills`
  (`JARVIS_SKILLS_DIR`) descrevendo *como* vocÃª quer que o Jarvis aja em um
  assunto (ex.: "o que conta como e-mail importante"). As polÃ­ticas relevantes sÃ£o
  aplicadas automaticamente e podem ser consultadas com `list_skills`. HÃ¡ exemplos
  prontos em `examples/skills/`. Formato:

  ```markdown
  ---
  title: Como respondo
  description: Estilo das minhas respostas
  ---
  Seja direto, sem jargÃ£o; no mÃ¡ximo 3 parÃ¡grafos.
  ```

- **Modo plano (aprovar antes de executar):** com `JARVIS_PLAN_MODE=true`, o
  Jarvis faz uma **passada de planejamento** antes de agir: ele descreve, em passos
  numerados, o que pretende fazer e quais ferramentas usarÃ¡, e **espera a sua
  aprovaÃ§Ã£o**. Se vocÃª recusar, nada Ã© executado. Se aprovar, ele executa o plano â€”
  e, como a autorizaÃ§Ã£o foi dada em bloco, as aÃ§Ãµes daquele turno nÃ£o pedem
  confirmaÃ§Ã£o individual de novo. Perguntas simples (que nÃ£o precisam de
  ferramentas) seguem direto, sem plano. Ã‰ o fluxo *human-in-the-loop* inspirado
  no CORE.
- **Modo plano no Live (tempo real):** como o microfone jÃ¡ estÃ¡ em uso pela sessÃ£o,
  a confirmaÃ§Ã£o Ã© adaptativa. Se houver um canal sem microfone (UI web ou
  `JARVIS_CONFIRM_CHANNEL=terminal`), o cÃ³digo **apresenta o plano e pede
  aprovaÃ§Ã£o antes de executar** (mesmo gate do texto). No canal de voz puro, o
  prÃ³prio **modelo narra o plano em voz alta e espera o seu "sim"** antes de chamar
  as ferramentas â€” sem abrir um segundo microfone. Em ambos os casos, perguntas
  simples e ferramentas seguras seguem direto.
- **Ferramentas externas (MCP):** configure servidores MCP em `~/.jarvis/mcp.json`
  (`JARVIS_MCP_CONFIG`). HÃ¡ um modelo comentado em `examples/mcp.json`:

  ```json
  {
    "servers": [
      {
        "name": "filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\"]
      },
      {
        "name": "remoto",
        "transport": "http",
        "url": "https://exemplo.com/mcp",
        "headers": { "Authorization": "Bearer ..." }
      }
    ]
  }
  ```

  Transportes: `stdio` (padrÃ£o, comando local), `http` e `sse`. PeÃ§a "quais
  ferramentas externas existem?" (`mcp_list_tools`) e depois "use a ferramenta X
  do servidor Y" (`mcp_call`, com confirmaÃ§Ã£o). Desative tudo com
  `JARVIS_MCP_ENABLED=false`.

## Provedores de LLM

Por padrÃ£o o Jarvis usa o **Gemini** (`JARVIS_PROVIDER=gemini`). Para usar qualquer
endpoint compatÃ­vel com a API da OpenAI (OpenAI, Ollama, LM Studio, OpenRouter,
Groqâ€¦), defina:

```dotenv
JARVIS_PROVIDER=openai
JARVIS_OPENAI_BASE_URL=http://localhost:11434/v1
JARVIS_OPENAI_API_KEY=
JARVIS_OPENAI_MODEL=llama3.1
```

O histÃ³rico, as ferramentas (function calling) e as imagens (capturas de tela) sÃ£o
traduzidos automaticamente para o formato OpenAI. Servidores locais normalmente nÃ£o
exigem chave. A pesquisa web com grounding (`web_search`) continua usando o Gemini,
por ser um recurso especÃ­fico dele.

## ConfirmaÃ§Ã£o e seguranÃ§a

O comportamento Ã© controlado por `JARVIS_CONFIRM_MODE` e `JARVIS_CONFIRM_CHANNEL`:

- `graduated` (padrÃ£o): aÃ§Ãµes seguras rodam direto; aÃ§Ãµes de risco sÃ£o confirmadas.
- `always`: tudo Ã© confirmado.
- `never`: nenhuma confirmaÃ§Ã£o (autonomia total; maior risco).

O canal de confirmaÃ§Ã£o Ã© `voice` (padrÃ£o) ou `terminal`. Em `voice`, o Jarvis fala
o que vai fazer e espera um "sim". Se a voz falhar **ou se nada for ouvido**, ele
cai automaticamente para o terminal (por isso a aÃ§Ã£o nunca Ã© cancelada em silÃªncio).

Outras salvaguardas:

- O Gemini nÃ£o tem ferramenta de shell sem confirmaÃ§Ã£o e nunca pode contornar os
  limites; comandos de shell sempre mostram a linha exata antes de rodar.
- Arquivos ficam confinados Ã s pastas autorizadas: `JARVIS_ALLOWED_DIR` (padrÃ£o:
  diretÃ³rio de execuÃ§Ã£o) mais as pastas extras de `JARVIS_ALLOWED_DIRS` (por padrÃ£o,
  a Ãrea de Trabalho, Downloads e Documentos do usuÃ¡rio). A listagem mostra nomes;
  a leitura/escrita/criaÃ§Ã£o de pastas nÃ£o escapam dessas pastas.
- Atalhos fora da lista segura, cliques fora da tela e textos acima de 500
  caracteres sÃ£o recusados.
- A decisÃ£o de olhar a tela Ã© do modelo: quando vocÃª pede para ele "ver" a tela,
  ele chama `capture_screen`. A imagem sÃ³ Ã© capturada e enviada ao Gemini apÃ³s sua
  confirmaÃ§Ã£o, e o arquivo temporÃ¡rio Ã© apagado logo em seguida. Desative com
  `JARVIS_SCREEN_CAPTURE_ENABLED=false`.
- O histÃ³rico local enviado em pedidos posteriores contÃ©m apenas texto; imagens de
  tela nÃ£o sÃ£o guardadas no histÃ³rico pelo Jarvis. Ainda assim, solicitaÃ§Ãµes e
  imagens sÃ£o transmitidas ao serviÃ§o Gemini para anÃ¡lise.
- O reconhecimento de fala usa `recognize_google` e a sÃ­ntese usa gTTS; o Ã¡udio e
  o texto necessÃ¡rios sÃ£o enviados aos serviÃ§os correspondentes pela internet. O
  modo de texto continua disponÃ­vel sem usar o microfone.
- Mantenha `.env` privado e use uma chave da API protegida e restrita conforme as
  recomendaÃ§Ãµes do Google.

## Testes

Execute os testes automatizados com:

```bash
python -m unittest discover -s tests -v
```

HÃ¡ tambÃ©m **testes de integraÃ§Ã£o** que abrem protocolos do Windows de verdade
(ex.: `ms-settings:`). Ficam desativados por padrÃ£o para nÃ£o abrir janelas; rode-os
assim, no Windows:

```bash
set JARVIS_INTEGRATION_TESTS=1
python -m unittest tests.test_integration_protocols -v
```

(PowerShell: `$env:JARVIS_INTEGRATION_TESTS=1`.)
# assistentejarvis
Assistente pessoal para realizar tarefas de forma automatica no seu computador, pode ser usado terminal, web locahost, ou LIVE real. Projeto ainda em desenvolvimento podendo apresentar falhas e erros.
