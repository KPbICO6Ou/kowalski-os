"""GTK3 omnibox window for kow-omni.

A borderless, centered launcher (~640px wide): prompt entry on top, a
scrollable monospace TextView streaming the answer below, and an action bar
that appears when the daemon asks to confirm a risky tool call.

Threading model: GTK owns the process main loop; a dedicated background
thread runs an asyncio event loop hosting OmniClient/OmniController. View
callbacks fire on that asyncio thread and marshal every widget update back to
the GTK thread with GLib.idle_add; entry activations hop the other way with
asyncio.run_coroutine_threadsafe.

Note: the Super+Space global hotkey is NOT bound here — it arrives with the
XFCE integration (libkeybinder) phase. Until then, launch `kow-omni` directly.

gi/GTK is imported lazily inside functions so this module can be imported (and
the package tested) on machines without PyGObject, e.g. macOS dev boxes.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from .client import OmniClient
from .controller import OmniController

WINDOW_WIDTH = 640
WINDOW_HEIGHT = 420


def gtk_available() -> bool:
    """True if PyGObject with GTK 3.0 can be loaded."""
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


class _AsyncioThread:
    """Background thread running an asyncio loop for the controller."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="kowui-asyncio", daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self) -> None:
        self._thread.start()

    def submit(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


class OmniWindow:
    """The omnibox window; constructed and used on the GTK main thread."""

    def __init__(self, client: OmniClient):
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk, Pango

        self._gtk = Gtk
        self._gdk = Gdk

        self._async = _AsyncioThread()
        self._async.start()
        self.controller = OmniController(client, _MarshalledCallbacks(self))

        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Kowalski Omnibox")
        self.window.set_decorated(False)  # borderless
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window.set_keep_above(True)
        self.window.connect("destroy", self._on_destroy)
        self.window.connect("key-press-event", self._on_key_press)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        self.window.add(box)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Ask Kowalski…")
        self.entry.connect("activate", self._on_activate)
        box.pack_start(self.entry, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_cursor_visible(False)
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.modify_font(Pango.FontDescription("monospace 11"))
        self.buffer = self.textview.get_buffer()
        scrolled.add(self.textview)
        box.pack_start(scrolled, True, True, 0)

        # Confirmation action bar (hidden until a ConfirmRequestEvent arrives)
        self.action_bar = Gtk.ActionBar()
        self.confirm_label = Gtk.Label(label="")
        self.confirm_label.set_line_wrap(True)
        self.action_bar.pack_start(self.confirm_label)
        allow = Gtk.Button(label="Allow")
        deny = Gtk.Button(label="Deny")
        allow.connect("clicked", self._on_confirm_clicked, True)
        deny.connect("clicked", self._on_confirm_clicked, False)
        self.action_bar.pack_end(allow)
        self.action_bar.pack_end(deny)
        box.pack_end(self.action_bar, False, False, 0)

        self._pending_request_id: str | None = None
        self.window.show_all()
        self.action_bar.hide()
        self.entry.grab_focus()

    # -- GTK-thread signal handlers ------------------------------------------------

    def _on_activate(self, _entry) -> None:
        prompt = self.entry.get_text().strip()
        if not prompt:
            return
        self.entry.set_text("")
        self.append_text(f"\n> {prompt}\n")
        self._async.submit(self.controller.submit(prompt))

    def _on_key_press(self, _widget, event) -> bool:
        Gdk = self._gdk
        keyval = event.keyval
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if keyval == Gdk.KEY_Escape:
            self.window.hide()  # hide, don't quit: the hotkey phase re-shows it
            return True
        if ctrl and keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self._gtk.main_quit()
            return True
        return False

    def _on_confirm_clicked(self, _button, approved: bool) -> None:
        if self._pending_request_id is None:
            return
        request_id = self._pending_request_id
        self._pending_request_id = None
        self.action_bar.hide()
        self.append_text(f"[{'allowed' if approved else 'denied'}]\n")
        self._async.submit(self.controller.answer_confirm(request_id, approved))

    def _on_destroy(self, _widget) -> None:
        self._async.stop()
        self._gtk.main_quit()

    # -- called via GLib.idle_add from the asyncio thread --------------------------

    def append_text(self, text: str) -> None:
        self.buffer.insert(self.buffer.get_end_iter(), text)
        mark = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        self.textview.scroll_mark_onscreen(mark)
        self.buffer.delete_mark(mark)

    def show_confirm(self, request_id: str, tool: str, risk: str, reason: str) -> None:
        self._pending_request_id = request_id
        self.confirm_label.set_text(f"{tool} [{risk}]: {reason}")
        self.action_bar.show_all()


class _MarshalledCallbacks:
    """Controller callbacks that hop from the asyncio thread to the GTK thread."""

    def __init__(self, view: OmniWindow):
        self.view = view

    def _idle(self, fn, *args) -> None:
        from gi.repository import GLib

        GLib.idle_add(lambda: (fn(*args), False)[1])

    def on_token(self, text: str) -> None:
        self._idle(self.view.append_text, text)

    def on_tool(self, tool: str, args: dict[str, Any]) -> None:
        self._idle(self.view.append_text, f"\n→ {tool}({args})\n")

    def on_tool_result(self, tool: str, ok: bool, content: str) -> None:
        status = "ok" if ok else "failed"
        first_line = content.splitlines()[0] if content else ""
        self._idle(self.view.append_text, f"← {tool}: {status} {first_line}\n")

    def on_confirm_request(
        self, request_id: str, tool: str, args: dict[str, Any], risk: str, reason: str
    ) -> None:
        self._idle(self.view.show_confirm, request_id, tool, risk, reason)

    def on_done(self, answer: str) -> None:
        self._idle(self.view.append_text, "\n")

    def on_error(self, message: str) -> None:
        self._idle(self.view.append_text, f"\nerror: {message}\n")


def run_gtk(client: OmniClient) -> int:
    """Build the window and enter the GTK main loop. Requires PyGObject."""
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    OmniWindow(client)
    Gtk.main()
    return 0
