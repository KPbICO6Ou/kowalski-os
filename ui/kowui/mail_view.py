"""GTK3 mail window for kow-mail: message list → message view → AI panel.

Layout: a toolbar (search, folder, refresh) over a horizontal pane — the message
list on the left; the selected message (headers + body), the AI action bar
(Summarize / Draft reply / Translate / ask-about entry), the streaming AI output,
and a draft editor with Send on the right.

Threading model mirrors the omnibox (gtk_view.py): GTK owns the main loop, a
background AsyncioThread hosts MailController, callbacks marshal widget updates
back with GLib.idle_add. Draft-reply tokens stream into the editable draft
buffer; every other AI action streams into the read-only AI output."""

from __future__ import annotations

from .asyncio_thread import AsyncioThread
from .mail_controller import MailController

WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 640
LIST_WIDTH = 380


class MailWindow:
    """The mail window; constructed and used on the GTK main thread."""

    def __init__(self, backend, client):
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, Pango

        self.gtk = Gtk

        self.async_thread = AsyncioThread(name="kowui-mail-asyncio")
        self.async_thread.start()
        self.controller = MailController(backend, client, MarshalledMailCallbacks(self))

        self.current_message = None
        self.ai_target = "ai"  # where AI tokens stream: "ai" panel or the "draft" editor
        self.folder = "INBOX"

        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Kowalski Mail")
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window.connect("destroy", self.on_destroy)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("top", "bottom", "start", "end"):
            getattr(root, f"set_margin_{side}")(8)
        self.window.add(root)

        # Toolbar: search + folder + refresh
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search mail…")
        self.search_entry.connect("activate", self.on_search)
        bar.pack_start(self.search_entry, True, True, 0)
        self.folder_combo = Gtk.ComboBoxText()
        self.folder_combo.append_text("INBOX")
        self.folder_combo.set_active(0)
        self.folder_combo.connect("changed", self.on_folder_changed)
        bar.pack_start(self.folder_combo, False, False, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", self.on_search)
        bar.pack_start(refresh, False, False, 0)
        root.pack_start(bar, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(paned, True, True, 0)

        # Left: the message list (id, date, from, subject; bold when unread)
        self.list_store = Gtk.ListStore(str, str, str, str, int)
        self.list_view = Gtk.TreeView(model=self.list_store)
        for index, title, width, expand in ((1, "Date", 90, False), (2, "From", 150, False),
                                            (3, "Subject", -1, True)):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn(title, renderer, text=index, weight=4)
            column.set_expand(expand)
            if width > 0:
                column.set_min_width(width)
            self.list_view.append_column(column)
        self.list_view.connect("cursor-changed", self.on_row_selected)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroll.add(self.list_view)
        list_scroll.set_size_request(LIST_WIDTH, -1)
        paned.add1(list_scroll)

        # Right: message + AI panel + draft
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        paned.add2(right)

        self.header_label = Gtk.Label(label="", xalign=0)
        self.header_label.set_line_wrap(True)
        self.header_label.set_selectable(True)
        right.pack_start(self.header_label, False, False, 0)

        self.body_view, self.body_buffer = self.make_text_view(Pango, editable=False)
        right.pack_start(self.wrap_scrolled(self.body_view), True, True, 0)

        ai_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, action in (("Summarize", self.on_summarize),
                              ("Draft reply", self.on_draft_reply),
                              ("Translate", self.on_translate)):
            button = Gtk.Button(label=label)
            button.connect("clicked", action)
            ai_bar.pack_start(button, False, False, 0)
        self.question_entry = Gtk.Entry()
        self.question_entry.set_placeholder_text("Ask about this email…")
        self.question_entry.connect("activate", self.on_question)
        ai_bar.pack_start(self.question_entry, True, True, 0)
        right.pack_start(ai_bar, False, False, 0)

        self.ai_view, self.ai_buffer = self.make_text_view(Pango, editable=False)
        ai_scroll = self.wrap_scrolled(self.ai_view)
        ai_scroll.set_size_request(-1, 120)
        right.pack_start(ai_scroll, False, True, 0)

        self.draft_frame = Gtk.Frame(label="Reply draft")
        draft_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.draft_view, self.draft_buffer = self.make_text_view(Pango, editable=True)
        draft_scroll = self.wrap_scrolled(self.draft_view)
        draft_scroll.set_size_request(-1, 120)
        draft_box.pack_start(draft_scroll, True, True, 0)
        send_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.send_button = Gtk.Button(label="Send")
        self.send_button.connect("clicked", self.on_send)
        send_bar.pack_end(self.send_button, False, False, 0)
        draft_box.pack_start(send_bar, False, False, 0)
        self.draft_frame.add(draft_box)
        right.pack_start(self.draft_frame, False, True, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        root.pack_end(self.status_label, False, False, 0)

        self.window.show_all()
        self.draft_frame.hide()
        self.async_thread.submit(self.controller.load_folders())
        self.async_thread.submit(self.controller.search("", folder=self.folder))

    # -- widget factories ----------------------------------------------------------

    def make_text_view(self, Pango, *, editable: bool):
        view = self.gtk.TextView()
        view.set_editable(editable)
        view.set_cursor_visible(editable)
        view.set_wrap_mode(self.gtk.WrapMode.WORD_CHAR)
        view.modify_font(Pango.FontDescription("monospace 10"))
        return view, view.get_buffer()

    def wrap_scrolled(self, widget):
        scrolled = self.gtk.ScrolledWindow()
        scrolled.set_policy(self.gtk.PolicyType.AUTOMATIC, self.gtk.PolicyType.AUTOMATIC)
        scrolled.add(widget)
        return scrolled

    # -- GTK-thread signal handlers ------------------------------------------------

    def on_search(self, _widget) -> None:
        query = self.search_entry.get_text().strip()
        self.status(f"searching '{query}'…" if query else "loading…")
        self.async_thread.submit(self.controller.search(query, folder=self.folder))

    def on_folder_changed(self, combo) -> None:
        self.folder = combo.get_active_text() or "INBOX"
        self.on_search(combo)

    def on_row_selected(self, view) -> None:
        path, _column = view.get_cursor()
        if path is None:
            return
        message_id = self.list_store[path][0]
        if self.current_message is not None and str(self.current_message.id) == message_id:
            return
        self.async_thread.submit(self.controller.open_message(message_id))

    def submit_ai(self, coro, target: str) -> None:
        if self.current_message is None:
            self.status("select a message first")
            return
        self.ai_target = target
        buffer = self.draft_buffer if target == "draft" else self.ai_buffer
        buffer.set_text("")
        if target == "draft":
            self.draft_frame.show_all()
        self.status("thinking…")
        self.async_thread.submit(coro)

    def on_summarize(self, _b) -> None:
        if self.current_message is not None:
            self.submit_ai(self.controller.summarize(self.current_message), "ai")

    def on_draft_reply(self, _b) -> None:
        if self.current_message is not None:
            self.submit_ai(self.controller.draft_reply(self.current_message), "draft")

    def on_translate(self, _b) -> None:
        if self.current_message is not None:
            self.submit_ai(self.controller.translate(self.current_message), "ai")

    def on_question(self, entry) -> None:
        question = entry.get_text().strip()
        if question and self.current_message is not None:
            entry.set_text("")
            self.submit_ai(self.controller.ask_about(self.current_message, question), "ai")

    def on_send(self, _b) -> None:
        if self.current_message is None:
            return
        Gtk = self.gtk
        start, end = self.draft_buffer.get_bounds()
        body = self.draft_buffer.get_text(start, end, True).strip()
        if not body:
            self.status("draft is empty")
            return
        message = self.current_message
        dialog = Gtk.MessageDialog(
            transient_for=self.window, modal=True,
            message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO,
            text=f"Send reply to {message.from_addr}?",
        )
        dialog.format_secondary_text(f"Subject: Re: {message.subject}\n\n{body[:200]}")
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.YES:
            self.status("sending…")
            self.async_thread.submit(self.controller.send_reply(message, body))

    def on_destroy(self, _widget) -> None:
        self.async_thread.stop()
        self.gtk.main_quit()

    # -- called via GLib.idle_add from the asyncio thread --------------------------

    def status(self, text: str) -> None:
        self.status_label.set_text(text)

    def show_folders(self, folders: list[str]) -> None:
        self.folder_combo.remove_all()
        for name in folders or ["INBOX"]:
            self.folder_combo.append_text(name)
        self.folder_combo.set_active(0)

    def show_messages(self, summaries) -> None:
        self.list_store.clear()
        for summary in summaries:
            weight = 700 if summary.unread else 400
            self.list_store.append(
                [str(summary.id), summary.date, summary.from_addr, summary.subject, weight]
            )
        self.status(f"{len(summaries)} message(s)")

    def show_message(self, message) -> None:
        self.current_message = message
        self.header_label.set_markup(
            f"<b>{escape_markup(message.subject)}</b>\n"
            f"{escape_markup(message.from_addr)} — {escape_markup(message.date)}"
        )
        self.body_buffer.set_text(message.body_text or "")
        self.ai_buffer.set_text("")
        self.draft_buffer.set_text("")
        self.draft_frame.hide()
        self.status("")

    def append_ai(self, text: str) -> None:
        buffer = self.draft_buffer if self.ai_target == "draft" else self.ai_buffer
        buffer.insert(buffer.get_end_iter(), text)

    def ai_finished(self) -> None:
        self.status("")

    def sent_ok(self, detail: str) -> None:
        self.draft_frame.hide()
        self.status(detail)

    def show_error(self, message: str) -> None:
        self.status(f"error: {message}")


def escape_markup(text: str) -> str:
    from gi.repository import GLib

    return GLib.markup_escape_text(text or "")


class MarshalledMailCallbacks:
    """MailController callbacks that hop from the asyncio thread to GTK."""

    def __init__(self, view: MailWindow):
        self.view = view

    def idle(self, fn, *args) -> None:
        from gi.repository import GLib

        GLib.idle_add(lambda: (fn(*args), False)[1])

    def on_folders(self, folders):
        self.idle(self.view.show_folders, folders)

    def on_messages(self, summaries):
        self.idle(self.view.show_messages, summaries)

    def on_message(self, message):
        self.idle(self.view.show_message, message)

    def on_ai_token(self, text):
        self.idle(self.view.append_ai, text)

    def on_ai_done(self):
        self.idle(self.view.ai_finished)

    def on_sent(self, detail):
        self.idle(self.view.sent_ok, detail)

    def on_error(self, message):
        self.idle(self.view.show_error, message)


def run_mail_gtk(backend, client) -> int:
    """Build the mail window and enter the GTK main loop. Requires PyGObject."""
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    MailWindow(backend, client)
    Gtk.main()
    return 0
