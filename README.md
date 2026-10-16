# J.A.R.V.I.S. Multi-Plataforma (Windows e Linux)

Assistente pessoal em Python com conversa usando Gemini, entrada e saída de voz,
análise opcional da tela e automações locais com confirmação por risco. Identifica
automaticamente se você está rodando no Windows ou no Linux.

## Requisitos

- Python 3.10 ou superior.
- Uma chave da Gemini API.
- Para usar o microfone, PyAudio e um microfone disponível. A dependência
  `SpeechRecognition[audio]` instala o suporte de áudio quando disponível; no
  Linux, pode ser necessário instalar previamente os pacotes de desenvolvimento
  do PortAudio pela distribuição.
- Para ouvir as respostas e falar, `ffplay` (recomendado), `mpg123` ou `mpv`.
  Sem um destes, no Windows o Jarvis usa o player padrão do sistema (sem
  bloquear) e no Linux a fala fica indisponível.

## Instalação

```bash
python -m venv .venv
```

Ative o ambiente virtual e instale as dependências:

```bash
python -m pip install -r requirements.txt
```

Para usar a **automação de navegador** (ferramentas `browser_*`), instale também
o navegador do Playwright (o Chrome instalado é usado quando disponível):

```bash
python -m playwright install chromium
```

Os controles de sistema (`system_status`, `top_processes`, `set_volume`,
`set_brightness`, `power_action`) usam `psutil`, `pycaw` (Windows) e
`screen-brightness-control`, já incluídos em `requirements.txt`. Se algum estiver
ausente, a ferramenta responde com uma mensagem clara em vez de quebrar o assistente.

Para usar **ferramentas externas via MCP** (ferramentas `mcp_*`), o pacote `mcp`
é necessário (`pip install mcp`). Ele é importado sob demanda: sem o pacote, o
Jarvis continua funcionando normalmente, apenas as ferramentas MCP avisam que
precisam ser instaladas.

Para usar **outro provedor de LLM** (OpenAI/Ollama/LM Studio), defina
`JARVIS_PROVIDER=openai` e as variáveis `JARVIS_OPENAI_*` (veja `.env.example`).
O padrão continua sendo o Gemini.

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

- **Modo voz contínuo (padrão):** o Jarvis fica ouvindo; diga a palavra de
  ativação (`JARVIS_WAKE_WORDS`, padrão `jarvis`, ou só "Jarvis") e em seguida o
  pedido. Se o microfone não estiver disponível, ele cai automaticamente para a
  entrada por texto. Desative com `JARVIS_WAKE_ENABLED=false`.
- **Modo texto:** com `JARVIS_WAKE_ENABLED=false`, digite o pedido e pressione
  Enter. Deixar a linha em branco faz o Jarvis escutar uma fala curta.
- **Voz natural:** as respostas usam vozes neurais (`edge-tts`, grátis e naturais
  em pt-BR). Escolha a voz em `JARVIS_TTS_VOICE` (`pt-BR-AntonioNeural` é o padrão;
  também há `pt-BR-FranciscaNeural` e `pt-BR-ThalitaMultilingualNeural`) e a
  velocidade em `JARVIS_TTS_RATE`. Para voltar ao gTTS, use `JARVIS_TTS_BACKEND=gtts`.
- **Modo voz em tempo real (Live):** defina `JARVIS_LIVE_MODE=true` para falar
  naturalmente, com o modelo respondendo em áudio quase instantâneo (incluindo
  interrupção/barge-in). É experimental e opcional; se a sessão não puder iniciar,
  o Jarvis volta automaticamente ao modo padrão. Ajustes: `JARVIS_LIVE_MODEL`
  (padrão `gemini-3.8-live`) e `JARVIS_LIVE_VOICE` (padrão `Puck`). As ferramentas
  e o modelo de confirmação continuam valendo. O **modo plano** também funciona no
  live: veja a nota na seção "Memória, políticas e integrações".
- **Limpar a conversa:** digite (ou fale) `limpar conversa` para apagar o
  histórico. `sair`, `desligar`, `encerrar` ou `tchau` encerram.
- A memória da conversa e os fatos memorizados ficam em `JARVIS_MEMORY_FILE`
  (padrão `~/.jarvis/memory.json`) e sobrevivem entre sessões.

## Ferramentas (o que o Jarvis pode fazer)

Ações **seguras** (liberadas direto no modo graduado):

