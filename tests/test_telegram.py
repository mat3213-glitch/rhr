"""Tests for Telegram collector (t.me/s/ HTML parsing)."""
import pytest
from unittest.mock import patch, MagicMock
from collectors.telegram import TelegramCollector


SAMPLE_HTML = '''
<html>
<body>
<div class="tgme_widget_message_wrap">
  <div class="tgme_channel_history">
    <div class="tgme_widget_message_wrap">
      <a class="tgme_widget_message_author" href="/s/passiveincome">
        <span>Passive Income</span>
      </a>
      <div class="tgme_widget_message_text">Great way to earn money: <a href="https://example.com">link</a></div>
      <time datetime="2026-06-24T10:00:00+00:00"></time>
      <a class="tgme_widget_message_date" href="/passiveincome/123">
        <time datetime="2026-06-24T10:00:00+00:00"></time>
      </a>
    </div>
    <div class="tgme_widget_message_wrap">
      <a class="tgme_widget_message_author" href="/s/passiveincome">
        <span>Passive Income</span>
      </a>
      <div class="tgme_widget_message_text">Another tip: build SaaS products</div>
      <time datetime="2026-06-24T11:00:00+00:00"></time>
      <a class="tgme_widget_message_date" href="/passiveincome/124">
        <time datetime="2026-06-24T11:00:00+00:00"></time>
      </a>
    </div>
  </div>
</div>
</body>
</html>
'''


def test_telegram_collector_type():
    coll = TelegramCollector({})
    assert coll.type == "telegram"


def test_telegram_fetch_empty_channels():
    coll = TelegramCollector({"channels": []})
    items = coll.fetch()
    assert items == []


@patch("collectors.telegram.httpx.Client")
def test_telegram_fetch_single_channel(mock_client):
    mock_response = MagicMock()
    mock_response.text = SAMPLE_HTML
    mock_response.raise_for_status = MagicMock()
    mock_client.return_value.__enter__ = MagicMock(return_value=mock_client.return_value)
    mock_client.return_value.__exit__ = MagicMock(return_value=False)
    mock_client.return_value.get.return_value = mock_response

    coll = TelegramCollector({"channels": ["passiveincome"]})
    items = coll.fetch()

    assert len(items) >= 1
    for item in items:
        assert item.source == "telegram"
        assert item.source_item_id.startswith("telegram:passiveincome:")


@patch("collectors.telegram.httpx.Client")
def test_telegram_fetch_multiple_channels(mock_client):
    mock_response = MagicMock()
    mock_response.text = SAMPLE_HTML
    mock_response.raise_for_status = MagicMock()
    mock_client.return_value.__enter__ = MagicMock(return_value=mock_client.return_value)
    mock_client.return_value.__exit__ = MagicMock(return_value=False)
    mock_client.return_value.get.return_value = mock_response

    coll = TelegramCollector({
        "channels": ["passiveincome", "saas", "defi"]
    })
    items = coll.fetch()

    assert len(items) >= 3
    sources = {item.source_item_id.split(":")[1] for item in items}
    assert "passiveincome" in sources
    assert "saas" in sources
    assert "defi" in sources


@patch("collectors.telegram.httpx.Client")
def test_telegram_max_messages_per_channel(mock_client):
    mock_response = MagicMock()
    mock_response.text = SAMPLE_HTML
    mock_response.raise_for_status = MagicMock()
    mock_client.return_value.__enter__ = MagicMock(return_value=mock_client.return_value)
    mock_client.return_value.__exit__ = MagicMock(return_value=False)
    mock_client.return_value.get.return_value = mock_response

    coll = TelegramCollector({
        "channels": ["passiveincome"],
        "max_messages_per_channel": 1
    })
    items = coll.fetch()

    assert len(items) <= 1


@patch("collectors.telegram.httpx.Client")
def test_telegram_handles_network_error(mock_client):
    mock_client.return_value.__enter__ = MagicMock(return_value=mock_client.return_value)
    mock_client.return_value.__exit__ = MagicMock(return_value=False)
    mock_client.return_value.get.side_effect = Exception("Connection failed")

    coll = TelegramCollector({"channels": ["nonexistent"]})
    items = coll.fetch()

    assert items == []


def test_telegram_strips_at_sign():
    coll = TelegramCollector({"channels": ["@passiveincome"]})
    items = []
    with patch("collectors.telegram.httpx.Client") as mock_client:
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML
        mock_response.raise_for_status = MagicMock()
        mock_client.return_value.__enter__ = MagicMock(return_value=mock_client.return_value)
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get.return_value = mock_response
        items = coll.fetch()

    for item in items:
        assert "passiveincome" in item.source_item_id
        assert "@passiveincome" not in item.source_item_id


def test_telegram_parse_empty_html():
    coll = TelegramCollector({})
    items = coll._parse_messages("<html></html>", "test", 10)
    assert items == []


def test_telegram_parse_no_messages():
    coll = TelegramCollector({})
    html = '<html><body><div class="tgme_widget_message_wrap"></div></body></html>'
    items = coll._parse_messages(html, "test", 10)
    assert isinstance(items, list)
