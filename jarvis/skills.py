"""Catálogo de skills: agrupa as capacidades do Jarvis para exibição na UI.

As "skills" são implementadas pelas ferramentas em :mod:`jarvis.hands`; aqui
mantemos apenas uma visão amigável (título, exemplo e nível de risco) para a
interface e para a documentação.
"""

from .hands import TOOL_RISK

# Cada grupo lista skills com a ferramenta correspondente e um exemplo de fala.
SKILL_GROUPS = [
    {
        "title": "Conversa e conhecimento",
        "icon": "🧠",
        "items": [
            {
                "tool": "web_search",
                "label": "Pesquisar na web",
                "example": "Pesquise o preço do dólar hoje",
            },
            {
                "tool": "read_webpage",
                "label": "Ler o conteúdo de um site",
                "example": "Leia a página inicial do g1 e resuma",
            },
            {
                "tool": "get_datetime",
                "label": "Data e hora",
                "example": "Que horas são?",
            },
            {
                "tool": "remember",
                "label": "Memorizar um fato",
                "example": "Lembre que meu aniversário é 12 de março",
            },
            {
                "tool": "recall",
                "label": "Recordar um fato",
                "example": "Quando é meu aniversário?",
            },
        ],
    },
    {
        "title": "E-mail",
        "icon": "📧",
        "items": [
            {
                "tool": "list_emails",
                "label": "Ver e-mails recentes",
                "example": "Veja meus e-mails mais recentes",
            },
            {
                "tool": "read_email",
                "label": "Ler um e-mail",
                "example": "Leia o e-mail sobre a reunião",
            },
        ],
    },
    {
        "title": "Computador e apps",
        "icon": "🖥️",
        "items": [
            {
                "tool": "open_application",
                "label": "Abrir app, arquivo ou pasta",
                "example": "Abra o Chrome",
            },
            {
                "tool": "open_special_folder",
                "label": "Abrir uma pasta especial",
                "example": "Abra a minha pasta de Downloads",
            },
            {
                "tool": "open_url",
                "label": "Abrir um site no navegador",
                "example": "Abra o site do YouTube",
            },
            {
                "tool": "search_web_browser",
                "label": "Pesquisar no Google pelo navegador",
                "example": "Abra o Chrome e pesquise sobre futebol",
            },
            {
                "tool": "browser_open",
                "label": "Abrir uma página para interagir",
                "example": "Abra o site e leia os resultados",
            },
            {
                "tool": "browser_read",
                "label": "Ler a página aberta",
                "example": "Leia o que está na página",
            },
            {
                "tool": "browser_click",
                "label": "Clicar em um elemento da página",
                "example": "Clique em 'Próxima página'",
            },
            {
                "tool": "browser_type",
                "label": "Preencher um campo da página",
                "example": "Digite futebol no campo de busca",
            },
            {
                "tool": "browser_close",
                "label": "Fechar o navegador controlado",
                "example": "Feche o navegador",
            },
            {
                "tool": "capture_screen",
                "label": "Olhar a tela",
                "example": "O que está na minha tela?",
            },
            {
                "tool": "click_at",
                "label": "Clicar em um ponto",
                "example": "Clique no botão no canto superior",
            },
            {
                "tool": "type_text",
                "label": "Digitar um texto",
                "example": "Digite 'bom dia' no campo",
            },
            {
                "tool": "press_hotkey",
                "label": "Pressionar um atalho",
                "example": "Pressione ctrl+c",
            },
        ],
    },
    {
        "title": "Arquivos e sistema",
        "icon": "📁",
        "items": [
            {
                "tool": "list_files",
                "label": "Listar arquivos",
                "example": "Liste os arquivos da pasta",
            },
            {
                "tool": "read_file",
                "label": "Ler um arquivo",
                "example": "Leia o arquivo notas.txt",
            },
            {
                "tool": "write_file",
                "label": "Escrever um arquivo",
                "example": "Crie um arquivo ideias.txt com ...",
            },
            {
                "tool": "create_directory",
                "label": "Criar uma pasta",
                "example": "Crie uma pasta 'teste' na Área de Trabalho",
            },
            {
                "tool": "get_system_info",
                "label": "Informações do sistema",
                "example": "Qual é o meu sistema?",
            },
            {
                "tool": "system_status",
                "label": "Uso de CPU, RAM e disco",
                "example": "Como está o uso de memória do PC?",
            },
            {
                "tool": "top_processes",
                "label": "Processos mais pesados",
                "example": "O que está consumindo mais memória?",
            },
            {
                "tool": "run_command",
                "label": "Executar um comando",
                "example": "Rode o comando ping google.com",
            },
        ],
    },
    {
        "title": "Sistema e produtividade",
        "icon": "⚙️",
        "items": [
            {
                "tool": "generate_password",
                "label": "Gerar uma senha forte",
                "example": "Gere uma senha de 20 caracteres",
            },
            {
                "tool": "set_volume",
                "label": "Ajustar o volume",
                "example": "Coloque o volume em 30%",
            },
            {
                "tool": "set_brightness",
                "label": "Ajustar o brilho",
                "example": "Diminua o brilho da tela",
            },
            {
                "tool": "power_action",
                "label": "Energia do computador",
                "example": "Bloqueie o computador",
            },
            {
                "tool": "set_reminder",
                "label": "Agendar um lembrete",
                "example": "Me lembre de tomar água em 15 minutos",
            },
            {
                "tool": "list_reminders",
                "label": "Ver lembretes pendentes",
                "example": "Quais lembretes eu tenho?",
            },
        ],
    },
    {
        "title": "Memória, políticas e integrações",
        "icon": "🧩",
        "items": [
            {
                "tool": "list_skills",
                "label": "Ver políticas/skills",
                "example": "Quais políticas minhas você conhece?",
            },
            {
                "tool": "mcp_list_tools",
                "label": "Listar ferramentas MCP",
                "example": "Quais ferramentas externas estão disponíveis?",
            },
            {
                "tool": "mcp_call",
                "label": "Usar uma ferramenta MCP",
                "example": "Crie uma issue no servidor MCP do GitHub",
            },
        ],
    },
]

_RISK_LABEL = {"safe": "automática", "dangerous": "com confirmação"}


def skills_payload() -> dict:
    """Retorna as skills com o nível de risco atual de cada ferramenta."""
    groups = []
    for group in SKILL_GROUPS:
        items = []
        for item in group["items"]:
            risk = TOOL_RISK.get(item["tool"], "dangerous")
            items.append(
                {
                    "tool": item["tool"],
                    "label": item["label"],
                    "example": item["example"],
                    "risk": risk,
                    "risk_label": _RISK_LABEL.get(risk, risk),
                }
            )
        groups.append({"title": group["title"], "icon": group["icon"], "items": items})
    return {"groups": groups, "total": sum(len(g["items"]) for g in groups)}


__all__ = ["SKILL_GROUPS", "skills_payload"]
