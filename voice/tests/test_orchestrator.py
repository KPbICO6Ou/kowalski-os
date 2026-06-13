from kowvoice.mocks import (
    MockAgentSession,
    MockAudioSink,
    MockInterrupter,
    MockRecorder,
    MockSttClient,
    MockTtsClient,
    MockWakeListener,
    silent_utterance,
)
from kowvoice.orchestrator import VoiceOrchestrator
from kowvoice.types import VoiceState


def build(settings, *, utterances, transcripts, deltas, on_synthesize=None, interrupter=None):
    captured = []
    interrupter = interrupter or MockInterrupter()
    sink = MockAudioSink()
    agent = MockAgentSession(deltas)
    stt = MockSttClient(transcripts)
    tts = MockTtsClient(on_synthesize=on_synthesize)
    orch = VoiceOrchestrator(
        wake=MockWakeListener(fires=1),
        recorder=MockRecorder(utterances),
        stt=stt,
        agent=agent,
        tts=tts,
        sink=sink,
        interrupter=interrupter,
        settings=settings,
        on_event=captured.append,
    )
    return orch, captured, sink, agent, stt, tts, interrupter


def kinds(events, kind):
    return [e for e in events if e.kind == kind]


async def test_happy_path_full_cycle(settings):
    orch, events, sink, agent, stt, tts, _ = build(
        settings,
        utterances=[silent_utterance()],
        transcripts=["what time is it"],
        deltas=["It is ", "noon. ", "Have a ", "good day!"],
    )
    await orch.run_once()

    assert agent.asked == ["what time is it"]
    assert tts.calls == ["It is noon.", "Have a good day!"]
    assert len(sink.played) == 2 and not sink.stopped
    assert kinds(events, "transcript")[0].text == "what time is it"
    assert kinds(events, "answer")[0].text == "It is noon. Have a good day!"
    states = [e.state for e in events if e.kind == "state"]
    assert VoiceState.LISTENING in states
    assert VoiceState.THINKING in states
    assert VoiceState.SPEAKING in states
    assert orch.state == VoiceState.IDLE


async def test_empty_transcript_returns_to_idle(settings):
    orch, events, sink, agent, *_ = build(
        settings, utterances=[silent_utterance()], transcripts=[""], deltas=["x"]
    )
    await orch.run_once()
    assert agent.asked == []
    assert sink.played == []
    assert kinds(events, "no_speech")


async def test_false_wake_no_utterance(settings):
    orch, events, sink, agent, stt, *_ = build(
        settings, utterances=[], transcripts=[], deltas=["x"]
    )
    await orch.run_once()
    assert stt.calls == []
    assert agent.asked == []
    assert kinds(events, "no_speech")


async def test_barge_in_interrupts_and_relistens(settings):
    interrupter = MockInterrupter()
    # trigger barge-in while the SECOND sentence of the first answer is synthesized
    orch, events, sink, agent, stt, tts, _ = build(
        settings,
        utterances=[silent_utterance(), silent_utterance()],
        transcripts=["tell me a long story", "stop, different question"],
        deltas=["First sentence. ", "Second sentence. ", "Third sentence."],
        on_synthesize=lambda _t, n: interrupter.trigger() if n == 2 else None,
        interrupter=interrupter,
    )
    await orch.run_once()

    # both turns were transcribed; the user was heard again after interrupting
    assert agent.asked == ["tell me a long story", "stop, different question"]
    assert len(stt.calls) == 2
    assert sink.stopped is True
    assert len(kinds(events, "barge_in")) == 1
    # first turn played only sentence 1 (sentence 2 was interrupted mid-play)
    assert sink.played  # at least the first sentence of turn 1 played


async def test_barge_in_disabled_skips_monitor(settings):
    settings.barge_in = False
    interrupter = MockInterrupter()
    orch, events, sink, agent, *_ = build(
        settings,
        utterances=[silent_utterance()],
        transcripts=["hello"],
        deltas=["Hi there!"],
        interrupter=interrupter,
    )
    await orch.run_once()
    assert interrupter.waits == 0  # the barge monitor was never armed
    assert len(sink.played) == 1
