"""Прикладной слой: переходы состояний с аудитом и кредитный конвейер (валидация → обогащение → скоринг → решение)."""
import os, threading, time
from . import db as DB, domain as D, integrations as INT

DELAY = float(os.getenv("PIPELINE_STEP_DELAY", "1.0"))   # пауза между этапами, чтобы статус был виден в UI
SYNC = os.getenv("PIPELINE_SYNC", "0") == "1"            # для тестов: конвейер выполняется синхронно

def transition(c, a, to, actor, comment=None, **upd):
    """Единственная точка смены статуса: проверка автомата, запись изменений, версия, запись в журнал."""
    D.check_transition(a["status"], to)
    frm = a["status"]
    a.update(upd); a["status"] = to
    DB.save_app(c, a)
    DB.add_event(c, a["id"], actor, frm, to, comment)

def start_pipeline(app_id):
    if SYNC: run_pipeline(app_id)
    else: threading.Thread(target=run_pipeline, args=(app_id,), daemon=True).start()

def resume_pending():
    """Надёжность: после рестарта продолжаем заявки, застрявшие на автоматических этапах."""
    with DB.db() as c:
        ids = [r[0] for r in c.execute(f"SELECT id FROM applications WHERE status IN ({','.join('?' * len(D.TRANSIENT))})", tuple(D.TRANSIENT))]
    for i in ids: start_pipeline(i)

def run_pipeline(app_id):
    while True:
        try:
            with DB.db() as c:
                a = DB.get_app(c, app_id)
                if not a or a["status"] not in D.TRANSIENT: return
                if DELAY and not SYNC: time.sleep(DELAY)
                _step(c, a)
        except DB.Conflict:
            continue   # заявку изменил другой процесс — перечитываем состояние

def _need_info(c, a, items, src, comment):
    transition(c, a, "INFO_REQUESTED", src, comment, info_request={"source": src, "items": items, "ts": DB.now()},
               decision={"outcome": "INFO_REQUESTED", "by": src, "reasons": items, "ts": DB.now()})

def _step(c, a):
    s = a["status"]
    if s == "SUBMITTED":
        transition(c, a, "VALIDATION", "system", "Проверка полноты и корректности данных")
    elif s == "VALIDATION":
        errs = D.validate(a)
        if errs: _need_info(c, a, [e["message"] for e in errs], "system", "Данные неполны или некорректны")
        else:
            transition(c, a, "ENRICHMENT", "system", "Запросы в ЕГРЮЛ/ЕГРИП, ФНС, БКИ (симуляторы)")
    elif s == "ENRICHMENT":
        chk = INT.enrich(a["company"]["inn"])
        if chk is None:
            _need_info(c, a, [f"ИНН {a['company']['inn']} не найден в ЕГРЮЛ/ЕГРИП. Проверьте ИНН или приложите выписку"], "system", "ИНН не найден в реестре")
        else:
            transition(c, a, "SCORING", "system", "Данные обогащены, расчёт оценки риска", checks=chk)
    elif s == "SCORING":
        sc = D.score(a, a["checks"])
        outcome, reasons, offer = D.decide(a, sc, a["checks"])
        dec = {"outcome": outcome, "by": "auto", "reasons": reasons, "ts": DB.now()}
        to = {"APPROVED": "OFFER_READY", "COUNTER": "OFFER_READY", "MANUAL_REVIEW": "MANUAL_REVIEW", "REJECTED": "REJECTED"}[outcome]
        transition(c, a, to, "system", "; ".join(reasons), scoring=sc, decision=dec, offer=offer, info_request=None)

# ---------- решение андеррайтера (ручное рассмотрение) ----------
def underwriter_decide(c, a, user, action, amount, term, comment):
    if a["status"] != "MANUAL_REVIEW": raise D.DomainError("Заявка не на ручном рассмотрении")
    p, g, who = D.PRODUCTS[a["product"]], a["scoring"]["grade"], user["login"]
    if action in ("reject", "request_info") and not (comment or "").strip():
        raise D.DomainError("Комментарий обязателен", 422)
    if action == "reject":
        transition(c, a, "REJECTED", who, comment, decision={"outcome": "REJECTED", "by": who, "reasons": [comment], "ts": DB.now()}, offer=None)
    elif action == "request_info":
        _need_info(c, a, [comment], who, comment)
    elif action in ("approve", "counter"):
        amt, trm = (a["amount"], a["term_months"]) if action == "approve" else (amount, term)
        if not (amt and trm and p["min_amount"] <= amt <= p["max_amount"] and p["min_term"] <= trm <= p["max_term"]):
            raise D.DomainError("Сумма/срок вне лимитов продукта", 422)
        kind = "APPROVED" if action == "approve" else "COUNTER"
        transition(c, a, "OFFER_READY", who, comment or "Решение андеррайтера",
                   decision={"outcome": kind, "by": who, "reasons": [comment or "Одобрено андеррайтером"], "ts": DB.now()},
                   offer=D.make_offer(a, amt, trm, kind, g))
    else:
        raise D.DomainError("Неизвестное действие", 422)

def sign_and_disburse(c, a, actor):
    transition(c, a, "SIGNED", actor, "Договор подписан (симуляция ЭП)")
    transition(c, a, "DISBURSED", "system", "Средства зачислены на расчётный счёт (симуляция выдачи)")
