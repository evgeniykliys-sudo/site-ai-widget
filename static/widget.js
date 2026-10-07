/* AI-ассистент на сайт. Подключение — одна строка перед </body>:
 *   <script src="https://ВАШ-СЕРВЕР/widget.js" data-title="Кирпичик" data-color="#E8590C" async></script>
 * Стили живут в Shadow DOM: CSS сайта не ломает виджет, а виджет не ломает сайт.
 */
(function () {
  if (window.__aiWidget) return;
  window.__aiWidget = true;

  const script = document.currentScript || document.querySelector('script[src*="widget.js"]');
  const API = new URL(script.src).origin;
  const cfg = {
    title: script.dataset.title || "Онлайн-консультант",
    subtitle: script.dataset.subtitle || "Отвечает сразу, по делу",
    color: script.dataset.color || "#2563EB",
    greeting: script.dataset.greeting || "Здравствуйте! Подскажу по ценам, срокам и условиям. Что вас интересует?",
    hints: (script.dataset.hints || "Сколько стоит ремонт санузла?|Какая гарантия?|Хочу бесплатный замер").split("|"),
  };
  const KEY = "aiw-history";
  const store = {
    get() { try { return JSON.parse(sessionStorage.getItem(KEY)) || []; } catch (e) { return []; } },
    set(v) { try { sessionStorage.setItem(KEY, JSON.stringify(v.slice(-20))); } catch (e) {} },
  };
  let history = store.get();
  let busy = false;

  const host = document.createElement("div");
  host.style.cssText = "position:fixed;z-index:2147483000;right:0;bottom:0;";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
<style>
  :host { all: initial; }
  * { box-sizing: border-box; font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
  .fab { position: fixed; right: 20px; bottom: 20px; width: 60px; height: 60px; border-radius: 50%; border: 0;
    background: ${cfg.color}; color: #fff; cursor: pointer; box-shadow: 0 8px 24px rgba(0,0,0,.25);
    display: grid; place-items: center; transition: transform .15s; }
  .fab:hover { transform: scale(1.06); }
  .fab:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 3px solid ${cfg.color}66; outline-offset: 2px; }
  .panel { position: fixed; right: 20px; bottom: 92px; width: 370px; height: min(580px, calc(100vh - 120px));
    background: #fff; color: #1F2937; border-radius: 18px; box-shadow: 0 16px 48px rgba(0,0,0,.22);
    display: none; flex-direction: column; overflow: hidden; }
  .panel.open { display: flex; }
  .head { background: ${cfg.color}; color: #fff; padding: 14px 16px; display: flex; align-items: center; gap: 10px; }
  .head b { display: block; font-size: 15px; } .head small { opacity: .85; font-size: 12px; }
  .head .x { margin-left: auto; background: transparent; border: 0; color: #fff; font-size: 24px; cursor: pointer; line-height: 1; padding: 4px 8px; }
  .log { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 8px; background: #F7F7F8; }
  .m { max-width: 85%; padding: 9px 12px; border-radius: 14px; font-size: 14px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }
  .m.bot { background: #fff; border: 1px solid #E5E7EB; align-self: flex-start; border-bottom-left-radius: 4px; }
  .m.user { background: ${cfg.color}; color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
  .m.err { background: #FEF2F2; border-color: #FECACA; }
  .typing::after { content: "●●●"; letter-spacing: 2px; animation: blink 1s infinite; color: #9CA3AF; }
  @keyframes blink { 50% { opacity: .3; } }
  .hints { display: flex; flex-wrap: wrap; gap: 6px; }
  .hints button { border: 1px solid ${cfg.color}55; color: ${cfg.color}; background: #fff; border-radius: 14px; padding: 6px 10px; font-size: 13px; cursor: pointer; }
  .form { background: #fff; border: 1px solid #E5E7EB; border-radius: 14px; padding: 12px; display: flex; flex-direction: column; gap: 8px; align-self: stretch; }
  .form b { font-size: 14px; }
  .form input, .form textarea { border: 1px solid #D1D5DB; border-radius: 10px; padding: 9px 10px; font-size: 14px; width: 100%; color: #1F2937; background: #fff; }
  .form .trap { position: absolute; left: -9999px; }
  .form button { background: ${cfg.color}; color: #fff; border: 0; border-radius: 10px; padding: 10px; font-size: 14px; font-weight: 600; cursor: pointer; }
  .form .note { font-size: 11px; color: #6B7280; } .form .bad { color: #B91C1C; font-size: 12px; }
  .inp { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #E5E7EB; background: #fff; }
  .inp textarea { flex: 1; resize: none; border: 1px solid #D1D5DB; border-radius: 12px; padding: 9px 10px; font-size: 14px; height: 40px; max-height: 100px; color: #1F2937; background: #fff; }
  .inp button { width: 40px; height: 40px; border-radius: 12px; border: 0; background: ${cfg.color}; color: #fff; cursor: pointer; display: grid; place-items: center; }
  .inp button:disabled { opacity: .5; cursor: default; }
  .foot { text-align: center; font-size: 11px; color: #9CA3AF; padding: 0 0 8px; background: #fff; }
  @media (max-width: 480px) {
    .panel { right: 0; bottom: 0; width: 100vw; height: 100dvh; border-radius: 0; }
    .panel.open ~ .fab { display: none; }
  }
</style>
<div class="panel" role="dialog" aria-label="${cfg.title}">
  <div class="head">
    <div><b>${cfg.title}</b><small>${cfg.subtitle}</small></div>
    <button class="x" aria-label="Закрыть чат">×</button>
  </div>
  <div class="log" aria-live="polite"></div>
  <div class="inp">
    <textarea rows="1" placeholder="Напишите вопрос…" aria-label="Ваш вопрос" maxlength="600"></textarea>
    <button class="send" aria-label="Отправить"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7z"/></svg></button>
  </div>
  <div class="foot">ИИ-ассистент · отвечает по информации компании</div>
</div>
<button class="fab" aria-label="Открыть чат с консультантом">
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
</button>`;

  const $ = (s) => root.querySelector(s);
  const panel = $(".panel"), log = $(".log"), input = $(".inp textarea"), send = $(".send");

  function bubble(cls, text) {
    const d = document.createElement("div");
    d.className = "m " + cls;
    d.textContent = text;           // textContent, не innerHTML: ответ модели не может внедрить разметку на сайт
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  function render() {
    log.innerHTML = "";
    bubble("bot", cfg.greeting);
    history.forEach((m) => bubble(m.role === "user" ? "user" : "bot", m.content));
    if (!history.length) {
      const h = document.createElement("div");
      h.className = "hints";
      cfg.hints.forEach((t) => {
        const b = document.createElement("button");
        b.textContent = t;
        b.onclick = () => { h.remove(); ask(t); };
        h.appendChild(b);
      });
      log.appendChild(h);
    }
  }

  function showForm() {
    const open = log.querySelector(".form:not(.done)");
    if (open) { log.appendChild(open); log.scrollTop = log.scrollHeight; return; }   // уже есть — переносим вниз, к последнему ответу
    const f = document.createElement("form");
    f.className = "form";
    f.innerHTML = `<b>Оставьте контакт — менеджер перезвонит</b>
      <input name="name" placeholder="Имя" required maxlength="60" autocomplete="name">
      <input name="phone" placeholder="Телефон" required maxlength="30" inputmode="tel" autocomplete="tel">
      <input name="website" class="trap" tabindex="-1" autocomplete="off" aria-hidden="true">
      <div class="bad" hidden></div>
      <button type="submit">Жду звонка</button>
      <div class="note">Нажимая кнопку, вы соглашаетесь на обработку персональных данных.</div>`;
    f.onsubmit = async (e) => {
      e.preventDefault();
      const btn = f.querySelector("button"), bad = f.querySelector(".bad");
      btn.disabled = true; bad.hidden = true;
      const lastQ = [...history].reverse().find((m) => m.role === "user");
      try {
        const r = await fetch(API + "/api/lead", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: f.elements.name.value, phone: f.elements.phone.value, website: f.elements.website.value,
                                 need: lastQ ? lastQ.content : "", history, page: location.href.slice(0, 300) }),
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.ok) {
          f.classList.add("done");
          f.innerHTML = "<b>✅ Заявка принята</b><div class='note'>Менеджер перезвонит в рабочее время, в течение 2 часов.</div>";
        } else {
          bad.textContent = j.error || j.detail || "Не получилось отправить, попробуйте ещё раз.";
          bad.hidden = false; btn.disabled = false;
        }
      } catch (err) {
        bad.textContent = "Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.";
        bad.hidden = false; btn.disabled = false;
      }
    };
    log.appendChild(f);
    log.scrollTop = log.scrollHeight;
    f.elements.name.focus();
  }

  async function ask(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; send.disabled = true;
    const hints = log.querySelector(".hints"); if (hints) hints.remove();
    bubble("user", text);
    const prev = history.slice();
    history.push({ role: "user", content: text });
    store.set(history);
    const out = bubble("bot typing", "");
    let answer = "", form = false;
    try {
      const r = await fetch(API + "/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: prev }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || "Сервис временно недоступен.");
      }
      // ответ идёт по кусочкам (Server-Sent Events) — печатаем по мере получения
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, i); buf = buf.slice(i + 2);
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.t === "delta") {
            answer += ev.text;
            out.classList.remove("typing");
            out.textContent = answer.trimEnd();
            log.scrollTop = log.scrollHeight;
          } else if (ev.t === "form") form = true;
        }
      }
      answer = answer.trim();
      if (!answer) throw new Error("Пустой ответ.");
      history.push({ role: "assistant", content: answer });
      store.set(history);
    } catch (e) {
      out.classList.remove("typing");
      out.classList.add("err");
      out.textContent = (e.message || "Ошибка связи.") + " Можно оставить контакт — менеджер ответит.";
      history.pop(); store.set(history);
      form = true;
    }
    if (form) showForm();
    busy = false; send.disabled = false;
    input.focus();
  }

  function toggle(open) {
    panel.classList.toggle("open", open);
    $(".fab").setAttribute("aria-expanded", String(open));
    if (open) { if (!log.children.length) render(); input.focus(); }
  }
  $(".fab").onclick = () => toggle(!panel.classList.contains("open"));
  $(".x").onclick = () => toggle(false);
  root.addEventListener("keydown", (e) => { if (e.key === "Escape") toggle(false); });
  send.onclick = () => { const t = input.value; input.value = ""; ask(t); };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send.click(); }
  });
})();
