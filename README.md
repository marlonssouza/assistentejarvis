# J.A.R.V.I.S. Multi-Plataforma (Windows e Linux)

Assistente pessoal em Python com conversa local usando Ollama, entrada e saída de voz,
análise opcional da tela e automações locais com confirmação por risco. Identifica
automaticamente se você está rodando no Windows ou no Linux.

## Requisitos

- Python 3.11 ou superior.
- Ollama em execução, com Qwen 2.5 7B e/ou Llama 3.1 8B instalados.
- Chave Gemini somente se optar pelas funcionalidades específicas desse provedor.
- Para usar o microfone, PyAudio e um microfone disponível; no Linux, pode ser
  necessário instalar previamente os pacotes de desenvolvimento do PortAudio.
- A captura pelo microfone local filtra ruído com Silero VAD via ONNX Runtime:
  somente blocos com probabilidade de fala maior que `0.5` são mantidos. O modelo
  ONNX é baixado do repositório oficial na primeira captura e armazenado em
  `~/.jarvis/models`; depois disso, a detecção funciona localmente.
- O reconhecimento de fala usa `faster-whisper` localmente, com o modelo `tiny`
  por padrão (`base` também é aceito). O primeiro uso baixa os pesos do modelo;
  depois disso, a transcrição é executada localmente, sem enviar áudio a serviços
  de reconhecimento. Configure `JARVIS_STT_MODEL_DIR` para escolher o diretório
  de cache dos modelos.
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

O padrão é o Ollama local com Qwen e Llama já instalados.
Não é necessária chave de API para conversar. Gemini é opcional para Live/visão.

Copie `.env.example` para `.env` e confirme os nomes dos modelos locais:

```dotenv
JARVIS_PROVIDER=ollama
JARVIS_OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
JARVIS_PROVIDER_CHAIN=ollama:qwen2.5:7b-instruct-q4_K_M,ollama:llama3.1:8b
```

Os logs da aplicação e os stack traces de erros são exibidos no console e
gravados em `~/.jarvis/logs/jarvis.log`, com rotação automática (até cinco
arquivos de backup). Para alterar o destino ou o nível, configure
`JARVIS_LOG_FILE` e `JARVIS_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR` ou
`CRITICAL`) no `.env`.

Execute o assistente:

```bash
python main.py
```

## Como conversar

- **Persona:** o assistente responde em português brasileiro com formalidade
  britânica natural, cortesia e tratamento por “Senhor”; mantém a fala concisa e
  pode usar humor seco sutil sem deixar de ser respeitoso ou preciso.
- **Palavra de ativação:** com `JARVIS_WAKE_ENABLED=true` (padrão), os modos de
  voz do terminal e do navegador só encaminham o pedido ao assistente quando a
  transcrição local começa com uma palavra de `JARVIS_WAKE_WORDS` (padrão:
  `jarvis`, `ei jarvis`, `hey jarvis`). Diga, por exemplo, “Jarvis, abra a
  calculadora”; palavras ditas no meio da frase não ativam o assistente. A
  transcrição local é necessária para verificar o prefixo; sem ele, o texto não
  é enviado ao modelo nem interrompe uma resposta em andamento. Uma palavra de
  ativação válida interrompe a resposta anterior e encaminha apenas o pedido.
  O microfone indisponível leva à entrada por texto no terminal. Desative a
  exigência com `JARVIS_WAKE_ENABLED=false`.
- **Modo texto:** com `JARVIS_WAKE_ENABLED=false`, digite o pedido e pressione
  Enter. Deixar a linha em branco faz o Jarvis escutar uma fala curta.
- **Voz natural:** as respostas usam vozes neurais (`edge-tts`, grátis e naturais
  em pt-BR). Escolha a voz em `JARVIS_TTS_VOICE` (`pt-BR-AntonioNeural` é o padrão;
  também há `pt-BR-FranciscaNeural` e `pt-BR-ThalitaMultilingualNeural`) e a
  velocidade em `JARVIS_TTS_RATE`. Para voltar ao gTTS, use `JARVIS_TTS_BACKEND=gtts`.
  Com o Ollama e a opção **Voz online** (ou no modo de terminal), a primeira frase
  começa a ser sintetizada assim que chega a pontuação final, enquanto o modelo
  ainda gera o restante. A voz do navegador continua lendo a resposta completa.
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

Ollama local é o padrão. A aplicação usa `/api/chat` nativo, sem serviços intermediários.

