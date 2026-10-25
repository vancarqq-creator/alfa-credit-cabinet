"""HTTP API (FastAPI) + раздача веб-интерфейса. Swagger UI: /docs, OpenAPI: /openapi.json"""
import hashlib, hmac, os, secrets, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db as DB, domain as D, integrations as INT, service as SVC

SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me-0123456789abcdef")
TOKEN_TTL_H = int(os.getenv("TOKEN_TTL_HOURS", "8"))
STATIC = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_):
    from .seed import seed
    DB.init(); seed(hash_pwd); SVC.resume_pending()
    yield

app = FastAPI(lifespan=lifespan, title="Умный кредитный кабинет предпринимателя", version="1.0.0",
              description="Цифровой кредитный конвейер для МСБ: личный кабинет клиента + рабочее место банка. Все внешние сервисы — симуляторы.")

class Company(BaseModel):
    inn: Optional[str] = None; name: Optional[str] = None; contact_name: Optional[str] = None
    contact_role: Optional[str] = None; okved: Optional[str] = None
class Financials(BaseModel):
    revenue_year: Optional[float] = Field(None, description="Выручка за 12 мес., ₽")
    profit_year: Optional[float] = Field(None, description="Чистая прибыль за 12 мес., ₽")
    monthly_obligations: Optional[float] = Field(None, description="Ежемесячные платежи по действующим кредитам, ₽")
class Doc(BaseModel):
    name: str = Field(max_length=200); kind: str = Field(pattern="^(financial_statements|egrul_extract|other)$")
class ApplicationIn(BaseModel):
    product: Optional[str] = None; amount: Optional[float] = None; term_months: Optional[int] = None
    purpose: Optional[str] = Field(None, max_length=500); company: Optional[Company] = None
    financials: Optional[Financials] = None; documents: Optional[list[Doc]] = None; consent: Optional[bool] = None
class Login(BaseModel): login: str; password: str
class SubmitIn(BaseModel): comment: Optional[str] = Field(None, max_length=1000)
class DecisionIn(BaseModel):
    action: str = Field(pattern="^(approve|counter|reject|request_info)$")
    amount: Optional[float] = None; term_months: Optional[int] = None; comment: Optional[str] = Field(None, max_length=1000)

# ---------- безопасность ----------
def hash_pwd(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + ":" + hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1).hex()
def check_pwd(pw, stored):
    salt, h = stored.split(":")
    return hmac.compare_digest(hash_pwd(pw, bytes.fromhex(salt)).split(":")[1], h)

_fails: dict = {}   # login -> (count, first_ts): простая защита от перебора пароля
def user_dep(request: Request):
    h = request.headers.get("authorization", "")
    if not h.startswith("Bearer "): raise HTTPException(401, "Требуется авторизация")
    try: p = jwt.decode(h[7:], SECRET, algorithms=["HS256"])
    except jwt.PyJWTError: raise HTTPException(401, "Сессия истекла или токен недействителен")
    return p
def underwriter(u=Depends(user_dep)):
    if u["role"] != "underwriter": raise HTTPException(403, "Доступно только сотрудникам банка")
    return u

@app.middleware("http")
async def sec_headers(request, call_next):
    r = await call_next(request)
    r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
    return r

@app.exception_handler(D.DomainError)
async def domain_err(_, e): return JSONResponse({"detail": e.msg}, e.code)
@app.exception_handler(DB.Conflict)
async def conflict(_, e): return JSONResponse({"detail": "Заявка была изменена в другой сессии, обновите страницу"}, 409)


@app.get("/health", tags=["system"])
def health():
    with DB.db() as c: c.execute("SELECT 1")
    return {"status": "ok"}

