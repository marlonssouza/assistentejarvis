import random
from typing import List

WAKE_RESPONSES: List[str] = [
    "Às suas ordens, senhor.",
    "Pois não, senhor.",
    "Sim, senhor?",
    "Pronto para ajudar, senhor.",
    "Estou à disposição.",
    "Em que posso servi-lo, senhor?",
    "À espera de suas ordens.",
    "Às suas ordens.",
    "Sim.",
    "Pode falar, senhor.",
    "Pronto.",
]


def get_wake_response() -> str:
    return random.choice(WAKE_RESPONSES)


def get_dynamic_response() -> str:
    return random.choice(WAKE_RESPONSES)