- `list_files` — lista nomes na pasta autorizada.
- `read_file` — lê o texto de um arquivo autorizado.
- `get_datetime` — data e hora atuais.
- `get_system_info` — sistema, versão, hostname, usuário, diretório atual, home,
  Área de Trabalho e pastas autorizadas.
- `open_url` — abre uma URL `http/https`.
- `web_search` — pesquisa na web (resultados atuais do Google) e resume com fontes.
- `read_webpage` — baixa uma página e devolve o texto legível dela.
- `search_web_browser` — abre o navegador (ex.: Chrome) em uma pesquisa do Google,
  mostrando a janela ao usuário.
- `browser_open` / `browser_read` / `browser_close` — navegador controlado
  (Playwright): abrir página, ler o texto visível e fechar.
- `open_special_folder` — abre uma pasta especial do usuário (Downloads, Documentos,
  Área de Trabalho, Imagens, Música, Vídeos).
- `system_status` — uso atual de CPU, memória e disco.
- `top_processes` — processos que mais consomem memória.
- `generate_password` — gera uma senha forte e tenta copiá-la para a área de
  transferência.
- `set_reminder` / `list_reminders` — agenda, anuncia e lista lembretes.
- `list_skills` — lista as políticas/skills do usuário.
- `mcp_list_tools` — lista as ferramentas dos servidores MCP configurados.
- `list_emails` / `read_email` — lista e lê os e-mails do Gmail (requer configuração).
- `remember` / `recall` — memoriza fatos (com aspecto) e recupera os mais
  relevantes por busca, com histórico preservado.

Ações de **risco** (pedem confirmação):

- `open_application` — abre qualquer aplicativo por nome. Resolve navegadores
  (ex.: Chrome, mesmo fora do PATH), **protocolos do Windows** (ex.: "configurações",
  "windows update", "bluetooth", "painel de controle"), pastas especiais e busca
  executáveis no PATH, no registro e nas pastas de programas.
- `capture_screen` — captura a tela (inteira ou uma região) e envia a imagem ao modelo.
- `click_at` — clica em uma coordenada.
- `type_text` — digita um texto.
- `press_hotkey` — pressiona um atalho permitido.
- `write_file` — escreve/sobrescreve um arquivo autorizado.
- `create_directory` — cria uma pasta em uma das pastas autorizadas.
- `browser_click` / `browser_type` — clica em / preenche elementos da página aberta
  no navegador controlado.
- `set_volume` — ajusta o volume do sistema (`set`, `up`, `down`, `mute`, `unmute`).
- `set_brightness` — ajusta o brilho da tela (`set`, `up`, `down`).
- `power_action` — desliga, reinicia, suspende, hiberna ou bloqueia o computador
  (destrutiva; exige confirmação).
- `mcp_call` — chama uma ferramenta de um servidor MCP externo (exige confirmação).
- `run_command` — executa um comando de shell.

## Rotina, clima e automacao

Ferramentas **seguras** adicionadas para o dia a dia:

- `get_weather` — clima atual e previsao. Usa a chave `OPENWEATHER_API_KEY`
  (se configurada) e cai automaticamente para **Open-Meteo** (sem chave) e
  **wttr.in**, garantindo resposta mesmo sem chave.
- `daily_briefing` — monta o resumo do dia: data/hora, clima, lembretes
  pendentes e e-mails nao lidos. Ideal para uma saudacao proativa.
- `take_quick_note` / `append_quick_note` / `list_quick_notes` — anotacoes
  rapidas em Markdown nas pastas autorizadas (otimo para ditado).
- `play_media` — busca e abre videos/musicas no navegador (YouTube por padrao).
- `schedule_task` / `list_scheduled` / `cancel_task` — agenda tarefas futuras
  (`"HH:MM"`, `"in 30"` minutos ou ISO), com repeticao `daily` opcional.
- `network_diagnostics` — diagnostico de rede somente leitura (ping em gateway
  e DNS publicos, teste de DNS, status de conectividade).

Ferramentas de **risco** (pedem confirmacao):

- `network_fix` — reparo de rede no Windows (release/renew de IP, flush e
  register de DNS); **cada etapa pede confirmacao explicita**.
- `network_autorepair` — diagnostica e, se estiver offline, executa o reparo
  com confirmacao.

Variaveis de ambiente relacionadas:

