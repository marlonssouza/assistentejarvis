import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis import apps


class BrowserResolutionTests(unittest.TestCase):
    def test_default_and_empty_return_none(self):
        self.assertIsNone(apps.resolve_browser("default"))
        self.assertIsNone(apps.resolve_browser(""))
        self.assertIsNone(apps.resolve_browser("   "))

    def test_unknown_browser_is_not_treated_as_executable(self):
        self.assertIsNone(apps.resolve_browser("navegador-inexistente-xyz"))

    def test_known_browser_uses_registry_when_present(self):
        fake = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        with (
            patch.object(apps.platform, "system", return_value="Windows"),
            patch.object(apps, "_registry_app_path", return_value=fake),
            patch.object(apps.shutil, "which", return_value=None),
        ):
            self.assertEqual(apps.resolve_browser("google chrome"), fake)

    def test_alias_is_normalized(self):
        fake = Path("/usr/bin/google-chrome")
        with (
            patch.object(apps.platform, "system", return_value="Linux"),
            patch.object(apps.shutil, "which", return_value=str(fake)),
        ):
            self.assertEqual(apps.resolve_browser("Google Chrome"), fake)


class ApplicationResolutionTests(unittest.TestCase):
    def test_application_falls_back_to_path(self):
        fake = "/usr/bin/meuapp"
        with patch.object(apps.shutil, "which", return_value=fake):
            self.assertEqual(apps.resolve_application("meuapp"), Path(fake))

    def test_unknown_application_returns_none(self):
        with (
            patch.object(apps.shutil, "which", return_value=None),
            patch.object(apps.platform, "system", return_value="Linux"),
        ):
            self.assertIsNone(apps.resolve_application("app-inexistente-xyz"))


class SpecialFolderTests(unittest.TestCase):
    def test_resolves_known_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Downloads").mkdir()
            with patch.object(apps.Path, "home", return_value=root):
                self.assertEqual(apps.resolve_special_folder("Downloads"), root / "Downloads")

    def test_accepts_accented_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Desktop").mkdir()
            with patch.object(apps.Path, "home", return_value=root):
                self.assertEqual(
                    apps.resolve_special_folder("Área de Trabalho"), root / "Desktop"
                )

    def test_unknown_folder_returns_none(self):
        self.assertIsNone(apps.resolve_special_folder("lugar-nenhum"))
        self.assertIsNone(apps.resolve_special_folder(""))

    def test_missing_folder_on_disk_returns_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(apps.Path, "home", return_value=Path(temp_dir)):
                self.assertIsNone(apps.resolve_special_folder("Downloads"))


class WindowsProtocolTests(unittest.TestCase):
    def test_resolves_settings_protocol_on_windows(self):
        with patch.object(apps.platform, "system", return_value="Windows"):
            self.assertEqual(apps.resolve_windows_protocol("configurações"), "ms-settings:")

    def test_resolves_windows_update_deep_link(self):
        with patch.object(apps.platform, "system", return_value="Windows"):
            self.assertEqual(
                apps.resolve_windows_protocol("Windows Update"),
                "ms-settings:windowsupdate-action",
            )

    def test_returns_none_on_other_systems(self):
        with patch.object(apps.platform, "system", return_value="Linux"):
            self.assertIsNone(apps.resolve_windows_protocol("configurações"))


class ExecutableSearchTests(unittest.TestCase):
    def test_finds_executable_in_search_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "MinhaApp").mkdir()
            target = root / "MinhaApp" / "minhaapp.exe"
            target.write_bytes(b"")
            with (
                patch.object(apps.platform, "system", return_value="Windows"),
                patch.object(apps, "_windows_search_roots", return_value=[root]),
            ):
                self.assertEqual(apps.search_windows_executable("minhaapp"), target)

    def test_returns_none_off_windows(self):
        with patch.object(apps.platform, "system", return_value="Linux"):
            self.assertIsNone(apps.search_windows_executable("qualquercoisa"))


class LaunchTests(unittest.TestCase):
    def test_windows_uses_startfile_without_console(self):
        with (
            patch.object(apps.platform, "system", return_value="Windows"),
            patch.object(apps.os, "startfile", create=True) as startfile,
        ):
            apps.launch(Path("C:/App/app.exe"))
        startfile.assert_called_once_with(str(Path("C:/App/app.exe")))

    def test_linux_uses_xdg_open_for_paths(self):
        with (
            patch.object(apps.platform, "system", return_value="Linux"),
            patch.object(apps.subprocess, "Popen") as popen,
        ):
            apps.launch("/usr/share")
        self.assertEqual(popen.call_args.args[0], ["xdg-open", "/usr/share"])

    def test_url_is_passed_to_the_target_binary(self):
        with (
            patch.object(apps.platform, "system", return_value="Linux"),
            patch.object(apps.subprocess, "Popen") as popen,
        ):
            apps.launch("/usr/bin/chrome", "http://exemplo.com")
        self.assertEqual(popen.call_args.args[0], ["/usr/bin/chrome", "http://exemplo.com"])


if __name__ == "__main__":
    unittest.main()