```dotenv
JARVIS_PROVIDER=ollama
JARVIS_OLLAMA_BASE_URL=http://127.0.0.1:11434
JARVIS_OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
JARVIS_PROVIDER_CHAIN=ollama:qwen2.5:7b-instruct-q4_K_M,ollama:llama3.1:8b
JARVIS_OLLAMA_NUM_CTX=8192
JARVIS_OLLAMA_MAX_TOKENS=384
JARVIS_OLLAMA_NUM_BATCH=128
JARVIS_OLLAMA_TIMEOUT=60
JARVIS_OLLAMA_KEEP_ALIVE=5m
JARVIS_FAILOVER_COOLDOWN=60
JARVIS_PLAN_MODE=false
```

Qwen é o principal; Llama é tentado automaticamente quando o principal falha.
Antes de trocar, o modelo que falhou é liberado do Ollama. Pedidos que já executaram
ferramentas não são repetidos, evitando ações duplicadas. Os nomes completos
dos modelos (incluindo os dois-pontos das tags) são preservados.

A primeira resposta pode incluir o carregamento do modelo. `KEEP_ALIVE` evita
recarregar a cada pedido. Contexto 8192 permite o catálogo completo de ferramentas;
o lote 128 reduz o pico de memória. Outros modelos em uso competem por RAM/VRAM.
As confirmações das ferramentas de risco permanecem ativas mesmo sem modo plano.

Os dois modelos locais selecionados suportam texto/ferramentas, sem visão.
Gemini pode ser selecionado explicitamente para Live/visão; não está na cadeia
local padrão. A pesquisa web tem uma alternativa pública sem chave Gemini.

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
- O áudio de entrada é transcrito localmente pelo faster-whisper e não é enviado
  a um serviço de STT. A síntese de fala (`edge-tts` ou gTTS) continua usando a
  rede; o modo de texto continua disponível sem usar o microfone. A exceção é o
  modo opcional Live (`JARVIS_LIVE_MODE=true`), que envia áudio ao Gemini Live.
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


## Conversa por voz e interrupções

A interface web usa por padrão a síntese de voz do navegador, sem aguardar a
geração de MP3 no servidor. Selecione Voz online para edge-tts/gTTS ou Som
desligado para texto. Voz e transcrição podem depender dos serviços do navegador
e do Google; a inferência de conversa continua no Ollama local.

Clique no microfone para conversar. Uma pausa de cerca de 700 ms encerra uma
frase. A transcrição usa faster-whisper local; a síntese pode depender do
navegador ou, no modo Voz online, de edge-tts/gTTS. Cancelamento de eco e
supressão de ruído são solicitados ao navegador. A captura recalibra o ruído
ambiente por um segundo a cada nova escuta e adapta o limiar de energia durante
a espera pela fala.
Quando o VAD detecta fala durante a resposta, o navegador para imediatamente
o áudio local e envia `ABORT` pelo WebSocket; o servidor descarta as frases
pendentes e fecha o stream ativo do Ollama. Também há o botão Interromper e a
tecla Escape. Fones ajudam a evitar que o som dos alto-falantes seja confundido
com uma interrupção. A transcrição ainda ocorre por trechos, não é uma sessão
de áudio em tempo real.

Pedidos interrompidos não podem iniciar novas ferramentas. Uma operação local
de ferramenta já iniciada não pode ser desfeita pela interrupção. O stream de
geração do Ollama é fechado no ABORT; pedidos novos aguardam a liberação do
motor para não misturar histórico nem executar ações simultâneas.

Confirmações e eventos de ferramentas são isolados por conexão do painel.
Respostas antigas são descartadas e não voltam a tocar após a interrupção.

### Prévia da câmera

Ligar câmera abre somente uma prévia local no navegador, com permissão do
usuário. Desligar câmera encerra as trilhas do dispositivo. Nenhum quadro é
enviado, salvo ou analisado pelo Jarvis. Os dois modelos de conversa atuais
não recebem imagens. Não foi instalado um modelo visual.


### Controles de voz na janela compacta

Execute `python -m jarvis.app --compact` no ambiente do projeto. O comando
`--compact` não precisa mais de `--ui`. Se já houver um servidor Jarvis ativo,
ele será reutilizado; outro serviço na mesma porta gera um erro claro.

A janela oferece Ativar escuta/Desativar escuta e Interromper (também Escape).
A captura só começa após clicar em Ativar escuta e depende de PyAudio e do
microfone disponível. A transcrição usa o mesmo fluxo do servidor web.
Durante o processamento e a reprodução, trechos capturados são descartados
para evitar que o Jarvis transcreva a própria voz. Para cortar a resposta na
janela compacta, use Interromper. O envio e a reprodução acontecem em threads,
sem bloquear o Tkinter. O áudio é reproduzido com ffplay, mpv ou mpg123.
Falhas do dispositivo e do reprodutor aparecem no histórico da janela.
Fechar a janela interrompe a escuta, a reprodução e a conexão do cliente.
O OpenCode e serviços de API removidos não são usados por esta interface.
