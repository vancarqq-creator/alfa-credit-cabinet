"""Сквозные тесты основного сценария. Запуск: PIPELINE_SYNC=1 pytest -q"""
import os, tempfile
os.environ.update(PIPELINE_SYNC="1", DB_PATH=os.path.join(tempfile.mkdtemp(), "t.db"))
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import integrations as I
from app.seed import PASSWORD

T = I.test_inns()
INN = {k.replace("ООО ", "").strip("«»").replace("«", "").replace("»", "").replace("ИП Смирнов Алексей Викторович", "ИП"): v for k, v in T.items()}

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c

def auth(client, login):
    r = client.post("/api/auth/login", json={"login": login, "password": PASSWORD}); assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}

def body(inn, product="working_capital", amount=1_200_000, term=24, rev=24e6, profit=3.6e6, obl=40e3, docs=None):
    return {"product": product, "amount": amount, "term_months": term, "purpose": "Закупка сырья", "consent": True,
            "company": {"inn": inn, "name": "Тест", "contact_name": "Иванов И.И.", "contact_role": "Директор"},
            "financials": {"revenue_year": rev, "profit_year": profit, "monthly_obligations": obl}, "documents": docs or []}

def run(client, h, b):
    a = client.post("/api/applications", json=b, headers=h).json()
    r = client.post(f"/api/applications/{a['id']}/submit", json={}, headers=h); assert r.status_code == 200
    return client.get(f"/api/applications/{a['id']}", headers=h).json()

def test_happy_path_approve_sign_disburse(client):
    h = auth(client, "client1"); a = run(client, h, body(INN["Пекарня Заря"]))
    assert a["status"] == "OFFER_READY" and a["offer"]["kind"] == "APPROVED" and a["offer"]["rate"] == 16.0
    assert "scoring" not in a and "checks" not in a                        # клиент не видит внутренний скоринг
    assert client.post(f"/api/applications/{a['id']}/offer/accept", headers=h).json()["status"] == "SIGNING"
    assert client.post(f"/api/applications/{a['id']}/sign", headers=h).json()["status"] == "DISBURSED"
    path = [e["to_status"] for e in client.get(f"/api/applications/{a['id']}/events", headers=h).json()]
    assert path == ["DRAFT", "SUBMITTED", "VALIDATION", "ENRICHMENT", "SCORING", "OFFER_READY", "SIGNING", "SIGNED", "DISBURSED"]

def test_counter_offer(client):
    h = auth(client, "client2")
    a = run(client, h, body(INN["ИП"], amount=600_000, rev=3.6e6, profit=6e5, obl=5e3))
    assert a["status"] == "OFFER_READY" and a["offer"]["kind"] == "COUNTER" and a["offer"]["amount"] < 600_000

def test_hard_stop_reject(client):
    h = auth(client, "client1"); a = run(client, h, body(INN["Ромашка"]))
    assert a["status"] == "REJECTED" and a["offer"] is None and "ликвидируется" in a["decision"]["reasons"][0]

def test_low_score_reject(client):
    h = auth(client, "client1"); a = run(client, h, body(INN["СтройРесурс"], amount=1e6, term=12, rev=12e6, profit=5e5, obl=30e3))
    assert a["status"] == "REJECTED"

def test_info_requested_then_resubmit(client):
    h = auth(client, "client1"); b = body(INN["Пекарня Заря"], product="equipment", amount=2_000_000, term=36)
    a = run(client, h, b)
    assert a["status"] == "INFO_REQUESTED" and "бухгалтерскую отчётность" in a["info_request"]["items"][0]
    client.put(f"/api/applications/{a['id']}", json={"documents": [{"name": "otchet.pdf", "kind": "financial_statements"}]}, headers=h)
    client.post(f"/api/applications/{a['id']}/submit", json={"comment": "Приложили отчётность"}, headers=h)
    assert client.get(f"/api/applications/{a['id']}", headers=h).json()["status"] == "OFFER_READY"

def test_unknown_inn_and_invalid_inn(client):
    h = auth(client, "client1")
    assert run(client, h, body(I.NOT_FOUND_INN))["status"] == "INFO_REQUESTED"
    a = run(client, h, body("1234567890")); assert a["status"] == "INFO_REQUESTED" and "ИНН" in a["info_request"]["items"][0]

def test_manual_review_by_underwriter(client):
    h, u = auth(client, "client3"), auth(client, "underwriter")
    docs = [{"name": "buh.pdf", "kind": "financial_statements"}]
    a = run(client, h, body(INN["ТехноЛогистик"], product="equipment", amount=4e6, term=36, rev=60e6, profit=9e6, obl=100e3, docs=docs))
    assert a["status"] == "MANUAL_REVIEW"
    assert client.post(f"/api/bank/applications/{a['id']}/decision", json={"action": "approve"}, headers=h).status_code == 403
    assert client.post(f"/api/bank/applications/{a['id']}/decision", json={"action": "reject"}, headers=u).status_code == 422   # нужен комментарий
    sv = client.get(f"/api/applications/{a['id']}", headers=u).json(); assert sv["scoring"]["score"] > 0 and sv["checks"]["bki"]
    r = client.post(f"/api/bank/applications/{a['id']}/decision", json={"action": "counter", "amount": 3.5e6, "term_months": 36, "comment": "Снижаем сумму"}, headers=u)
    assert r.json()["status"] == "OFFER_READY" and r.json()["offer"]["amount"] == 3.5e6
    assert client.get("/api/bank/stats", headers=u).json()["OFFER_READY"] >= 1

def test_manual_review_gray_zone_and_request_info(client):
    h, u = auth(client, "client1"), auth(client, "underwriter")
    a = run(client, h, body(INN["Гелиос-Сервис"], product="express", amount=200_000, term=12, rev=10e6, profit=1.6e6, obl=45e3))
    assert a["status"] == "MANUAL_REVIEW"
    r = client.post(f"/api/bank/applications/{a['id']}/decision", json={"action": "request_info", "comment": "Пришлите договор аренды"}, headers=u)
    assert r.json()["status"] == "INFO_REQUESTED" and r.json()["info_request"]["items"] == ["Пришлите договор аренды"]

def test_access_control_and_invalid_transitions(client):
    h1, h2 = auth(client, "client1"), auth(client, "client2")
    a = run(client, h1, body(INN["Пекарня Заря"]))
    assert client.get(f"/api/applications/{a['id']}", headers=h2).status_code == 404       # чужая заявка
    assert client.get("/api/applications").status_code == 401
    assert client.post(f"/api/applications/{a['id']}/sign", headers=h1).status_code == 409  # подпись до принятия оферты
    assert client.post(f"/api/applications/{a['id']}/submit", json={}, headers=h1).status_code == 409
    assert client.post("/api/auth/login", json={"login": "client1", "password": "bad"}).status_code == 401

def test_draft_persistence_and_catalog(client):
    h = auth(client, "client2")
    d = client.post("/api/applications", json={"product": "express", "amount": 100000}, headers=h).json()
    client.put(f"/api/applications/{d['id']}", json={"company": {"inn": "7701000019"}}, headers=h)
    g = client.get(f"/api/applications/{d['id']}", headers=h).json()
    assert g["status"] == "DRAFT" and g["amount"] == 100000 and g["company"]["inn"] == "7701000019"
    assert len(client.get("/api/products", headers=h).json()) == 3
    assert client.get("/api/registry/lookup?inn=7701000019", headers=h).json()["name"].startswith("ООО")
    assert client.get("/health").json() == {"status": "ok"}
