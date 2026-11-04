"""Saved chats and runs through the store, and what the page sends instead of what ffmpeg made."""

import wave

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fall_zero import server, store, voice


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCAL", tmp_path)
    return tmp_path


def test_saved_chats_round_trip_newest_first(local):
    client = TestClient(server.app)
    for tid, title in (("aaaaaaaaaaaa", "Dresser"), ("bbbbbbbbbbbb", "Bookcase")):
        assert client.put(f"/api/threads/{tid}", json={"title": title, "messages": []}).status_code == 200
    assert [t["title"] for t in client.get("/api/threads").json()] == ["Bookcase", "Dresser"]
    assert client.get("/api/threads/aaaaaaaaaaaa").json()["title"] == "Dresser"
    client.delete("/api/threads/aaaaaaaaaaaa")
    assert [t["id"] for t in client.get("/api/threads").json()] == ["bbbbbbbbbbbb"]
    assert client.get("/api/threads/../../.env").status_code == 404


def test_a_runs_files_are_served_and_nothing_else(local):
    (local / "web" / "0123456789ab").mkdir(parents=True)
    (local / "web" / "0123456789ab" / "still.jpg").write_bytes(b"jpeg")
    client = TestClient(server.app)
    assert client.get("/files/0123456789ab/still.jpg").content == b"jpeg"
    assert client.get("/files/0123456789ab/report.json").status_code == 404
    assert client.get("/files/0123456789ab/..%2F..%2F.env").status_code == 404


def test_deployed_each_browser_lists_only_its_own_chats(monkeypatch):
    monkeypatch.setattr(store, "REMOTE", True)
    owner = "0123456789abcdef0123456789abcdef"
    assert server._thread_name("aaaaaaaaaaaa", owner) == f"threads/{owner}/aaaaaaaaaaaa.json"
    with pytest.raises(HTTPException):
        server._folder("")  # no id, no chats: never the shared folder


def test_the_pages_recording_goes_to_the_transcriber_as_it_is(tmp_path):
    path = tmp_path / "voice.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(voice.RATE)
        w.writeframes(b"\0\0" * 2400)
    assert voice.to_wav(path) == path
