"""Синтетические тестовые аккаунты (создаются при первом старте). Пароль всех демо-аккаунтов: Demo#2026"""
from . import db as DB

PASSWORD = "Demo#2026"
USERS = [("client1", "client", "Мария Иванова (Пекарня Заря)"), ("client2", "client", "Алексей Смирнов (ИП)"),
         ("client3", "client", "Дмитрий Петров (ТехноЛогистик)"), ("underwriter", "underwriter", "Елена Кредитова, андеррайтер")]

def seed(hash_pwd):
    with DB.db() as c:
        for login, role, name in USERS:
            c.execute("INSERT OR IGNORE INTO users(login,pwd_hash,role,name) VALUES(?,?,?,?)", (login, hash_pwd(PASSWORD), role, name))