```dotenv
# Frases de ativacao variadas ("As suas ordens", "Pois nao"...). Padrao: false.
JARVIS_WAKE_DYNAMIC=false
# Cria automaticamente um briefing diario as 08:00. Padrao: false.
JARVIS_DAILY_BRIEFING_AUTO=false
# Interface: "web" (padrao) ou "compact" (janela Tkinter + bandeja).
JARVIS_UI_MODE=web
```

## Interface compacta (Tkinter + bandeja)

Alem do painel web, ha uma **interface compacta opcional** – uma janela pequena
estilo orbe, com icone na bandeja do sistema. Ela **nao substitui** a
arquitetura atual: conversa com o **mesmo servidor** (FastAPI/WebSocket), pelo
mesmo `/ws`, com as mesmas ferramentas, confirmacoes e memoria.

Ativar (mantendo o modo web como padrao):

```bash
# Opcao 1: variavel de ambiente
set JARVIS_UI_MODE=compact
python -m jarvis.app --ui

# Opcao 2: lancador dedicado (sobe o servidor em background)
python -m jarvis.compact_app
# ou, se instalado: jarvis-compact

# Opcao 3: forcar pela linha de comando
python -m jarvis.app --ui --compact
```

O icone de bandeja usa `pystray` (opcional). Se nao estiver instalado, a janela
funciona normalmente e o tray e apenas ignorado:

```bash
pip install "jarvis-cross-platform[tray]"
```

## Web e e-mail


- **Pesquisar e ler sites:** peça "pesquise X" (o Jarvis usa o Google e responde
  com dados atuais e fontes) ou "abra e leia o site Y" para ele baixar a página e
  resumir o conteúdo.
- **Abrir o navegador e pesquisar:** peça "abra o Chrome e pesquise futebol". O
  Jarvis encontra o Chrome instalado (mesmo que não esteja no PATH) e abre a
  pesquisa no Google, mostrando a janela. Para interagir com a página (ler,
  clicar, preencher campos), ele usa o navegador controlado (`browser_open`,
  `browser_read`, `browser_click`, `browser_type`), que usa o Playwright.
- **Gmail:** para o Jarvis ler seus e-mails, faça isto uma vez:
  1. No Google Cloud Console, crie um projeto e habilite a **Gmail API**.
  2. Crie credenciais OAuth do tipo **App para computador** e baixe o JSON.
  3. Salve o arquivo como `credentials.json` na pasta do projeto.
  4. Rode `python gmail_setup.py` e autorize no navegador.
  O token fica em `~/.jarvis/token.json`. Depois é só pedir, por exemplo,
  "veja meus e-mails mais recentes" ou "leia o e-mail sobre X".

## Sistema e produtividade

- **Abrir pastas especiais:** "abra a minha pasta de Downloads", "abra os Documentos",
  "abra a Área de Trabalho", "abra as Imagens".
- **Abrir apps e protocolos do Windows:** "abra o Chrome", "abra as configurações",
  "abra o Windows Update", "abra o Bluetooth", "abra o painel de controle". O
  `open_application` procura no PATH, no registro e nas pastas de programas.
- **Monitorar o PC:** "como está o uso de memória?" (`system_status`) e "o que está
  consumindo mais memória?" (`top_processes`).
- **Volumes e energia:** "coloque o volume em 30%", "diminua o brilho", "bloqueie o
  computador" — todas pedem confirmação.
- **Senhas:** "gere uma senha de 20 caracteres" (`generate_password`).
- **Lembretes:** "me lembre de tomar água em 15 minutos" (`set_reminder`); o Jarvis
  anuncia quando chegar a hora. "quais lembretes eu tenho?" (`list_reminders`).

## Memória, políticas e integrações

- **Memória estruturada:** cada fato guardado tem um **aspecto** (categoria:
  `identity`, `preference`, `directive`, `goal`, `decision`, `problem`, `knowledge`,
  `habit`, `relationship`, `belief`, `task`, `event`), data e origem. O histórico
  é sempre preservado: quando você corrige um fato, o antigo é marcado como
  **substituído** (supersessão) em vez de apagado. A recuperação é feita por
  **relevância**, então o Jarvis não despeja a memória inteira no contexto.
  Diga, por exemplo, "lembre que eu prefiro respostas curtas" e depois
  "você lembra das minhas preferências?".
