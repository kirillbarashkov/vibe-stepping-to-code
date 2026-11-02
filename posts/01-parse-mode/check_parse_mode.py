#!/usr/bin/env python3
"""Проверка: разбирает ли Telegram разметку в ваших сообщениях.

    python check_parse_mode.py --chat @my_channel
    TG_TOKEN=123:AA... python check_parse_mode.py --chat 123456789 --keep

Что делает:
  1) отправляет сообщение с HTML-разметкой (жирный, курсив, код, блок кода, ссылка,
     спойлер) и смотрит, какие сущности вернул Telegram;
  2) шлёт заведомо сломанный тег — если Telegram его принял, значит parse_mode
     не применяется вовсе;
  3) удаляет за собой отправленное.

Зависимостей нет: только стандартная библиотека. Токен — из TG_TOKEN или --token.
Прокси — из TG_PROXY (или HTTPS_PROXY), если он нужен в вашей сети.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"

HTML_SAMPLE = (
    "<b>жирный</b> и <i>курсив</i>, <u>подчёркнутый</u>, <s>зачёркнутый</s>, "
    "<code>inline-код</code>, <span class=\"tg-spoiler\">спойлер</span>\n"
    "<a href=\"https://example.com\">ссылка</a>\n"
    "<pre><code class=\"language-python\">print('блок кода')</code></pre>\n"
    "<blockquote>цитата</blockquote>"
)
BROKEN_SAMPLE = "<b>незакрытый тег"


class TgError(RuntimeError):
    pass


class Api:
    def __init__(self, token: str, proxy: str | None = None):
        self.token = token
        handlers = urllib.request.ProxyHandler({"https": proxy, "http": proxy} if proxy else {})
        self.opener = urllib.request.build_opener(handlers)

    def call(self, method: str, params: dict) -> dict:
        request = urllib.request.Request(
            API.format(token=self.token, method=method),
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=45) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode())
        except Exception as exc:  # сеть
            raise TgError(f"{method}: нет связи ({type(exc).__name__}: {exc})") from exc
        if not payload.get("ok"):
            raise TgError(f"{method}: {payload.get('error_code')} {payload.get('description')}")
        return payload["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка разметки Telegram")
    parser.add_argument("--chat", required=True, help="@канал или chat_id")
    parser.add_argument("--token", default=os.environ.get("TG_TOKEN", ""), help="токен бота")
    parser.add_argument("--proxy", default=os.environ.get("TG_PROXY") or os.environ.get("HTTPS_PROXY") or "")
    parser.add_argument("--keep", action="store_true", help="не удалять тестовое сообщение")
    args = parser.parse_args()

    if not args.token:
        print("нужен токен: --token или переменная TG_TOKEN", file=sys.stderr)
        return 2

    api = Api(args.token.strip(), args.proxy or None)
    failures = 0
    sent_id = None

    try:
        me = api.call("getMe", {})
        print(f"бот: @{me['username']} ({me['id']})")
    except TgError as exc:
        print(f"FAIL  getMe — {exc}")
        return 2

    try:
        message = api.call("sendMessage", {
            "chat_id": args.chat,
            "text": HTML_SAMPLE,
            "parse_mode": "HTML",
            "disable_notification": True,
        })
        sent_id = message["message_id"]
        entities = message.get("entities") or []
        kinds = [e["type"] + (f"/{e['language']}" if e.get("language") else "") for e in entities]
        print(f"PASS  сообщение отправлено: message_id={message['message_id']}")
        print(f"      сущностей: {len(entities)} → {', '.join(kinds) if kinds else 'НЕТ'}")
        if not entities:
            print("FAIL  разметка не разобрана: пришло как обычный текст")
            failures += 1
        else:
            lengths = {e["type"]: e["length"] for e in entities}
            if "bold" in lengths and lengths["bold"] != len("жирный"):
                print("WARN  длина сущности не совпала с длиной текста — проверьте offset/length")
    except TgError as exc:
        print(f"FAIL  отправка — {exc}")
        failures += 1

    try:
        api.call("sendMessage", {"chat_id": args.chat, "text": BROKEN_SAMPLE,
                                 "parse_mode": "HTML", "disable_notification": True})
        print("FAIL  сломанный тег принят: parse_mode не применяется вовсе")
        failures += 1
    except TgError as exc:
        text = str(exc).lower()
        if "parse" in text or "tag" in text or "entity" in text:
            print(f"PASS  сломанный тег отвергнут ({exc})")
        else:
            print(f"WARN  неожиданная ошибка на сломанном теге: {exc}")

    if sent_id and not args.keep:
        try:
            api.call("deleteMessage", {"chat_id": args.chat, "message_id": sent_id})
            print("      тестовое сообщение удалено")
        except TgError as exc:
            print(f"WARN  не удалось удалить сообщение {sent_id}: {exc}")

    print("\nИТОГ:", "разметка работает" if failures == 0 else "есть проблемы (см. FAIL)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
