import httpx

from app import updates
from app.updates import parse_version, update_status


class Resp:
    def __init__(self, tags, status=200):
        self._tags, self.status_code = tags, status

    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPError("rate limited")

    def json(self):
        return [{"name": t} for t in self._tags]


def fresh(monkeypatch):
    monkeypatch.setattr(updates, "_cache", {"at": 0.0, "latest": None})


def test_parse_version():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.10.0") == (1, 10, 0)
    assert parse_version("v2.0.0-beta") is None and parse_version("latest") is None


def test_reports_newer_release(monkeypatch):
    fresh(monkeypatch)
    status = update_status("1.0.0", fetch=lambda *a, **k: Resp(["v0.1.0", "v1.10.0", "v1.2.0", "nightly"]))
    assert status["latest"] == "1.10.0" and status["update_available"] is True
    assert status["url"].endswith("/releases")


def test_up_to_date_and_cached(monkeypatch):
    fresh(monkeypatch)
    calls = []
    fetch = lambda *a, **k: calls.append(1) or Resp(["v1.0.0"])
    assert update_status("1.0.0", fetch=fetch)["update_available"] is False
    update_status("1.0.0", fetch=fetch)
    assert len(calls) == 1


def test_offline_never_breaks(monkeypatch):
    fresh(monkeypatch)
    def offline(*a, **k):
        raise httpx.ConnectError("no network")
    assert update_status("1.0.0", fetch=offline) == {
        "current": "1.0.0", "latest": None, "update_available": False, "url": updates.RELEASES_PAGE}