# ---------- auth / справочники ----------
@app.post("/api/auth/login", tags=["auth"])
def login(b: Login):
    cnt, ts = _fails.get(b.login, (0, time.time()))
    if cnt >= 5 and time.time() - ts < 60: raise HTTPException(429, "Слишком много попыток входа, подождите минуту")
    with DB.db() as c: u = c.execute("SELECT * FROM users WHERE login=?", (b.login,)).fetchone()
    if not u or not check_pwd(b.password, u["pwd_hash"]):
        _fails[b.login] = (cnt + 1 if time.time() - ts < 60 else 1, ts if cnt else time.time())
        raise HTTPException(401, "Неверный логин или пароль")
    _fails.pop(b.login, None)
    user = {"id": u["id"], "login": u["login"], "role": u["role"], "name": u["name"]}
    tok = jwt.encode({**user, "sub": str(u["id"]), "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_H)}, SECRET, algorithm="HS256")
    return {"token": tok, "user": user}

@app.get("/api/products", tags=["catalog"])
def products(_=Depends(user_dep)):
    return [{"id": k, **v} for k, v in D.PRODUCTS.items()]

@app.get("/api/registry/lookup", tags=["catalog"], summary="Поиск компании по ИНН (симулятор ЕГРЮЛ/ЕГРИП)")
def lookup(inn: str = Query(...), _=Depends(user_dep)):
    if not D.valid_inn(inn): raise HTTPException(422, "Некорректный ИНН")
    e = INT.egrul(inn)
    if not e: raise HTTPException(404, "Компания не найдена в реестре")
    return {"inn": inn, "name": e["name"], "okved": e["okved"], "head": e["head"], "status": e["status"], "type": e["type"]}

# ---------- заявки ----------
def view(a, user):
    a = dict(a)
    if user["role"] == "client":   # минимизация данных: клиент не видит скоринг и сырые ответы БКИ/ФНС
        a.pop("scoring", None); a.pop("checks", None)
    return a

def load(c, app_id, user):
    a = DB.get_app(c, app_id)
    if not a: raise HTTPException(404, "Заявка не найдена")
    if user["role"] == "client" and a["user_id"] != int(user["sub"]): raise HTTPException(404, "Заявка не найдена")
    if user["role"] == "underwriter" and a["status"] == "DRAFT": raise HTTPException(404, "Заявка не найдена")
    return a

def apply_body(a, b: ApplicationIn):
    for k in ("product", "amount", "term_months", "purpose", "consent"):
        v = getattr(b, k)
        if v is not None: a[k] = v
    for k in ("company", "financials"):
        v = getattr(b, k)
        if v is not None: a[k] = {**(a.get(k) or {}), **v.model_dump(exclude_none=True)}
    if b.documents is not None: a["documents"] = [d.model_dump() for d in b.documents]
    if a.get("product") and a["product"] not in D.PRODUCTS: raise D.DomainError("Неизвестный продукт", 422)

def client_only(u=Depends(user_dep)):
    if u["role"] != "client": raise HTTPException(403, "Доступно только клиентам")
    return u

@app.post("/api/applications", tags=["applications"], status_code=201, summary="Создать черновик заявки")
def create(b: ApplicationIn, u=Depends(client_only)):
    a = {"id": D.new_id(), "user_id": int(u["sub"]), "status": "DRAFT", "consent": False, "documents": [], "company": {}, "financials": {}}
    apply_body(a, b)
    with DB.db() as c:
        DB.insert_app(c, a); DB.add_event(c, a["id"], u["login"], None, "DRAFT", "Черновик создан")
        return view(DB.get_app(c, a["id"]), u)

@app.get("/api/applications", tags=["applications"], summary="Список заявок (клиент — свои, банк — все, кроме черновиков)")
def listing(status: Optional[str] = None, u=Depends(user_dep)):
    q, args = "SELECT * FROM applications WHERE 1=1", []
    if u["role"] == "client": q += " AND user_id=?"; args.append(int(u["sub"]))
    else: q += " AND status!='DRAFT'"
    if status: q += " AND status=?"; args.append(status)
    with DB.db() as c:
        return [view(DB.row_to_app(r), u) for r in c.execute(q + " ORDER BY updated_at DESC LIMIT 200", args)]

@app.get("/api/applications/{app_id}", tags=["applications"])
def get(app_id: str, u=Depends(user_dep)):
    with DB.db() as c: return view(load(c, app_id, u), u)

@app.get("/api/applications/{app_id}/events", tags=["applications"], summary="Журнал переходов (аудит)")
def get_events(app_id: str, u=Depends(user_dep)):
    with DB.db() as c: load(c, app_id, u); return DB.events(c, app_id)

@app.put("/api/applications/{app_id}", tags=["applications"], summary="Изменить черновик / дополнить заявку по запросу банка")
def update(app_id: str, b: ApplicationIn, u=Depends(client_only)):
    with DB.db() as c:
        a = load(c, app_id, u)
        if a["status"] not in ("DRAFT", "INFO_REQUESTED"): raise D.DomainError("Заявку нельзя редактировать в статусе " + a["status"])
        apply_body(a, b); DB.save_app(c, a)
        return view(a, u)

@app.post("/api/applications/{app_id}/submit", tags=["applications"], summary="Отправить в банк (запускает конвейер)")
def submit(app_id: str, b: SubmitIn = SubmitIn(), u=Depends(client_only)):
    with DB.db() as c:
        a = load(c, app_id, u)
        if a["status"] not in ("DRAFT", "INFO_REQUESTED"): raise D.DomainError("Отправка невозможна в статусе " + a["status"])
        SVC.transition(c, a, "SUBMITTED", u["login"], b.comment or "Заявка отправлена в банк", info_request=None)
        out = view(a, u)
    SVC.start_pipeline(app_id)
    return out

def _client_action(app_id, u, to, comment):
    with DB.db() as c:
        a = load(c, app_id, u); SVC.transition(c, a, to, u["login"], comment); return view(a, u)

@app.post("/api/applications/{app_id}/offer/accept", tags=["applications"], summary="Принять предложение банка")
def accept(app_id: str, u=Depends(client_only)):
    with DB.db() as c:
        a = load(c, app_id, u)
        if a["offer"] and a["offer"]["valid_until"] < str(datetime.now(timezone.utc).date()): raise D.DomainError("Срок действия предложения истёк")
    return _client_action(app_id, u, "SIGNING", "Клиент принял предложение")

@app.post("/api/applications/{app_id}/offer/decline", tags=["applications"], summary="Отказаться от предложения")
def decline(app_id: str, u=Depends(client_only)): return _client_action(app_id, u, "DECLINED", "Клиент отказался от предложения")

@app.post("/api/applications/{app_id}/cancel", tags=["applications"], summary="Отозвать заявку")
def cancel(app_id: str, u=Depends(client_only)): return _client_action(app_id, u, "CANCELLED", "Клиент отозвал заявку")

@app.post("/api/applications/{app_id}/sign", tags=["applications"], summary="Подписать договор (симуляция ЭП) → выдача (симуляция)")
def sign(app_id: str, u=Depends(client_only)):
    with DB.db() as c:
        a = load(c, app_id, u)
        if a["status"] != "SIGNING": raise D.DomainError("Подписание недоступно в статусе " + a["status"])
        SVC.sign_and_disburse(c, a, u["login"]); return view(a, u)

@app.post("/api/bank/applications/{app_id}/decision", tags=["bank"], summary="Решение андеррайтера по заявке на ручном рассмотрении")
def bank_decision(app_id: str, b: DecisionIn, u=Depends(underwriter)):
    with DB.db() as c:
        a = load(c, app_id, u)
        SVC.underwriter_decide(c, a, u, b.action, b.amount, b.term_months, b.comment); return view(a, u)

@app.get("/api/bank/stats", tags=["bank"], summary="Количество заявок по статусам")
def stats(u=Depends(underwriter)):
    with DB.db() as c: return {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM applications WHERE status!='DRAFT' GROUP BY status")}

@app.get("/api/meta/states", tags=["system"], summary="Автомат состояний заявки")
def states(): return {"transitions": {k: sorted(v) for k, v in D.TRANSITIONS.items()}, "final": sorted(D.FINAL)}

@app.get("/")
def index(): return FileResponse(STATIC / "index.html")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