- **Perfil automático:** a partir da memória, o Jarvis monta um pequeno **perfil**
  (identidade, diretrizes, preferências, objetivos…) e injeta os fatos relevantes
  em cada conversa. Desative com `JARVIS_PERSONA_ENABLED=false`.
- **Políticas/skills:** crie arquivos `.md` em `~/.jarvis/skills`
  (`JARVIS_SKILLS_DIR`) descrevendo *como* você quer que o Jarvis aja em um
  assunto (ex.: "o que conta como e-mail importante"). As políticas relevantes são
  aplicadas automaticamente e podem ser consultadas com `list_skills`. Há exemplos
  prontos em `examples/skills/`. Formato:

  ```markdown
  ---
  title: Como respondo
  description: Estilo das minhas respostas
  ---
  Seja direto, sem jargão; no máximo 3 parágrafos.
  ```

- **Modo plano (aprovar antes de executar):** com `JARVIS_PLAN_MODE=true`, o
  Jarvis faz uma **passada de planejamento** antes de agir: ele descreve, em passos
  numerados, o que pretende fazer e quais ferramentas usará, e **espera a sua
  aprovação**. Se você recusar, nada é executado. Se aprovar, ele executa o plano —
  e, como a autorização foi dada em bloco, as ações daquele turno não pedem
  confirmação individual de novo. Perguntas simples (que não precisam de
  ferramentas) seguem direto, sem plano. É o fluxo *human-in-the-loop* inspirado
  no CORE.
- **Modo plano no Live (tempo real):** como o microfone já está em uso pela sessão,
  a confirmação é adaptativa. Se houver um canal sem microfone (UI web ou
  `JARVIS_CONFIRM_CHANNEL=terminal`), o código **apresenta o plano e pede
  aprovação antes de executar** (mesmo gate do texto). No canal de voz puro, o
  próprio **modelo narra o plano em voz alta e espera o seu "sim"** antes de chamar
  as ferramentas — sem abrir um segundo microfone. Em ambos os casos, perguntas
  simples e ferramentas seguras seguem direto.
- **Ferramentas externas (MCP):** configure servidores MCP em `~/.jarvis/mcp.json`
  (`JARVIS_MCP_CONFIG`). Há um modelo comentado em `examples/mcp.json`:

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

  Transportes: `stdio` (padrão, comando local), `http` e `sse`. Peça "quais
  ferramentas externas existem?" (`mcp_list_tools`) e depois "use a ferramenta X
  do servidor Y" (`mcp_call`, com confirmação). Desative tudo com
  `JARVIS_MCP_ENABLED=false`.

## Provedores de LLM

Por padrão o Jarvis usa o **Gemini** (`JARVIS_PROVIDER=gemini`). Para usar qualquer
endpoint compatível com a API da OpenAI (OpenAI, Ollama, LM Studio, OpenRouter,
Groq…), defina:

```dotenv
JARVIS_PROVIDER=openai
JARVIS_OPENAI_BASE_URL=http://localhost:11434/v1
JARVIS_OPENAI_API_KEY=
JARVIS_OPENAI_MODEL=llama3.1
```

O histórico, as ferramentas (function calling) e as imagens (capturas de tela) são
traduzidos automaticamente para o formato OpenAI. Servidores locais normalmente não
exigem chave. A pesquisa web com grounding (`web_search`) continua usando o Gemini,
por ser um recurso específico dele.

### OpenCode Zen (LLMs gratuitas)

O Jarvis também fala com o **OpenCode Zen** (`JARVIS_PROVIDER=zen`), que oferece
modelos gratuitos (`qwen3.6-plus-free`, `glm-5-free`, `kimi-k2.5-free`, ...) num
endpoint compatível com a API da OpenAI. A chave é lida de `JARVIS_ZEN_API_KEY`;
se vazia, tenta `OPENCODE_API_KEY` e, por fim, a credencial do próprio OpenCode
instalado (`~/.local/share/opencode/auth.json`).

```dotenv
JARVIS_PROVIDER=zen
JARVIS_ZEN_MODEL=qwen3.6-plus-free
```

> O *free tier* do Zen é oferecido para uso de dentro do próprio OpenCode e pode
> recusar chamadas externas (`FreeTierError` / "Model is unavailable"). Nesse
> caso o failover abaixo segue para o próximo provedor automaticamente.

### Failover automático entre provedores

