"""Políticas/skills do usuário (inspirado no CORE).

Uma *política* é um documento markdown que descreve como o assistente deve agir
em um domínio (ex.: "o que conta como e-mail importante", "como eu gosto de
respostas", "meu padrão de commits"). Diferente de uma tarefa, ela não é
executada: é aplicada como um *lente* em toda interação relevante.

Formato do arquivo (front matter opcional)::

    ---
    title: Como organizo meu e-mail
    description: O que é urgente, cliente e ruído
    ---

    Corpo da política...

Sem front matter, o título vem do primeiro ``# Título`` e a descrição da
primeira linha não vazia após o título.
"""

import logging
import re
from pathlib import Path

from .config import MAX_CONTEXT_POLICIES, SKILLS_DIR
from .textutil import jaccard, tokens

logger = logging.getLogger(__name__)


class Policy:
    """Uma política carregada do disco."""

    def __init__(
        self,
        name: str,
        title: str,
        description: str,
        body: str,
        path: Path | None = None,
    ) -> None:
        self.name = name
        self.title = title
        self.description = description
        self.body = body
        self.path = path

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "body": self.body,
            "path": str(self.path) if self.path else "",
        }

    def render(self) -> str:
        header = self.title or self.name
        if self.description:
            return f"### {header}\n{self.description}\n\n{self.body}".strip()
        return f"### {header}\n{self.body}".strip()


def policies_dir() -> Path:
    """Diretório das políticas (criado sob demanda)."""
    return SKILLS_DIR


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Extrai um front matter simples (``chave: valor``) delimitado por ``---``."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    lines = text.splitlines()
    # localiza a linha de abertura
    start = next((i for i, line in enumerate(lines) if line.strip() == "---"), None)
    if start is None:
        return {}, text
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start=start + 1) if line.strip() == "---"),
        None,
    )
    if end is None:
        return {}, text
    metadata: dict[str, str] = {}
    for line in lines[start + 1 : end]:
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip().casefold()] = value.strip().strip('"').strip("'")
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return metadata, body


def load_policy(path: Path) -> Policy | None:
    """Carrega uma política de um arquivo markdown."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Não foi possível ler a política %s.", path)
        return None

    metadata, body = _parse_front_matter(text)
    title = metadata.get("title", "").strip()
    description = metadata.get("description", "").strip()

    if not title:
        heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if heading:
            title = heading.group(1).strip()
            body = (body[: heading.start()] + body[heading.end() :]).strip()

    if not description:
        for line in body.splitlines():
            candidate = line.strip()
            if candidate and not candidate.startswith("#"):
                description = candidate
                break

    if not title:
        title = path.stem.replace("_", " ").replace("-", " ").strip()
    if not body.strip() and not description:
        return None

    return Policy(
        name=path.stem,
        title=title or path.stem,
        description=description,
        body=body.strip(),
        path=path,
    )


def list_policies(directory: Path | None = None) -> list[Policy]:
    """Lista as políticas disponíveis (``*.md``), em ordem alfabética."""
    target = (directory or policies_dir()).expanduser()
    if not target.is_dir():
        return []
    policies: list[Policy] = []
    for path in sorted(target.glob("*.md")):
        policy = load_policy(path)
        if policy is not None:
            policies.append(policy)
    return policies


def match_policies(
    query: str,
    limit: int = MAX_CONTEXT_POLICIES,
    directory: Path | None = None,
) -> list[Policy]:
    """Seleciona as políticas mais relevantes para uma consulta."""
    policies = list_policies(directory)
    if not policies:
        return []
    if not isinstance(limit, int) or limit < 1:
        limit = MAX_CONTEXT_POLICIES
    if not isinstance(query, str) or not query.strip():
        return policies[:limit]

    query_tokens = tokens(query)
    scored: list[tuple[float, Policy]] = []
    for policy in policies:
        haystack = f"{policy.title} {policy.description} {policy.body}"
        score = jaccard(query_tokens, tokens(haystack))
        # títulos e descrições pesam mais
        score += 0.5 * jaccard(query_tokens, tokens(policy.title))
        score += 0.25 * jaccard(query_tokens, tokens(policy.description))
        if score > 0:
            scored.append((score, policy))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [policy for _, policy in scored[:limit]]


def policies_block(query: str, limit: int = MAX_CONTEXT_POLICIES) -> str:
    """Monta o bloco de texto com as políticas relevantes (ou vazio)."""
    policies = match_policies(query, limit=limit)
    if not policies:
        return ""
    rendered = "\n\n".join(policy.render() for policy in policies)
    return "POLÍTICAS DO USUÁRIO (siga-as quando relevantes):\n" + rendered
