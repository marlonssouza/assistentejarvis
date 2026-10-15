import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis import hands, system


def _fake_psutil():
    memory = SimpleNamespace(percent=42.0, used=8 * 1024**3, total=16 * 1024**3)
    disk = SimpleNamespace(percent=55.0, used=100 * 1024**3, total=200 * 1024**3)
    processes = [
        SimpleNamespace(info={"pid": 1, "name": "a.exe", "memory_info": SimpleNamespace(rss=10 * 1024**2)}),
        SimpleNamespace(info={"pid": 2, "name": "b.exe", "memory_info": SimpleNamespace(rss=90 * 1024**2)}),
        SimpleNamespace(info={"pid": 3, "name": "c.exe", "memory_info": None}),
        SimpleNamespace(info={"pid": 4, "name": "d.exe", "memory_info": SimpleNamespace(rss=50 * 1024**2)}),
    ]
    return SimpleNamespace(
        virtual_memory=lambda: memory,
        disk_usage=lambda _path: disk,
        cpu_percent=lambda interval=0.5: 33.3,
        process_iter=lambda _fields: processes,
        NoSuchProcess=ProcessLookupError,
        AccessDenied=PermissionError,
    )


class SystemStatusTests(unittest.TestCase):
    def test_status_reports_cpu_ram_and_disk(self):
        with patch.object(system, "_import_psutil", return_value=_fake_psutil()):
            data = system.system_status()
        self.assertEqual(data["cpu_percent"], 33.3)
        self.assertEqual(data["ram_percent"], 42.0)
        self.assertEqual(data["disk_percent"], 55.0)
        self.assertRegex(data["updated"], r"^\d{2}:\d{2}:\d{2}$")

    def test_top_processes_sorts_by_memory_and_skips_unknown(self):
        with patch.object(system, "_import_psutil", return_value=_fake_psutil()):
            top = system.top_processes(2)
        self.assertEqual([item["name"] for item in top], ["b.exe", "d.exe"])
        self.assertEqual(top[0]["memory_mb"], 90.0)

    def test_missing_psutil_raises_clear_error(self):
        with patch.object(system, "_import_psutil", side_effect=RuntimeError("psutil")):
            with self.assertRaisesRegex(RuntimeError, "psutil"):
                system.system_status()


class VolumeTests(unittest.TestCase):
    def test_invalid_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "volume"):
            system.set_volume("boost", 10)

    def test_invalid_level_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "0 e 100"):
            system.set_volume("set", 150)

    def test_dispatches_to_platform_implementation(self):
        with (
            patch.object(system.platform, "system", return_value="Linux"),
            patch.object(system, "_volume_linux", return_value=42) as linux,
        ):
            result = system.set_volume("set", 42)
        linux.assert_called_once_with("set", 42)
        self.assertEqual(result["level"], 42)

    def test_windows_backend_is_used_on_windows(self):
        with (
            patch.object(system.platform, "system", return_value="Windows"),
            patch.object(system, "_volume_windows", return_value=100) as windows,
        ):
            system.set_volume("up", 10)
        windows.assert_called_once_with("up", 10)


class BrightnessTests(unittest.TestCase):
    def test_invalid_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "brilho"):
            system.set_brightness("blink")

    def test_missing_dependency_raises_clear_error(self):
        with patch.dict("sys.modules", {"screen_brightness_control": None}):
            with self.assertRaisesRegex(RuntimeError, "screen-brightness-control"):
                system.set_brightness("set", 50)

    def test_sets_value_with_dependency(self):
        fake = SimpleNamespace(get_brightness=lambda display: [40], set_brightness=lambda *_a, **_k: None)
        with patch.dict("sys.modules", {"screen_brightness_control": fake}):
            result = system.set_brightness("up", 20)
        self.assertEqual(result["level"], 60)


class PowerTests(unittest.TestCase):
    def test_invalid_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "energia"):
            system.power_action("explodir")

    def test_alias_maps_to_command_on_windows(self):
        with (
            patch.object(system.platform, "system", return_value="Windows"),
            patch.object(system.subprocess, "Popen") as popen,
        ):
            result = system.power_action("desligar")
        self.assertEqual(result, "shutdown")
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][:2], ["shutdown", "/s"])

    def test_lock_uses_rundll32_on_windows(self):
        with (
            patch.object(system.platform, "system", return_value="Windows"),
            patch.object(system.subprocess, "Popen") as popen,
        ):
            system.power_action("bloquear")
        self.assertIn("user32.dll,LockWorkStation", popen.call_args.args[0])

    def test_linux_suspend_uses_systemctl(self):
        with (
            patch.object(system.platform, "system", return_value="Linux"),
            patch.object(system.subprocess, "Popen") as popen,
        ):
            system.power_action("suspender")
        self.assertEqual(popen.call_args.args[0], ["systemctl", "suspend"])


