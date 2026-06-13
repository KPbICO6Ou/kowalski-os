## Kowalski OS — habla con tu computadora

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS convierte un escritorio Linux común y corriente en uno con el que simplemente puedes hablar. Pídele con palabras sencillas — escribiendo o con la voz — que busque un archivo, ponga un recordatorio, resuma un correo, ejecute un comando o mire lo que hay en tu pantalla. El asistente funciona **localmente** en tu propia máquina (a través de [Ollama](https://ollama.com)), así que tus datos nunca salen de tu computadora.

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | **[Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md)** | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### ¿Qué puede hacer?

Después de instalarlo, puedes escribir cosas como:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **Encontrar cosas** — por nombre, por contenido o por significado ("el documento sobre el viaje").
- **Recordar** — notas, recordatorios y datos sobre ti que puede recuperar más tarde.
- **Correo** — buscar, leer, redactar y (con tu aprobación) enviar.
- **Ver tu pantalla** — responder "¿qué hay en la pantalla ahora mismo?".
- **Hacer cosas** — abrir aplicaciones, controlar ventanas, ejecutar comandos de shell, automatizar tareas de varios pasos.
- **Hablar** — un modo de voz con manos libres (palabra de activación → voz a texto → respuesta → texto a voz).

### ¿Es seguro?

Sí, por diseño:

- El asistente solo puede tocar las carpetas que tú permitas.
- Cualquier cosa arriesgada — enviar un correo, ejecutar un comando, escribir en una ventana — **pide tu confirmación primero**, y puedes decir que no.
- Los comandos de shell se ejecutan dentro de un entorno aislado (sandbox) en Linux.
- Cada acción se escribe en un registro local que puedes revisar con `kow journal tail`.
- El modelo de lenguaje funciona localmente a través de Ollama — nada se envía a la nube.

### Requisitos

- **Ubuntu 24.04** con el escritorio XFCE (también puedes ejecutar el asistente en macOS para desarrollo).
- **[Ollama](https://ollama.com)** con un modelo que admita llamadas a herramientas (tool-calling), p. ej. `qwen2.5:14b` (o `qwen2.5:7b` en una máquina más modesta).
- Se **recomienda una GPU** para respuestas rápidas, pero no es obligatoria.

### Instalación (Ubuntu)

Instala el asistente principal e inícialo en segundo plano:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

Agrega componentes opcionales cuando quieras:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> ¿Aún no tienes los archivos `.deb`? Constrúyelos con `make deb` (requiere Docker), o usa la configuración para desarrolladores que aparece más abajo.

### Pruébalo (configuración para desarrolladores — Linux o macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### Primeros pasos

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### Cómo está organizado

Kowalski OS tiene un único "cerebro" — el servicio `kow-core` — con el que habla cada interfaz: hoy la línea de comandos, y en el escritorio el Omnibox, la voz y las ventanas de chat. Así el asistente se comporta igual en todas partes.

| Parte | Qué es |
|---|---|
| `core/` | el cerebro del asistente: comprender las solicitudes, las herramientas, las reglas de seguridad, el registro |
| `ui/` | el Omnibox (presiona Super+Space) y las piezas del escritorio |
| `voice/` | palabra de activación, voz a texto, texto a voz |
| `indexer/` | búsqueda semántica de archivos |
| `setup/` | el asistente de configuración inicial |
| `provision/` | scripts que instalan todo el sistema en una máquina nueva |
| `packaging/` | los paquetes `.deb` y el tema del escritorio |

Más detalles: [Architecture](docs/ARCHITECTURE.md) · [Installing on a machine](docs/PROVISIONING.md) · [Packaging](docs/PACKAGING.md).

### Estado del proyecto

Kowalski OS está en **desarrollo temprano**. El asistente ya funciona hoy a través de la línea de comandos; las piezas gráficas del escritorio (la ventana del Omnibox, la voz, la instalación completa del sistema) están construidas y probadas, pero necesitan una máquina Linux real con una GPU para cobrar vida por completo. Espera algunas asperezas.

### Licencia

[Apache-2.0](LICENSE).
