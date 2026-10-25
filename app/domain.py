"""Доменная модель: продукты, расчёт платежа, валидация, скоринг, кредитное решение, автомат состояний.
Скоринг и кредитное решение разделены: скоринг даёт оценку риска, решение учитывает продукт, сумму, срок, внешние проверки."""
import math, re, uuid
from datetime import date, timedelta

PRODUCTS = {
    "working_capital": {"name": "Оборотный кредит", "desc": "Закупки, зарплаты, сезонные кассовые разрывы",
                        "min_amount": 100_000, "max_amount": 5_000_000, "min_term": 3, "max_term": 36, "base_rate": 16.0},
    "equipment": {"name": "Кредит на оборудование", "desc": "Покупка оборудования и транспорта",
                  "min_amount": 300_000, "max_amount": 15_000_000, "min_term": 12, "max_term": 60, "base_rate": 15.0},
    "express": {"name": "Экспресс-кредит", "desc": "Небольшая сумма на короткий срок",
                "min_amount": 50_000, "max_amount": 1_000_000, "min_term": 3, "max_term": 12, "base_rate": 19.0},
}
GRADE_MARGIN = {"A": 0.0, "B": 2.0, "C": 4.0, "D": 7.0}   # надбавка к базовой ставке по классу риска
AUTO_LIMIT = 3_000_000       # свыше — только ручное рассмотрение андеррайтером
DOCS_THRESHOLD = 1_500_000   # свыше — обязательна бухгалтерская отчётность
MAX_BURDEN = 0.5             # допустимая доля денежного потока (прибыль/12), идущая на платежи по кредитам
SCORE_REJECT, SCORE_AUTO = 450, 650

# ---------- автомат состояний заявки ----------
TRANSITIONS = {
    "DRAFT": {"SUBMITTED", "CANCELLED"},
    "SUBMITTED": {"VALIDATION"},
    "VALIDATION": {"ENRICHMENT", "INFO_REQUESTED"},
    "ENRICHMENT": {"SCORING", "INFO_REQUESTED"},
    "SCORING": {"OFFER_READY", "MANUAL_REVIEW", "REJECTED"},
    "MANUAL_REVIEW": {"OFFER_READY", "INFO_REQUESTED", "REJECTED"},
    "INFO_REQUESTED": {"SUBMITTED", "CANCELLED"},
    "OFFER_READY": {"SIGNING", "DECLINED"},
    "SIGNING": {"SIGNED", "DECLINED"},
    "SIGNED": {"DISBURSED"},
    "DISBURSED": set(), "REJECTED": set(), "DECLINED": set(), "CANCELLED": set(),
}
TRANSIENT = {"SUBMITTED", "VALIDATION", "ENRICHMENT", "SCORING"}   # обрабатываются конвейером автоматически
FINAL = {s for s, t in TRANSITIONS.items() if not t}

class DomainError(Exception):
    def __init__(self, msg, code=409): self.msg, self.code = msg, code

def check_transition(frm, to):
    if to not in TRANSITIONS.get(frm, ()):
        raise DomainError(f"Недопустимый переход {frm} → {to}")

# ---------- расчёты ----------
def annuity(amount, rate, term):
    r = rate / 1200
    return amount / term if r == 0 else amount * r / (1 - (1 + r) ** -term)

def max_amount_for_payment(pay, rate, term):
    r = rate / 1200
    return pay * term if r == 0 else pay * (1 - (1 + r) ** -term) / r

def make_offer(a, amount, term, kind, grade):
    rate = round(PRODUCTS[a["product"]]["base_rate"] + GRADE_MARGIN[grade], 2)
    pay = round(annuity(amount, rate, term), 2)
    return {"kind": kind, "amount": amount, "term_months": term, "rate": rate, "grade": grade, "payment": pay,
            "overpayment": round(pay * term - amount, 2), "valid_until": str(date.today() + timedelta(days=10))}

