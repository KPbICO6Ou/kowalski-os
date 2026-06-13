"""Exercise the real httpx STT/TTS clients against a tiny in-process HTTP
server speaking the wachawo contracts (no ML, no network)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kowvoice.stt_http import HttpSttClient
from kowvoice.tts_http import HttpTtsClient
from kowvoice.types import Utterance


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def do_GET(self):
        if self.path == "/api/health":
            self.server.last_auth = self.headers.get("Authorization")
            self._json({"available": 2, "engine": "silerotts"})
        else:
            self.send_error(404)

    def do_POST(self):
        body = self._read_body()
        self.server.last_auth = self.headers.get("Authorization")
        if self.path == "/api/stt":
            self.server.stt_bytes = len(body)
            self._json({"text": "hello world", "language": "en", "elapsed": 0.12})
        elif self.path == "/api/tts":
            payload = json.loads(body)
            self.server.tts_text = payload.get("text")
            audio = b"RIFFfake-wav-bytes"
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("X-Elapsed", "0.34")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
        else:
            self.send_error(404)

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    httpd.last_auth = None
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


def _url(server):
    return f"http://127.0.0.1:{server.server_address[1]}"


async def test_stt_transcribe(server):
    client = HttpSttClient(_url(server), token="secret")
    result = await client.transcribe(Utterance(pcm=b"\x00\x00" * 1600), language="en")
    assert result.text == "hello world"
    assert result.language == "en"
    assert result.elapsed_s == 0.12
    assert server.last_auth == "Bearer secret"
    assert server.stt_bytes > 0  # a WAV body was uploaded


async def test_tts_synthesize_reads_elapsed_header(server):
    client = HttpTtsClient(_url(server), engine="silerotts")
    clip = await client.synthesize("good evening")
    assert clip.audio == b"RIFFfake-wav-bytes"
    assert clip.format == "wav"
    assert clip.elapsed_s == 0.34
    assert server.tts_text == "good evening"


async def test_health(server):
    assert (await HttpSttClient(_url(server)).health())["available"] == 2
    assert (await HttpTtsClient(_url(server)).health())["engine"] == "silerotts"
