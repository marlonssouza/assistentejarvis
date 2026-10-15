"""Testes de integração que abrem protocolos do Windows **de verdade**.

Eles ficam desativados por padrão para não abrir janelas durante a suíte normal.
Para rodá-los no Windows::

    set JARVIS_INTEGRATION_TESTS=1
    python -m unittest tests.test_integration_protocols -v

(PowerShell: ``$env:JARVIS_INTEGRATION_TESTS=1``.)
"""

import os
import platform
import unittest

from jarvis import apps

RUN_INTEGRATION = os.environ.get("JARVIS_INTEGRATION_TESTS") == "1"

_skip_reason = (
    "Integração desativada. Defina JARVIS_INTEGRATION_TESTS=1 no Windows para "
    "abrir os protocolos de verdade."
)


@unittest.skipUnless(RUN_INTEGRATION, _skip_reason)
@unittest.skipUnless(platform.system() == "Windows", "Protocolos são do Windows.")
class ProtocolIntegrationTests(unittest.TestCase):
    def test_settings_protocol_opens_for_real(self):
        protocol = apps.resolve_windows_protocol("configurações")
        self.assertEqual(protocol, "ms-settings:")
        apps.launch(protocol)  # abre a janela de Configurações de fato

    def test_windows_update_deep_link_opens_for_real(self):
        protocol = apps.resolve_windows_protocol("windows update")
        self.assertEqual(protocol, "ms-settings:windowsupdate-action")
        apps.launch(protocol)


if __name__ == "__main__":
    unittest.main()
