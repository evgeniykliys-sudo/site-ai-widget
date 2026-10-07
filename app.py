"""Сервер виджета: /widget.js (вставляется на сайт), /api/chat (ответ стримом), /api/lead (заявка), / (демо-страница).

    uvicorn app:app --port 8010
"""
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import assistant  # noqa: E402
import kb  # noqa: E402
import leads  # noqa: E402

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("widget")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Сайты, которым можно встраивать виджет (через запятую). Чужой сайт не сможет тратить ваш бюджет на нейросеть.
ORIGINS = [o.strip() for o in (os.getenv("ALLOWED_ORIGINS") or "http://localhost:8010,http://127.0.0.1:8010").split(",") if o.strip()]
PER_IP = int(os.getenv("LIMIT_PER_IP") or 20)          # сообщений с одного адреса за 10 минут
PER_DAY = int(os.getenv("LIMIT_PER_DAY") or 500)       # сообщений всего за сутки — потолок расходов на API
LEADS_PER_IP = 3                                       # заявок с одного адреса за 10 минут — от спама формой

app = FastAPI(title="site-ai-widget")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["POST", "GET"], allow_headers=["Content-Type"])


@app.exception_handler(RequestValidationError)
async def validation_error(req: Request, exc: RequestValidationError):
    # стандартный ответ FastAPI — список технических ошибок; виджету нужна одна понятная фраза
    msg = "Проверьте имя и телефон." if req.url.path == "/api/lead" else "Сообщение пустое или слишком длинное (до 600 символов)."
    return JSONResponse({"ok": False, "error": msg, "detail": msg}, 422)


class Limiter:
    """Скользящее окно в памяти. Для одного сервера достаточно; для нескольких — Redis."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float) -> bool:
        q, now = self.hits[key], time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


limiter = Limiter()


def client_ip(req: Request) -> str:
    # за nginx настоящий адрес — в X-Real-IP (proxy_set_header X-Real-IP $remote_addr)
    return req.headers.get("x-real-ip") or (req.client.host if req.client else "?")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=assistant.MAX_MSG_LEN)
    history: list[dict] = Field(default_factory=list, max_length=40)


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    phone: str = Field(max_length=30)   # формат проверяем сами — с понятным текстом ошибки
    need: str = Field(default="", max_length=500)
    history: list[dict] = Field(default_factory=list, max_length=40)
    page: str = Field(default="", max_length=300)
    website: str = Field(default="", max_length=100)   # ловушка для ботов: поле скрыто, человек его не заполнит


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(body: ChatIn, req: Request):
    ip = client_ip(req)
    if not limiter.allow(f"ip:{ip}", PER_IP, 600):
        raise HTTPException(429, "Слишком много сообщений. Оставьте заявку — менеджер ответит сам.")
    if not limiter.allow("day", PER_DAY, 86400):
        log.warning("дневной лимит сообщений исчерпан")
        raise HTTPException(429, "Ассистент сейчас недоступен. Оставьте заявку — менеджер перезвонит.")

    async def gen():
        try:
            async for ev in assistant.stream_answer(body.message, body.history):
                yield sse(ev)
        except Exception:
            log.exception("ошибка ответа ассистента")
            # посетитель не должен видеть трассировку: даём выход — форму заявки
            yield sse({"t": "delta", "text": "Не получилось ответить — похоже, временный сбой. Оставьте контакт, менеджер ответит сам."})
            yield sse({"t": "form"})
            yield sse({"t": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/lead")
async def lead(body: LeadIn, req: Request):
    if body.website:                       # бот заполнил скрытое поле — делаем вид, что всё хорошо
        return {"ok": True}
    phone = leads.normalize_phone(body.phone)
    if not phone:
        return JSONResponse({"ok": False, "error": "Проверьте номер телефона: например, +7 913 123-45-67"}, 422)
    # лимит считаем после проверки: опечатки в номере не должны «съедать» попытки живому человеку
    if not limiter.allow(f"lead:{client_ip(req)}", LEADS_PER_IP, 600):
        raise HTTPException(429, "Заявка уже отправлена — менеджер скоро свяжется.")
    dialog = "\n".join(f"{'Клиент' if m.get('role') == 'user' else 'Бот'}: {str(m.get('content', ''))[:300]}"
                       for m in body.history[-6:] if m.get("role") in ("user", "assistant"))
    name = body.name.strip()
    lead_id = leads.save(name, phone, body.need.strip(), dialog, body.page)
    sent = await leads.notify(lead_id, name, phone, body.need.strip(), dialog, body.page)
    log.info("заявка %s сохранена, уведомление: %s", lead_id, sent)
    return {"ok": True, "id": lead_id}


@app.get("/widget.js")
async def widget_js():
    return FileResponse(STATIC / "widget.js", media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"})


@app.get("/")
async def demo():
    return FileResponse(STATIC / "demo.html")


@app.get("/health")
async def health():
    return {"ok": True, "kb_keys": kb.collection().count()}   # ключей поиска (предложений), не разделов


@app.on_event("startup")
async def warmup():
    kb.collection()
    kb.model()   # первая загрузка модели эмбеддингов ~5 с — пусть будет при старте, а не на первом вопросе
