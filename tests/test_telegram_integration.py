"""Integration test — Telegram collector with real-ish HTML (mocked network)."""
import pytest
from unittest.mock import patch, MagicMock
from collectors.telegram import TelegramCollector


# Real-world-like HTML from t.me/s/ (simplified but structurally accurate)
REALISTIC_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Telegram</title></head>
<body>
<div class="tgme_channel_history">
  <div class="tgme_widget_message_wrap">
    <div class="tgme_widget_message">
      <div class="tgme_widget_message_header">
        <a class="tgme_widget_message_author" href="/s/passiveincome">
          <span>Passive Income Ideas</span>
        </a>
      </div>
      <div class="tgme_widget_message_text">5 ways to earn $1000/month passively:<br>1. Print on demand<br>2. Digital products<br>3. Affiliate marketing<br>4. Course creation<br>5. Dividend investing</div>
      <div class="tgme_widget_message_footer">
        <a class="tgme_widget_message_date" href="/passiveincome/123" data-post="passiveincome/123">
          <time datetime="2026-06-24T10:30:00+00:00">10:30</time>
        </a>
      </div>
    </div>
  </div>
  <div class="tgme_widget_message_wrap">
    <div class="tgme_widget_message">
      <div class="tgme_widget_message_header">
        <a class="tgme_widget_message_author" href="/s/passiveincome">
          <span>Passive Income Ideas</span>
        </a>
      </div>
      <div class="tgme_widget_message_text">Just launched my SaaS tool for automating social media posts. MRR already at $500 after 2 weeks!</div>
      <div class="tgme_widget_message_footer">
        <a class="tgme_widget_message_date" href="/passiveincome/124" data-post="passiveincome/124">
          <time datetime="2026-06-24T11:00:00+00:00">11:00</time>
        </a>
      </div>
    </div>
  </div>
  <div class="tgme_widget_message_wrap">
    <div class="tgme_widget_message">
      <div class="tgme_widget_message_header">
        <a class="tgme_widget_message_author" href="/s/passiveincome">
          <span>Passive Income Ideas</span>
        </a>
      </div>
      <div class="tgme_widget_message_text">Crypto staking yields are insane right now. ETH 4.5%, SOL 7.2%, ATOM 15%+. Not financial advice.</div>
      <div class="tgme_widget_message_footer">
        <a class="tgme_widget_message_date" href="/passiveincome/125" data-post="passiveincome/125">
          <time datetime="2026-06-24T12:00:00+00:00">12:00</time>
        </a>
      </div>
    </div>
  </div>
</div>
</body>
</html>
'''


@pytest.fixture
def mock_httpx():
    with patch("collectors.telegram.httpx.Client") as client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = REALISTIC_HTML
        mock_response.raise_for_status = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        client_cls.return_value = mock_client
        yield mock_client


def test_fetches_all_messages(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    assert len(items) == 3


def test_extracts_body_text(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    texts = [item.body_text for item in items]
    assert any("SaaS" in (t or "") for t in texts)
    assert any("staking" in (t or "").lower() for t in texts)
    assert any("passive" in (t or "").lower() for t in texts)


def test_source_ids_are_unique(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    ids = [item.source_item_id for item in items]
    assert len(ids) == len(set(ids))


def test_source_id_format(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    for item in items:
        assert item.source_item_id.startswith("telegram:passiveincome:")
        parts = item.source_item_id.split(":")
        assert len(parts) == 3


def test_published_dates_parsed(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    for item in items:
        assert item.published_at is not None
        assert "2026-06-24" in item.published_at


def test_author_extracted(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    for item in items:
        assert item.author is not None


def test_message_links_extracted(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    urls = [item.url for item in items if item.url]
    assert len(urls) > 0
    for url in urls:
        assert url.startswith("https://t.me/passiveincome/")


def test_max_items_respected(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"], "max_messages_per_channel": 2})
    items = coll.fetch()
    assert len(items) == 2


def test_multiple_channels(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome", "saas"]})
    items = coll.fetch()
    channels = {item.source_item_id.split(":")[1] for item in items}
    assert "passiveincome" in channels
    assert "saas" in channels


def test_body_text_strips_html(mock_httpx):
    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()
    for item in items:
        assert "<" not in (item.body_text or "")
        assert ">" not in (item.body_text or "")


def test_body_truncated_to_500(mock_httpx):
    long_html = REALISTIC_HTML.replace(
        "5 ways to earn",
        "A" * 600
    )
    with patch("collectors.telegram.httpx.Client") as client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = long_html
        mock_response.raise_for_status = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        client_cls.return_value = mock_client

        coll = TelegramCollector({"channels": ["passiveincome"]})
        items = coll.fetch()
        for item in items:
            assert len(item.body_text or "") <= 500


def test_handles_empty_channel_list():
    coll = TelegramCollector({"channels": []})
    items = coll.fetch()
    assert items == []


def test_handles_nonexistent_channel():
    with patch("collectors.telegram.httpx.Client") as client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "<html><body>Sorry, this channel doesn't exist</body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        client_cls.return_value = mock_client

        coll = TelegramCollector({"channels": ["nonexistent_channel_xyz"]})
        items = coll.fetch()
        assert items == []