class PasswordTests(unittest.TestCase):
    def test_password_meets_complexity_requirements(self):
        with patch.object(system, "copy_to_clipboard", return_value=True):
            data = system.generate_password(16, include_symbols=True)
        password = data["password"]
        self.assertEqual(len(password), 16)
        self.assertTrue(any(c.islower() for c in password))
        self.assertTrue(any(c.isupper() for c in password))
        self.assertTrue(any(c.isdigit() for c in password))
        self.assertTrue(data["copied"])

    def test_password_without_symbols(self):
        alphabet = set()
        with patch.object(system, "copy_to_clipboard", return_value=False):
            for _ in range(3):
                alphabet.update(system.generate_password(24, include_symbols=False)["password"])
        symbols = set("!@#$%^&*()-_=+[]{};:,.?")
        self.assertFalse(alphabet & symbols)

    def test_out_of_range_length_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "8 e 128"):
            system.generate_password(4)


class ReminderTests(unittest.TestCase):
    def test_set_and_list_reminder(self):
        result = system.set_reminder(30, "tomar água")
        self.assertEqual(result["task"], "tomar água")
        pending = system.list_reminders()
        self.assertTrue(any(item["id"] == result["id"] for item in pending))

    def test_reminder_validation(self):
        with self.assertRaisesRegex(ValueError, "minutos"):
            system.set_reminder(0, "nada")
        with self.assertRaisesRegex(ValueError, "tarefa"):
            system.set_reminder(5, "   ")

    def test_notifier_is_called_when_fired(self):
        received = []
        system.configure_reminder_notifier(received.append)
        try:
            system._scheduler._fire({"id": 999, "task": "teste"})
        finally:
            system.configure_reminder_notifier(None)
        self.assertEqual(received[0]["task"], "teste")

    def test_notifier_errors_do_not_propagate(self):
        def boom(_reminder):
            raise RuntimeError("falha proposital")

        system.configure_reminder_notifier(boom)
        try:
            system._scheduler._fire({"id": 1, "task": "x"})  # não deve levantar
        finally:
            system.configure_reminder_notifier(None)


class HandsSystemToolTests(unittest.TestCase):
    def test_system_status_tool_returns_json(self):
        with patch.object(hands.system, "system_status", return_value={"cpu_percent": 1.0}):
            self.assertEqual(json.loads(hands.system_status())["cpu_percent"], 1.0)

    def test_top_processes_tool_returns_json(self):
        with patch.object(hands.system, "top_processes", return_value=[{"name": "x"}]):
            self.assertEqual(json.loads(hands.top_processes(3))[0]["name"], "x")

    def test_generate_password_tool_returns_json(self):
        data = json.loads(hands.generate_password(12))
        self.assertEqual(len(data["password"]), 12)

    def test_set_volume_requires_confirmation(self):
        with patch.object(hands, "confirm_action", return_value=False) as confirm:
            self.assertEqual(hands.set_volume("set", 50), "Ação cancelada pelo usuário.")
            confirm.assert_called_once()

    def test_set_brightness_requires_confirmation(self):
        with patch.object(hands, "confirm_action", return_value=False) as confirm:
            self.assertEqual(
                hands.set_brightness("down"), "Ação cancelada pelo usuário."
            )
            confirm.assert_called_once()

    def test_power_action_requires_confirmation(self):
        with (
            patch.object(hands, "confirm_action", return_value=False) as confirm,
            patch.object(hands.system, "power_action") as action,
        ):
            self.assertEqual(
                hands.power_action("desligar"), "Ação cancelada pelo usuário."
            )
            action.assert_not_called()
            confirm.assert_called_once()

    def test_power_action_runs_after_confirmation(self):
        with (
            patch.object(hands, "confirm_action", return_value=True),
            patch.object(hands.system, "power_action", return_value="lock") as action,
        ):
            result = hands.power_action("bloquear")
        action.assert_called_once_with("bloquear")
        self.assertIn("lock", result)

    def test_open_special_folder_launches_resolved_path(self):
        target = Path("C:/Users/Teste/Downloads")
        with (
            patch.object(hands.apps, "resolve_special_folder", return_value=target),
            patch.object(hands.apps, "launch") as launch,
        ):
            data = json.loads(hands.open_special_folder("Downloads"))
        launch.assert_called_once_with(target)
        self.assertEqual(data["path"], str(target))

    def test_open_special_folder_rejects_unknown_name(self):
        with (
            patch.object(hands.apps, "resolve_special_folder", return_value=None),
            patch.object(hands.apps, "launch") as launch,
        ):
            with self.assertRaisesRegex(FileNotFoundError, "pasta especial"):
                hands.open_special_folder("lugar-nenhum")
            launch.assert_not_called()

    def test_new_tools_are_registered_with_expected_risk(self):
        expected = {
            "open_special_folder": "safe",
            "system_status": "safe",
            "top_processes": "safe",
            "generate_password": "safe",
            "set_volume": "dangerous",
            "set_brightness": "dangerous",
            "power_action": "dangerous",
            "set_reminder": "safe",
            "list_reminders": "safe",
        }
        for tool, risk in expected.items():
            self.assertIn(tool, hands.TOOL_HANDLERS)
            self.assertEqual(hands.TOOL_RISK[tool], risk)


if __name__ == "__main__":
    unittest.main()