Defina uma cadeia de alvos em `JARVIS_PROVIDER_CHAIN` (separados por vírgula,
cada um no formato `provedor` ou `provedor:modelo`). O Jarvis tenta na ordem
configurada e, quando um alvo responde com erro de cota/limite (`429`,
`RESOURCE_EXHAUSTED`, chave inválida, modelo indisponível...), ele sai da cadeia
por `JARVIS_FAILOVER_COOLDOWN` segundos e a resposta vem do próximo alvo:

```dotenv
JARVIS_PROVIDER_CHAIN=zen:qwen3.6-plus-free,zen:glm-5-free,gemini
JARVIS_FAILOVER_COOLDOWN=21600
```

Detalhes que importam:

- O estado fica em `~/.jarvis/provider_state.json` e sobrevive a reinícios: uma
  cota diária estourada hoje volta a ser usada sozinha amanhã.
- Quando a própria mensagem de erro informa o prazo ("Retry in 6h43m"), ele é
  respeitado — em vez do cooldown fixo.
- Se **todos** os alvos estiverem esgotados, o Jarvis tenta a cadeia completa
  como último recurso (um provedor que já voltou responde e é liberado na hora).
  Se nada responder, ele avisa que as cotas estão esgotadas em vez de mostrar um
  erro cru.
- O failover só repete o turno quando o erro acontece **antes** de qualquer
  ferramenta rodar: se uma ação já começou, o Jarvis não a executa duas vezes. A
  aprovação do modo plano também vale para o turno inteiro, sem perguntar de novo.

## Confirmação e segurança

O comportamento é controlado por `JARVIS_CONFIRM_MODE` e `JARVIS_CONFIRM_CHANNEL`:

- `graduated` (padrão): ações seguras rodam direto; ações de risco são confirmadas.
- `always`: tudo é confirmado.
- `never`: nenhuma confirmação (autonomia total; maior risco).

O canal de confirmação é `voice` (padrão) ou `terminal`. Em `voice`, o Jarvis fala
o que vai fazer e espera um "sim". Se a voz falhar **ou se nada for ouvido**, ele
cai automaticamente para o terminal (por isso a ação nunca é cancelada em silêncio).

Outras salvaguardas:

- O Gemini não tem ferramenta de shell sem confirmação e nunca pode contornar os
  limites; comandos de shell sempre mostram a linha exata antes de rodar.
- Arquivos ficam confinados às pastas autorizadas: `JARVIS_ALLOWED_DIR` (padrão:
  diretório de execução) mais as pastas extras de `JARVIS_ALLOWED_DIRS` (por padrão,
  a Área de Trabalho, Downloads e Documentos do usuário). A listagem mostra nomes;
  a leitura/escrita/criação de pastas não escapam dessas pastas.
- Atalhos fora da lista segura, cliques fora da tela e textos acima de 500
  caracteres são recusados.
- A decisão de olhar a tela é do modelo: quando você pede para ele "ver" a tela,
  ele chama `capture_screen`. A imagem só é capturada e enviada ao Gemini após sua
  confirmação, e o arquivo temporário é apagado logo em seguida. Desative com
  `JARVIS_SCREEN_CAPTURE_ENABLED=false`.
- O histórico local enviado em pedidos posteriores contém apenas texto; imagens de
  tela não são guardadas no histórico pelo Jarvis. Ainda assim, solicitações e
  imagens são transmitidas ao serviço Gemini para análise.
- O reconhecimento de fala usa `recognize_google` e a síntese usa gTTS; o áudio e
  o texto necessários são enviados aos serviços correspondentes pela internet. O
  modo de texto continua disponível sem usar o microfone.
- Mantenha `.env` privado e use uma chave da API protegida e restrita conforme as
  recomendações do Google.

## Testes

Execute os testes automatizados com:

```bash
python -m unittest discover -s tests -v
```

Há também **testes de integração** que abrem protocolos do Windows de verdade
(ex.: `ms-settings:`). Ficam desativados por padrão para não abrir janelas; rode-os
assim, no Windows:

```bash
set JARVIS_INTEGRATION_TESTS=1
python -m unittest tests.test_integration_protocols -v
```

(PowerShell: `$env:JARVIS_INTEGRATION_TESTS=1`.)
# assistentejarvis
Assistente pessoal para realizar tarefas de forma automatica no seu computador, pode ser usado terminal, web locahost, ou LIVE real. Projeto ainda em desenvolvimento podendo apresentar falhas e erros.
