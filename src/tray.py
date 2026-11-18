"""Windows notification-area integration."""
from __future__ import annotations
import threading
from typing import Callable, Any

class SystemTrayController:
    def __init__(
        self,
        on_show: Callable[[], None],
        on_pause: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.on_show, self.on_pause, self.on_exit = on_show, on_pause, on_exit
        self.icon: Any = None

    @staticmethod
    def _image():
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (64, 64), "#111827")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 59, 59), radius=15, fill="#3B82F6")
        draw.rounded_rectangle((19, 16, 45, 48), radius=7, outline="#FFFFFF", width=4)
        draw.line((25, 27, 39, 27), fill="#FFFFFF", width=3)
        draw.line((25, 35, 39, 35), fill="#FFFFFF", width=3)
        return image

    def start(self) -> None:
        if self.icon is not None:
            return
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("Открыть Focus Guard", lambda _icon, _item: self.on_show()),
            pystray.MenuItem("Пауза / продолжить", lambda _icon, _item: self.on_pause()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda _icon, _item: self.on_exit()),
        )
        self.icon = pystray.Icon("FocusGuard", self._image(), "Focus Guard", menu)
        self.icon.run_detached()

    def stop(self) -> None:
        icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
