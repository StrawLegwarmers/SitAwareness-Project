import pytest

import feeds

EMPTY_RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><link>https://e.com</link>' \
            b'<description>d</description></channel></rss>'
ONE_ITEM = EMPTY_RSS.replace(b"</channel>", b"<item><title>A</title><link>https://e.com/a</link></item></channel>")


def test_a_feed_with_items_is_a_feed():
    assert feeds.parse_feed_bytes(ONE_ITEM).entries


def test_an_empty_feed_is_quiet_not_broken():
    assert feeds.parse_feed_bytes(EMPTY_RSS) is None                  # strict: discovery needs items
    assert feeds.parse_feed_bytes(EMPTY_RSS, allow_empty=True) is not None


def test_a_web_page_is_not_a_feed():
    assert feeds.parse_feed_bytes(b"<html><body>hello</body></html>", allow_empty=True) is None


class FakeResponse:
    def __init__(self, chunks):
        self.chunks, self.status_code, self.headers, self.url = chunks, 200, {}, "https://e.com/feed"

    @property
    def content(self):                 # like requests.Response: the body read so far
        return self._content

    def iter_content(self, size):
        yield from self.chunks

    def close(self):
        pass


def test_huge_responses_are_cut_off(monkeypatch):
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: FakeResponse([b"x" * 1_000_000] * 20))
    with pytest.raises(ValueError, match="larger than"):
        feeds.fetch("https://e.com/feed")


def test_normal_responses_keep_their_content(monkeypatch):
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: FakeResponse([ONE_ITEM[:50], ONE_ITEM[50:]]))
    assert feeds.fetch("https://e.com/feed").content == ONE_ITEM
