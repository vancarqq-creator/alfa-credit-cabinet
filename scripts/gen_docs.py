"""Генерирует docs/openapi.json, docs/postman_collection.json, docs/state-diagram.md из кода (единый источник правды)."""
import json, os, sys, tempfile
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "x.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.main import app
from app import domain as D

os.makedirs("docs", exist_ok=True)
json.dump(app.openapi(), open("docs/openapi.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def req(name, method, path, body=None, auth=True, test=None):
    r = {"method": method, "header": [{"key": "Content-Type", "value": "application/json"}] + ([{"key": "Authorization", "value": "Bearer {{token}}"}] if auth else []),
         "url": {"raw": "{{baseUrl}}" + path, "host": ["{{baseUrl}}"], "path": path.lstrip("/").split("/")}}
    if body is not None: r["body"] = {"mode": "raw", "raw": json.dumps(body, ensure_ascii=False, indent=2)}
    item = {"name": name, "request": r}
    if test: item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": test}}]
    return item
login = lambda n, u: req(f"Вход: {u}", "POST", "/api/auth/login", {"login": u, "password": "Demo#2026"}, False,
                         ["const j = pm.response.json(); pm.collectionVariables.set('token', j.token);"])
app_body = {"product": "working_capital", "amount": 1200000, "term_months": 24, "purpose": "Закупка сырья", "consent": True,
            "company": {"inn": "7701000019", "name": "ООО «Пекарня Заря»", "contact_name": "Иванова М.С.", "contact_role": "Собственник"},
            "financials": {"revenue_year": 24000000, "profit_year": 3600000, "monthly_obligations": 40000}, "documents": []}
saveid = ["pm.collectionVariables.set('appId', pm.response.json().id);"]
coll = {"info": {"name": "Умный кредитный кабинет", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "variable": [{"key": "baseUrl", "value": "http://localhost:8000"}, {"key": "token", "value": ""}, {"key": "appId", "value": ""}],
        "item": [
            {"name": "1. Клиентский сценарий", "item": [
                login(0, "client1"), req("Продукты", "GET", "/api/products"), req("Поиск компании по ИНН", "GET", "/api/registry/lookup?inn=7701000019"),
                req("Создать черновик", "POST", "/api/applications", app_body, test=saveid), req("Отправить в банк", "POST", "/api/applications/{{appId}}/submit", {}),
                req("Карточка заявки (повторить до OFFER_READY)", "GET", "/api/applications/{{appId}}"), req("Журнал переходов", "GET", "/api/applications/{{appId}}/events"),
                req("Принять предложение", "POST", "/api/applications/{{appId}}/offer/accept"), req("Подписать договор → выдача", "POST", "/api/applications/{{appId}}/sign"),
                req("Список моих заявок", "GET", "/api/applications")]},
            {"name": "2. Банк (андеррайтер)", "item": [
                login(0, "underwriter"), req("Очередь: на ручном рассмотрении", "GET", "/api/applications?status=MANUAL_REVIEW"), req("Статистика по статусам", "GET", "/api/bank/stats"),
                req("Решение: встречное предложение", "POST", "/api/bank/applications/{{appId}}/decision", {"action": "counter", "amount": 3500000, "term_months": 36, "comment": "Снижаем сумму"}),
                req("Решение: запрос информации", "POST", "/api/bank/applications/{{appId}}/decision", {"action": "request_info", "comment": "Пришлите договор аренды"}),
                req("Решение: отказ", "POST", "/api/bank/applications/{{appId}}/decision", {"action": "reject", "comment": "Высокий риск"})]},
            {"name": "3. Служебные", "item": [req("Health", "GET", "/health", auth=False), req("Автомат состояний", "GET", "/api/meta/states", auth=False)]}]}
json.dump(coll, open("docs/postman_collection.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

lines = ["# Диаграмма состояний заявки", "", "Сгенерировано из `app/domain.py::TRANSITIONS` (`python scripts/gen_docs.py`).", "", "```mermaid", "stateDiagram-v2", "    [*] --> DRAFT"]
for s, ts in D.TRANSITIONS.items():
    lines += [f"    {s} --> {t}" for t in sorted(ts)]
lines += [f"    {s} --> [*]" for s in sorted(D.FINAL)] + ["```"]
open("docs/state-diagram.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("docs generated")
