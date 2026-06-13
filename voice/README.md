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
pip install -e 'voice[mic]'     # sounddevice + numpy + openwakeword
kow-voice check                 # probe STT, TTS, and the kow-core socket
kow-voice run                   # push-to-talk → STT → agent → TTS → playback
```

`run` uses the real adapters: an HTTP STT client (wachawo/speech-to-text,
`POST /api/stt`), an HTTP TTS client (wachawo/text-to-speech, `POST /api/tts`,
inference time from the `X-Elapsed` header), the kow-core unix socket for the
agent, and sounddevice for capture/playback. Tool-call confirmations are
auto-denied over voice (no GUI to approve), so destructive actions are blocked by
design in this mode.

The shipped wake/VAD adapters are deliberately simple — **push-to-talk** (press
Enter) and an **RMS energy VAD** — so `run` works on a stock Linux box today.
openWakeWord and silero-vad are the production upgrades (see `audio_devices.py`),
and the Super+Space / always-listening wake arrives with the XFCE integration.

## Configuration

`VoiceSettings.load()` resolves, highest priority first: environment variables →
`./ttsgen.conf` → `~/.config/ttsgen.conf` (the native wachawo TTS config chain) →
kow-core's `kowalski.conf` (for the socket path) → defaults.

| Key | Default | Meaning |
|---|---|---|
| `STT_URL` / `STT_TOKEN` / `STT_LANGUAGE` | `http://127.0.0.1:5099` / — / server default | speech-to-text endpoint |
| `TTS_URL` / `TTS_TOKEN` / `TTS_ENGINE` | `http://127.0.0.1:5000` / — / server default | text-to-speech endpoint |
| `KOW_WAKE_WORD` | `hey_kowalski` | openWakeWord model name |
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
