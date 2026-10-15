import mss
from PIL import Image


def get_primary_monitor_size() -> tuple[int, int]:
    with mss.mss() as capture:
        monitor = capture.monitors[1]
        return monitor["width"], monitor["height"]


def take_screenshot(
    filepath: str,
    region: tuple[int, int, int, int] | None = None,
) -> str:
    """Captures the primary display or a validated crop in local coordinates."""
    with mss.mss() as capture:
        monitor = capture.monitors[1]
        if region is None:
            bounds = {
                "left": monitor["left"],
                "top": monitor["top"],
                "width": monitor["width"],
                "height": monitor["height"],
            }
        else:
            x, y, width, height = region
            if (
                x < 0
                or y < 0
                or width <= 0
                or height <= 0
                or x + width > monitor["width"]
                or y + height > monitor["height"]
            ):
                raise ValueError("A região solicitada está fora dos limites da tela.")
            bounds = {
                "left": monitor["left"] + x,
                "top": monitor["top"] + y,
                "width": width,
                "height": height,
            }

        image = capture.grab(bounds)
        Image.frombytes("RGB", image.size, image.rgb).save(filepath, format="PNG")
    return filepath
