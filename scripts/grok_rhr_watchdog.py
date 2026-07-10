"""
Grok RHR Watchdog: проверяет наличие signals/incoming/grok_<YYYY-MM-DD>.json (UTC-дата).
Если файла нет — шлёт пинок в Telegram.
Дедлайн Grok: 18:00 НСК (=11:00 UTC); крон стража 13:00 UTC (буфер ~2ч).
"""
import os
from datetime import datetime, timezone
import requests

DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
GROK_FILE = os.path.join("signals", "incoming", f"grok_{DATE}.json")


def send_tg(text: str) -> None:
    worker = os.environ.get("CLOUDFLARE_WORKER")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("SCOUT_CHAT_ID")
    if not (worker and token and chat):
        print("[tg] нет секретов — пропускаю")
        return
    try:
        requests.post(
            f"{worker.rstrip('/')}/bot{token}/sendMessage",
            json={"chat_id": chat, "message_thread_id": 1653, "text": text[:3800]},
            headers={"User-Agent": "curl/8.5.0"},
            timeout=30,
        )
        print("[tg] пинок отправлен")
    except Exception as e:
        print(f"[tg] ошибка: {e}")


def main() -> None:
    if os.path.isfile(GROK_FILE):
        print(f"[watchdog] grok_{DATE}.json на месте — пинок не нужен")
        return
    print(f"[watchdog] grok_{DATE}.json отсутствует — шлю пинок")
    prompt = (
        f"Проверь GitHub mat3213-glitch/rhr/signals/incoming/. Сегодня {DATE}. "
        f"Если grok_{DATE}.json ещё нет — собери дневные сигналы "
        "(passive income, micro SaaS, AI wrappers, DeFi yield, automation, demand gaps) "
        "из X и веба и закоммить файл через MCP-коннектор."
    )
    text = (
        f"🔴 grok_{DATE}.json за {DATE} не найден в rhr/signals/incoming/!\n\n"
        f"Промпт для вставки в Grok:\n{prompt}\n\n"
        "Ссылка: https://x.com/i/grok"
    )
    send_tg(text)


if __name__ == "__main__":
    main()
