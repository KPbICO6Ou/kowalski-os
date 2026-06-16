# kowalski-voice (`kow-voice`)

The Kowalski OS voice pipeline: **wake word → STT → agent → TTS**, with barge-in.

```
IDLE --wake--> LISTENING --VAD endpoint--> TRANSCRIBING --POST /api/stt-->
THINKING --kow-core stream--> SPEAKING (POST /api/tts per sentence) --> IDLE
```

The control flow lives in a pure asyncio state machine (`orchestrator.py`) that
depends only on small protocols. Hardware (microphone, wake word, VAD, playback)
and network (STT/TTS services, the kow-core agent) sit behind those protocols, so
the whole pipeline runs and is tested with mocks on any OS — no microphone, no
models, no daemon required.

## Try it now (mocks, any OS)

```sh
pip install -e voice            # from the monorepo root
kow-voice demo                  # full pipeline with scripted mocks
kow-voice demo --barge-in       # simulate the user interrupting mid-answer
```

`demo` prints the HUD event stream: state transitions, the (mock) transcript,
each spoken sentence, and the final answer.

## Real pipeline (Linux desktop)

```sh
pip install -e 'voice[mic]'         # sounddevice + numpy + onnxruntime + helpers
pip install --no-deps openwakeword  # only for wake_word/both modes (see note below)
kow-setup                            # set STT/TTS endpoints + wake activation (writes kowalski.conf)
kow-voice check                     # probe STT, TTS, and the kow-core socket
kow-voice run                       # wake → STT → agent → TTS → playback
kow-voice chat                      # voice + text in one conversation (type OR press Enter to talk)
```

### Voice + text chat

`kow-voice chat` (same as `kow chat --voice`) runs one conversation you can drive
either way: type a message, or press **Enter on an empty line** to talk
(push-to-talk → STT). Every answer is **both printed and spoken** (TTS). Set
`KOW_CHAT_VOICE=1` in `kowalski.conf` to make plain `kow chat` start in this mode.
`--no-speak` falls back to text only. The agent runs in-process through kow-core's
`run_turn`, so typed and spoken turns share the same persisted conversation.

> **openWakeWord on Python 3.12:** the package pins `tflite-runtime`, which has
> no 3.12 wheel, so it can't be installed normally. It also runs on
> **onnxruntime**, so install it with `--no-deps` (onnxruntime comes from the
> `[mic]` extra) and the listener uses the `.onnx` model variants automatically.
> Skip this line if you only use `push_to_talk`.

`run` uses the real adapters: an HTTP STT client (wachawo/speech-to-text,
`POST /api/stt`), an HTTP TTS client (wachawo/text-to-speech, `POST /api/tts`,
inference time from the `X-Elapsed` header), the kow-core unix socket for the
agent, and sounddevice for capture/playback. Tool-call confirmations are
auto-denied over voice (no GUI to approve), so destructive actions are blocked by
design in this mode.

### Wake activation

`KOW_WAKE_MODE` chooses how a turn starts:

| Mode | Trigger |
|---|---|
| `push_to_talk` (default) | press **Enter** — no model, works everywhere |
| `wake_word` | openWakeWord listens for `KOW_WAKE_MODEL` (or `KOW_WAKE_WORD`) |
| `both` | Enter **or** the wake word, whichever comes first |

openWakeWord ships/downloads pretrained names (`hey_jarvis`, `alexa`, …). A
custom phrase such as **"kowalski" needs a trained model file** — train one with
the openWakeWord notebook and point `KOW_WAKE_MODEL` at its `.onnx`/`.tflite`.
Until then, use `both` so push-to-talk always works while you dial in the model.
The RMS energy VAD endpoints utterances; silero-vad is the production upgrade.

## Configuration

`VoiceSettings.load()` resolves, highest priority first: environment variables →
`./ttsgen.conf` → `~/.config/ttsgen.conf` (the native wachawo TTS config chain) →
kow-core's `kowalski.conf` (what `kow-setup` writes — STT/TTS/wake/socket) →
defaults.

| Key | Default | Meaning |
|---|---|---|
| `STT_URL` / `STT_TOKEN` / `STT_LANGUAGE` | `http://127.0.0.1:5099` / — / server default | speech-to-text endpoint |
| `TTS_URL` / `TTS_TOKEN` / `TTS_ENGINE` | `http://127.0.0.1:5000` / — / server default | text-to-speech endpoint |
| `KOW_WAKE_MODE` | `push_to_talk` | `push_to_talk` / `wake_word` / `both` |
| `KOW_WAKE_WORD` | `hey_kowalski` | openWakeWord pretrained model name |
| `KOW_WAKE_MODEL` | — | path to a custom `.onnx`/`.tflite` wake model |
| `KOW_WAKE_THRESHOLD` | `0.5` | detection score required to fire |
| `KOW_VOICE_SAMPLE_RATE` | `16000` | capture sample rate |
| `KOW_VAD_SILENCE_MS` | `700` | trailing silence that ends an utterance |
| `KOW_BARGE_IN` | `1` | allow interrupting the agent mid-answer |

## Architecture

```
kowvoice/
  types.py         Utterance, Transcript, AudioClip, VoiceState, VoiceEvent
  protocols.py     WakeListener, Recorder, Interrupter, SttClient, TtsClient,
                   AudioSink, AgentSession
  segmenter.py     streaming token -> sentence segmentation (TTS by sentences)
  orchestrator.py  VoiceOrchestrator: the pure state machine + barge-in
  settings.py      env / ttsgen.conf chain / kowalski.conf
  mocks.py         scripted implementations of every protocol (demo + tests)
  stt_http.py      HttpSttClient (httpx)
  tts_http.py      HttpTtsClient (httpx)
  agent_socket.py  SocketAgentSession (kow-core unix socket)
  audio_devices.py mic/VAD/wake/playback (sounddevice, [mic] extra)
  cli.py           kow-voice demo | run | check
```
