"""СИМУЛЯТОРЫ внешних сервисов (реальные интеграции недоступны по условиям кейса). Детерминированы, без сети.
Контракт упрощён, смысл сохранён: ЕГРЮЛ/ЕГРИП, ФНС «Прозрачный бизнес», БКИ."""
from .domain import inn10, inn12

def _p(inn, name, reg, okved, head, addr, status="ACTIVE", kind="ЮЛ", hist=0, loans=0, overdue=False, delay=0, debt=0,
       arrears=False, mass_addr=False, mass_dir=False, disq=False):
    return inn, ({"inn": inn, "name": name, "type": kind, "status": status, "reg_date": reg, "okved": okved, "head": head, "address": addr},
                 {"history_months": hist, "active_loans": loans, "overdue_now": overdue, "max_delay_days_12m": delay, "total_debt": debt},
                 {"tax_arrears": arrears, "mass_address": mass_addr, "mass_director": mass_dir, "disqualified": disq})

_DATA = dict([
    _p(inn10("770100001"), "ООО «Пекарня Заря»", "2018-03-12", "10.71 Производство хлеба", "Иванова М.С.", "г. Москва, ул. Тестовая, 1", hist=60, loans=1, debt=400_000),
    _p(inn12("7701000020"), "ИП Смирнов Алексей Викторович", "2025-02-10", "47.11 Розничная торговля", "Смирнов А.В.", "г. Казань, ул. Образцовая, 5", kind="ИП", hist=8),
    _p(inn10("770100003"), "ООО «ТехноЛогистик»", "2020-06-01", "49.41 Грузовой транспорт", "Петров Д.А.", "г. Тверь, пр-т Макетный, 12", hist=36, loans=3, delay=20, debt=3_500_000),
    _p(inn10("770100004"), "ООО «СтройРесурс»", "2019-09-20", "41.20 Строительство зданий", "Сидоров К.Н.", "г. Тула, ул. Условная, 7", hist=30, loans=4, overdue=True, delay=45, debt=6_000_000, arrears=True),
    _p(inn10("770100005"), "ООО «Ромашка»", "2015-01-15", "46.90 Оптовая торговля", "Орлова Е.П.", "г. Самара, ул. Вымышленная, 3", status="LIQUIDATING", hist=70),
    _p(inn10("770100006"), "ООО «Гелиос-Сервис»", "2022-01-10", "62.01 Разработка ПО", "Фёдоров И.И.", "г. Омск, ул. Демонстрационная, 9", hist=18, loans=1, delay=15, debt=300_000),
])
NOT_FOUND_INN = inn10("770199999")   # корректный по контрольной сумме, но отсутствует в «реестре»

def egrul(inn):  return (_DATA.get(inn) or (None,))[0]
def enrich(inn):
    if inn not in _DATA: return None
    e, b, f = _DATA[inn]
    return {"egrul": e, "bki": b, "fns": f, "simulated": True}
def test_inns(): return {v[0]["name"]: k for k, v in _DATA.items()}