# ---------- ИНН ----------
def _ctrl(digits, w): return str(sum(int(d) * k for d, k in zip(digits, w)) % 11 % 10)
W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8); W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8); W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
def inn10(b9): return b9 + _ctrl(b9, W10)
def inn12(b10): b = b10 + _ctrl(b10, W11); return b + _ctrl(b, W12)
def valid_inn(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{10}|\d{12}", s): return False
    return s == (inn10(s[:9]) if len(s) == 10 else inn12(s[:10]))

# ---------- валидация полноты и корректности ----------
def validate(a):
    e, p = [], PRODUCTS.get(a.get("product"))
    co, fin, docs = a.get("company") or {}, a.get("financials") or {}, a.get("documents") or []
    if not p: e.append(("product", "Не выбран кредитный продукт"))
    else:
        if not a.get("amount") or not p["min_amount"] <= a["amount"] <= p["max_amount"]:
            e.append(("amount", f"Сумма: от {p['min_amount']:,} до {p['max_amount']:,} ₽".replace(",", " ")))
        if not a.get("term_months") or not p["min_term"] <= a["term_months"] <= p["max_term"]:
            e.append(("term_months", f"Срок: от {p['min_term']} до {p['max_term']} мес."))
    if not (a.get("purpose") or "").strip(): e.append(("purpose", "Укажите цель финансирования"))
    if not valid_inn(co.get("inn")): e.append(("company.inn", "Некорректный ИНН (10 или 12 цифр, проверка контрольной суммы)"))
    for k, t in (("name", "Укажите название компании"), ("contact_name", "Укажите ФИО представителя"),
                 ("contact_role", "Укажите должность/роль представителя")):
        if not (co.get(k) or "").strip(): e.append((f"company.{k}", t))
    for k in ("revenue_year", "profit_year", "monthly_obligations"):
        if fin.get(k) is None: e.append((f"financials.{k}", "Заполните финансовые показатели"))
    if fin.get("revenue_year") is not None and fin["revenue_year"] <= 0: e.append(("financials.revenue_year", "Выручка должна быть больше 0"))
    if (fin.get("monthly_obligations") or 0) < 0: e.append(("financials.monthly_obligations", "Платежи не могут быть отрицательными"))
    if not a.get("consent"): e.append(("consent", "Необходимо согласие на обработку данных и запрос в БКИ"))
    if (a.get("amount") or 0) > DOCS_THRESHOLD and not any(d.get("kind") == "financial_statements" for d in docs):
        e.append(("documents", "Для суммы свыше 1 500 000 ₽ приложите бухгалтерскую отчётность"))
    return [{"field": f, "message": m} for f, m in e]

# ---------- скоринг: балльная модель с объяснением вклада факторов ----------
def months_since(d):
    y, m, _ = map(int, d.split("-")); t = date.today(); return (t.year - y) * 12 + t.month - m

def score(a, chk):
    fin, eg, b, f = a["financials"], chk["egrul"], chk["bki"], chk["fns"]
    margin, cash = fin["profit_year"] / fin["revenue_year"], fin["profit_year"] / 12
    age, F = months_since(eg["reg_date"]), []
    def add(name, value, pts): F.append({"factor": name, "value": value, "points": pts})
    add("Возраст бизнеса", f"{age} мес.", -60 if age < 12 else -20 if age < 24 else 30 if age < 60 else 60)
    add("Рентабельность (прибыль/выручка)", f"{margin:.1%}", -100 if margin < 0 else -20 if margin < .05 else 30 if margin < .15 else 70)
    dti = fin["monthly_obligations"] / cash if cash > 0 else 9.99
    add("Действующая долговая нагрузка", f"{dti:.0%} от мес. прибыли", 50 if dti < .15 else 20 if dti < .3 else -40 if dti < .5 else -100)
    add("Длина кредитной истории", f"{b['history_months']} мес.", -30 if b["history_months"] == 0 else 0 if b["history_months"] < 12 else 40)
    add("Текущая просрочка", "есть" if b["overdue_now"] else "нет", -200 if b["overdue_now"] else 0)
    d = b["max_delay_days_12m"]
    add("Макс. просрочка за 12 мес.", f"{d} дн.", 60 if d == 0 else -30 if d <= 30 else -100 if d <= 90 else -200)
    add("Налоговая задолженность (ФНС)", "есть" if f["tax_arrears"] else "нет", -80 if f["tax_arrears"] else 0)
    flags = f["mass_address"] or f["mass_director"]
    add("Риск-флаги ФНС (массовый адрес/руководитель)", "есть" if flags else "нет", -60 if flags else 0)
    ratio = a["amount"] / fin["revenue_year"]
    add("Запрошенная сумма к годовой выручке", f"{ratio:.0%}", 30 if ratio < .15 else 0 if ratio < .4 else -40 if ratio < .8 else -90)
    total = max(0, min(1000, 500 + sum(x["points"] for x in F)))
    return {"score": total, "grade": "A" if total >= 700 else "B" if total >= 600 else "C" if total >= 500 else "D",
            "factors": F, "model": "points-v1"}

# ---------- кредитное решение (результат не бинарный) ----------
def decide(a, sc, chk):
    """Возвращает (outcome, reasons, offer): APPROVED | COUNTER | MANUAL_REVIEW | REJECTED."""
    p, fin, eg, b, f = PRODUCTS[a["product"]], a["financials"], chk["egrul"], chk["bki"], chk["fns"]
    if eg["status"] != "ACTIVE": return "REJECTED", ["Компания ликвидируется или прекратила деятельность"], None
    if f["disqualified"]: return "REJECTED", ["Руководитель дисквалифицирован (сведения ФНС)"], None
    if b["overdue_now"] and b["max_delay_days_12m"] > 90: return "REJECTED", ["Действующая просрочка по кредитам свыше 90 дней"], None
    s, g = sc["score"], sc["grade"]
    if s < SCORE_REJECT: return "REJECTED", [f"Оценка риска {s} ниже допустимого порога {SCORE_REJECT}"], None
    rate = p["base_rate"] + GRADE_MARGIN[g]
    capacity = MAX_BURDEN * fin["profit_year"] / 12 - fin["monthly_obligations"]
    if capacity <= 0: return "REJECTED", ["Недостаточная платёжеспособность: действующие платежи занимают допустимую долю денежного потока"], None
    if annuity(a["amount"], rate, a["term_months"]) > capacity:
        amt = math.floor(max_amount_for_payment(capacity, rate, a["term_months"]) / 10_000) * 10_000
        if amt < p["min_amount"]: return "REJECTED", ["Платёжеспособности недостаточно даже для минимальной суммы продукта"], None
        return "COUNTER", [f"Запрошенный платёж превышает допустимую нагрузку ({capacity:,.0f} ₽/мес.); банк готов одобрить меньшую сумму".replace(",", " ")], \
            make_offer(a, amt, a["term_months"], "COUNTER", g)
    if s >= SCORE_AUTO and a["amount"] <= AUTO_LIMIT:
        return "APPROVED", [f"Оценка риска {s} (класс {g}), платёж в пределах допустимой нагрузки"], make_offer(a, a["amount"], a["term_months"], "APPROVED", g)
    why = f"Оценка риска {s} в серой зоне ({SCORE_REJECT}–{SCORE_AUTO - 1})" if s < SCORE_AUTO else f"Сумма превышает лимит автоматического решения {AUTO_LIMIT:,} ₽".replace(",", " ")
    return "MANUAL_REVIEW", [why + " — требуется решение андеррайтера"], None

def new_id(): return "AB-" + uuid.uuid4().hex[:8].upper()
