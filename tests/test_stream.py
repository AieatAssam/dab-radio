import asyncio
from typing import Any

import app as backend


class FakeResponse:
    status_code = 200

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def aiter_bytes(self, chunk_size: int):
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield chunk
        # Keep the upstream alive until the test closes its subscribers.
        await asyncio.Event().wait()


class FakeStreamContext:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> FakeResponse:
        return self.response

    async def __aexit__(self, *_: Any) -> None:
        return None


class FakeHTTPClient:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.requests: list[tuple[str, str]] = []

    def stream(self, method: str, url: str) -> FakeStreamContext:
        self.requests.append((method, url))
        return FakeStreamContext(FakeResponse(self.chunks))


class CompletedAudioStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.subscriber = backend.StreamSubscriber()
        self.closed = False
        for chunk in chunks:
            self.subscriber.queue.put_nowait(chunk)
        self.subscriber.queue.put_nowait(None)

    async def subscribe(self, sid: str) -> backend.StreamSubscriber:
        self.sid = sid
        return self.subscriber

    async def unsubscribe(self, subscriber: backend.StreamSubscriber) -> None:
        assert subscriber is self.subscriber
        self.closed = True


def test_subscribers_are_hashable_and_receive_the_same_audio_chunks(
    monkeypatch,
) -> None:
    async def exercise() -> None:
        chunks = [b"mp3-frame-one", b"mp3-frame-two"]
        upstream = FakeHTTPClient(chunks)
        monkeypatch.setattr(backend.receiver, "http", upstream, raising=False)
        audio = backend.SharedAudioStream()

        try:
            first = await audio.subscribe("0x1234")
            second = await audio.subscribe("0x1234")

            assert first is not second
            assert set(audio.subscribers) == {first, second}

            first_chunks, second_chunks = await asyncio.wait_for(
                asyncio.gather(
                    asyncio.gather(*(first.queue.get() for _ in chunks)),
                    asyncio.gather(*(second.queue.get() for _ in chunks)),
                ),
                timeout=1.0,
            )

            assert first_chunks == chunks
            assert second_chunks == chunks
            assert upstream.requests == [("GET", f"{backend.RECEIVER_ROOT}/stream/0x1234")]
            assert audio.bytes_streamed == sum(map(len, chunks))
        finally:
            await audio.stop_all()

    asyncio.run(exercise())


def test_mp3_route_forwards_chunks_and_unsubscribes_on_end(monkeypatch) -> None:
    async def exercise() -> None:
        chunks = [b"first-mp3-frame", b"second-mp3-frame"]
        audio = CompletedAudioStream(chunks)
        monkeypatch.setattr(backend.receiver, "status", "healthy")
        monkeypatch.setattr(backend.receiver, "selected", {"channel": "12B", "service": "0x1234"})
        monkeypatch.setattr(
            backend.receiver,
            "cache",
            {"version": 1, "selected": {"channel": "12B", "service": "0x1234"}, "channels": {}},
        )
        monkeypatch.setattr(backend.receiver, "current_channel", None)
        monkeypatch.setattr(backend.receiver, "audio", audio)

        response = await backend.stream_mp3()
        forwarded = [chunk async for chunk in response.body_iterator]

        assert response.status_code == 200
        assert response.media_type == "audio/mpeg"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Accel-Buffering"] == "no"
        assert audio.sid == "0x1234"
        assert forwarded == chunks
        assert audio.closed is True

    asyncio.run(exercise())


def test_slow_subscriber_is_disconnected_without_stalling_fast_subscriber(
    monkeypatch,
) -> None:
    async def exercise() -> None:
        chunks = [f"frame-{index}".encode() for index in range(backend.STREAM_QUEUE_DEPTH + 1)]
        upstream = FakeHTTPClient(chunks)
        monkeypatch.setattr(backend.receiver, "http", upstream, raising=False)
        audio = backend.SharedAudioStream()

        async def read_fast_subscriber(subscriber) -> list[bytes]:
            return [
                await asyncio.wait_for(subscriber.queue.get(), timeout=1.0)
                for _ in chunks
            ]

        try:
            fast = await audio.subscribe("0x1234")
            slow = await audio.subscribe("0x1234")
            fast_chunks = await asyncio.wait_for(read_fast_subscriber(fast), timeout=2.0)

            assert fast_chunks == chunks
            assert fast.closed is False
            assert slow.closed is True
            assert audio.slow_disconnects == 1
            assert audio.subscribers == {fast}

            await audio.unsubscribe(fast)

            assert fast.closed is True
            assert audio.subscribers == set()
            assert audio.upstream_task is None
        finally:
            await audio.stop_all()

    asyncio.run(exercise())
