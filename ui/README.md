# kowalski-ui (`kow-omni`)

The Kowalski OS omnibox: a small launcher-style client for the `kow-core`
agent daemon. Type a prompt, watch the answer stream in, and approve or deny
risky tool calls when the daemon asks for confirmation.

## Usage

The daemon must be running (`kow serve`). Then:

```sh
pip install -e ui            # from the monorepo root (core is a dependency)
kow-omni --cli               # terminal REPL, works on any OS (incl. macOS)
kow-omni                     # GTK3 window (Linux + PyGObject), falls back to --cli
kow-omni --socket /path/to/kowalski.sock   # override the daemon socket
```

In `--cli` mode tokens print as they stream, tool calls appear as dim
`→ tool(...)` lines, and confirmation requests prompt `allow? [y/N]`.
`exit` or Ctrl-D quits.

## GTK status

The GTK3 window (borderless, centered, entry + streaming monospace view +
Allow/Deny action bar) needs PyGObject and GTK3, i.e. a Linux desktop.
`gi` is imported lazily, so the package installs and tests fine without it.
The Super+Space global hotkey is not bound yet — it lands with the XFCE
integration (libkeybinder) phase; until then launch `kow-omni` directly.
Keys: Enter submits, Escape hides the window, Ctrl+Q quits.

## Architecture

```
kowui/
  client.py      OmniClient: async unix-socket client (one connection per ask,
                 confirm/status/tools on short separate connections)
  controller.py  OmniController: pure-asyncio event dispatch to view callbacks;
                 one conversation_id per omnibox session
  tty.py         terminal REPL view (--cli)
  gtk_view.py    GTK3 window view (lazy gi import; asyncio in a background
                 thread, UI updates marshalled via GLib.idle_add)
  app.py         kow-omni entry point: mode selection and fallback
```

Views never talk to the socket directly; they implement the controller's
callback protocol (`on_token`, `on_tool`, `on_tool_result`,
`on_confirm_request`, `on_done`, `on_error`).

## Protocol

Newline-delimited JSON over a unix socket — see
`core/kowalski/ipc/socket_service.py` and `core/kowalski/agent/events.py`.
The socket path resolves exactly like the daemon's (`kowalski.config.Config`):
`KOW_SOCKET_PATH` from `~/.config/kowalski/kowalski.conf`, else
`$XDG_RUNTIME_DIR/kowalski.sock`, else `~/.local/state/kowalski/kowalski.sock`.
Confirmations are answered on a separate connection from the ask stream.
