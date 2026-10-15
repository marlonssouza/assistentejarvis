import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis import hands, memory


class HandsTests(unittest.TestCase):
    def test_file_listing_is_confined_and_hides_dotfiles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "visible.txt").touch()
            (root / ".private").touch()
            with patch.object(hands, "ALLOWED_FILES_DIR", root):
                result = hands.list_files(".")
                self.assertIn("visible.txt", result)
                self.assertNotIn(".private", result)
                with self.assertRaisesRegex(ValueError, "fora"):
                    hands.list_files("..")

    def test_read_file_is_confined_to_allowed_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.txt").write_text("conteúdo", encoding="utf-8")
            with patch.object(hands, "ALLOWED_FILES_DIR", root):
                data = json.loads(hands.read_file("notes.txt"))
                self.assertEqual(data["content"], "conteúdo")
                with self.assertRaisesRegex(ValueError, "fora"):
                    hands.read_file("../segredo.txt")

    def test_write_file_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(hands, "ALLOWED_FILES_DIR", root),
                patch.object(hands, "confirm_action", return_value=False),
            ):
                self.assertEqual(
                    hands.write_file("novo.txt", "x"), "Ação cancelada pelo usuário."
                )
            self.assertFalse((root / "novo.txt").exists())

    def test_write_file_writes_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(hands, "ALLOWED_FILES_DIR", root),
                patch.object(hands, "confirm_action", return_value=True),
            ):
                hands.write_file("novo.txt", "olá")
            self.assertEqual((root / "novo.txt").read_text(encoding="utf-8"), "olá")

    def test_safe_tools_do_not_require_confirmation(self):
        data = json.loads(hands.get_datetime())
        self.assertIn("iso", data)
        info = json.loads(hands.get_system_info())
        self.assertIn("os", info)

    def test_open_application_rejects_unknown_app_before_confirmation(self):
        with (
            patch.object(hands.apps, "resolve_browser", return_value=None),
            patch.object(hands.apps, "resolve_windows_protocol", return_value=None),
            patch.object(hands.apps, "resolve_special_folder", return_value=None),
            patch.object(hands.apps, "resolve_application", return_value=None),
            patch.object(hands.apps, "search_windows_executable", return_value=None),
            patch.object(hands, "confirm_action") as confirm,
        ):
            with self.assertRaisesRegex(FileNotFoundError, "não foi encontrado"):
                hands.open_application("app-que-nao-existe-xyz")
            confirm.assert_not_called()

    def test_confirmation_fails_closed_without_interactive_input(self):
        with (
            patch("jarvis.security.CONFIRM_CHANNEL", "terminal"),
            patch("builtins.input", side_effect=EOFError),
        ):
            self.assertFalse(hands.confirm_action("abrir um aplicativo"))

    def test_click_requires_confirmation(self):
        with (
            patch.object(hands.pyautogui, "size", return_value=(100, 80)),
            patch.object(hands, "confirm_action", return_value=False),
            patch.object(hands.pyautogui, "click") as click,
        ):
            self.assertEqual(hands.click_at(10, 10), "Ação cancelada pelo usuário.")
            click.assert_not_called()

    def test_click_rejects_out_of_bounds_coordinates(self):
        with (
            patch.object(hands.pyautogui, "size", return_value=(100, 80)),
            patch.object(hands, "confirm_action") as confirm,
        ):
            with self.assertRaisesRegex(ValueError, "fora da tela"):
                hands.click_at(100, 10)
            confirm.assert_not_called()

    def test_mouse_failsafe_is_reported_as_a_safe_cancellation(self):
        with (
            patch.object(hands.pyautogui, "size", return_value=(100, 80)),
            patch.object(hands, "confirm_action", return_value=True),
            patch.object(
                hands.pyautogui,
                "click",
                side_effect=hands.pyautogui.FailSafeException,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "mecanismo de segurança"):
                hands.execute_tool("click_at", {"x": 10, "y": 10})

    def test_text_limit_is_checked_before_confirmation(self):
        with patch.object(hands, "confirm_action") as confirm:
            with self.assertRaisesRegex(ValueError, "500"):
                hands.type_text("x" * 501)
            confirm.assert_not_called()

    def test_unsafe_hotkey_is_rejected(self):
        with patch.object(hands, "confirm_action") as confirm:
            with self.assertRaisesRegex(ValueError, "não permitido"):
                hands.press_hotkey(["alt", "f4"])
            confirm.assert_not_called()

    def test_run_command_requires_confirmation(self):
        with patch.object(hands, "confirm_action", return_value=False) as confirm:
            self.assertEqual(
                hands.run_command("whoami"), "Ação cancelada pelo usuário."
            )
            confirm.assert_called_once()

    def test_capture_screen_is_disabled_by_flag(self):
        with (
            patch.object(hands, "SCREEN_CAPTURE_ENABLED", False),
            patch.object(hands, "confirm_action") as confirm,
        ):
            with self.assertRaisesRegex(RuntimeError, "desativada"):
                hands.capture_screen()
            confirm.assert_not_called()

    def test_capture_screen_requires_confirmation(self):
        with (
            patch.object(hands, "SCREEN_CAPTURE_ENABLED", True),
            patch.object(hands, "confirm_action", return_value=False) as confirm,
        ):
            self.assertEqual(
                hands.capture_screen(), "Ação cancelada pelo usuário."
            )
            confirm.assert_called_once()

    def test_capture_screen_returns_image_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = str(Path(temp_dir) / "shot.png")

            def fake_screenshot(path, region=None):
                Path(path).write_bytes(b"png")
                return path

            with (
                patch.object(hands, "SCREEN_CAPTURE_ENABLED", True),
                patch.object(hands, "confirm_action", return_value=True),
                patch("jarvis.eyes.take_screenshot", side_effect=fake_screenshot),
                patch.object(hands.tempfile, "gettempdir", return_value=temp_dir),
            ):
                data = json.loads(hands.capture_screen([0, 0, 10, 10]))

            self.assertTrue(Path(data["image_path"]).is_file())
            self.assertEqual(data["region"], [0, 0, 10, 10])

    def test_capture_screen_rejects_bad_region(self):
        with patch.object(hands, "SCREEN_CAPTURE_ENABLED", True):
            with self.assertRaisesRegex(ValueError, "quatro inteiros"):
                hands.capture_screen([0, 0, 10])

    def test_create_directory_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(hands, "ALLOWED_FILES_DIR", root),
                patch.object(hands, "confirm_action", return_value=False),
            ):
                self.assertEqual(
                    hands.create_directory("nova"), "Ação cancelada pelo usuário."
                )
            self.assertFalse((root / "nova").exists())

    def test_create_directory_creates_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(hands, "ALLOWED_FILES_DIR", root),
                patch.object(hands, "confirm_action", return_value=True),
            ):
                data = json.loads(hands.create_directory("nova/sub"))
            self.assertTrue((root / "nova" / "sub").is_dir())
            self.assertTrue(data["created"])

    def test_create_directory_reports_existing_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "existente").mkdir()
            with (
                patch.object(hands, "ALLOWED_FILES_DIR", root),
                patch.object(hands, "confirm_action") as confirm,
            ):
                data = json.loads(hands.create_directory("existente"))
            self.assertFalse(data["created"])
            self.assertTrue(data["already_existed"])
            confirm.assert_not_called()

    def test_create_directory_is_confined_to_authorized_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(hands, "ALLOWED_FILES_DIR", root),
                patch.object(hands, "EXTRA_ALLOWED_DIRS", []),
                patch.object(hands, "confirm_action") as confirm,
            ):
                with self.assertRaisesRegex(ValueError, "fora"):
                    hands.create_directory("../escapa")
            confirm.assert_not_called()

    def test_create_directory_allows_extra_authorized_dir(self):
        with tempfile.TemporaryDirectory() as base:
            allowed = Path(base)
            extra = allowed / "Desktop"
            extra.mkdir()
            with (
                patch.object(hands, "ALLOWED_FILES_DIR", allowed),
                patch.object(hands, "EXTRA_ALLOWED_DIRS", [extra]),
                patch.object(hands, "confirm_action", return_value=True),
            ):
                hands.create_directory(str(extra / "teste"))
            self.assertTrue((extra / "teste").is_dir())

    def test_search_web_browser_opens_google(self):
        with (
            patch.object(hands, "_launch_browser_url") as launch,
            patch.object(hands.apps, "resolve_browser", return_value=None),
        ):
            data = json.loads(hands.search_web_browser("futebol"))
        self.assertIn("google.com/search", data["url"])
        self.assertIn("futebol", data["url"])
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[1], data["url"])

    def test_search_web_browser_rejects_empty_query(self):
        with self.assertRaisesRegex(ValueError, "vazia"):
            hands.search_web_browser("   ")

    def test_open_application_finds_browser_by_name(self):
        fake = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        with (
            patch.object(hands.apps, "resolve_browser", return_value=fake),
            patch.object(hands, "confirm_action", return_value=True),
            patch.object(hands, "_launch_browser_url") as launch,
        ):
            result = hands.open_application("chrome")
        self.assertIn("aberto", result)
        launch.assert_called_once_with(fake, "about:blank")

    def test_open_application_opens_windows_protocol(self):
        with (
            patch.object(hands.apps, "resolve_browser", return_value=None),
            patch.object(
                hands.apps, "resolve_windows_protocol", return_value="ms-settings:"
            ),
            patch.object(hands, "confirm_action", return_value=True),
            patch.object(hands.apps, "launch") as launch,
        ):
            result = hands.open_application("configurações")
        launch.assert_called_once_with("ms-settings:")
        self.assertIn("aberto", result)

    def test_open_application_opens_special_folder(self):
        target = Path("C:/Users/Teste/Desktop")
        with (
            patch.object(hands.apps, "resolve_browser", return_value=None),
            patch.object(hands.apps, "resolve_windows_protocol", return_value=None),
            patch.object(hands.apps, "resolve_special_folder", return_value=target),
            patch.object(hands, "confirm_action", return_value=True),
            patch.object(hands.apps, "launch") as launch,
        ):
            result = hands.open_application("Área de Trabalho")
        launch.assert_called_once_with(target)
        self.assertIn("Pasta", result)

    def test_open_application_searches_disk_as_last_resort(self):
        target = Path("C:/Program Files/App/app.exe")
        with (
            patch.object(hands.apps, "resolve_browser", return_value=None),
            patch.object(hands.apps, "resolve_windows_protocol", return_value=None),
            patch.object(hands.apps, "resolve_special_folder", return_value=None),
            patch.object(hands.apps, "resolve_application", return_value=None),
            patch.object(hands.apps, "search_windows_executable", return_value=target),
            patch.object(hands, "confirm_action", return_value=True),
            patch.object(hands.apps, "launch") as launch,
        ):
            result = hands.open_application("meuapp")
        launch.assert_called_once_with(target)
        self.assertIn("aberto", result)

    def test_unknown_tool_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Ferramenta desconhecida"):
            hands.execute_tool("run_shell_command", {"command": "whoami"})

    def test_remember_stores_structured_fact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = memory.Memory(Path(temp_dir) / "memory.json")
            with patch.object(hands.memory, "get_store", return_value=store):
                result = hands.remember("prefiro café", aspect="preference")
            self.assertEqual(result, "Fato memorizado.")
            record = store.records()[0]
            self.assertEqual(record["text"], "prefiro café")
            self.assertEqual(record["aspect"], "preference")

    def test_recall_returns_structured_facts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = memory.Memory(Path(temp_dir) / "memory.json")
            store.add_fact("meu aniversário é 12 de março", aspect="identity")
            with patch.object(hands.memory, "get_store", return_value=store):
                data = json.loads(hands.recall("aniversário"))
            self.assertEqual(data["facts"][0]["aspect"], "identity")
            self.assertIn("id", data["facts"][0])

    def test_list_skills_reports_policies(self):
        from jarvis import policies as policies_module

        policy = policies_module.Policy(
            name="email", title="E-mail", description="urgente", body="corpo"
        )
        with patch.object(hands.policies, "list_policies", return_value=[policy]):
            data = json.loads(hands.list_skills())
        self.assertEqual(data["skills"][0]["name"], "email")
        self.assertEqual(data["skills"][0]["title"], "E-mail")

    def test_mcp_list_tools_delegates_with_server(self):
        with patch.object(
            hands.mcp, "list_tools", return_value={"tools": {}, "errors": {}}
        ) as lister:
            json.loads(hands.mcp_list_tools("servidor"))
        lister.assert_called_once_with("servidor")

    def test_mcp_list_tools_without_server_lists_all(self):
        with patch.object(
            hands.mcp, "list_tools", return_value={"tools": {}, "errors": {}}
        ) as lister:
            hands.mcp_list_tools()
        lister.assert_called_once_with(None)

    def test_mcp_call_delegates(self):
        with patch.object(
            hands.mcp, "call_tool", return_value={"is_error": False, "content": []}
        ) as caller:
            data = json.loads(hands.mcp_call("srv", "tool", {"a": 1}))
        caller.assert_called_once_with("srv", "tool", {"a": 1})
        self.assertFalse(data["is_error"])

    def test_new_tools_are_risk_classified(self):
        self.assertEqual(hands.TOOL_RISK["list_skills"], hands.SAFE)
        self.assertEqual(hands.TOOL_RISK["mcp_list_tools"], hands.SAFE)
        self.assertEqual(hands.TOOL_RISK["mcp_call"], hands.DANGEROUS)


if __name__ == "__main__":
    unittest.main()
