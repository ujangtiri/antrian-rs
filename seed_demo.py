"""Fill a fresh hospital.db with fictional demo patients (obviously fake NIKs).

Run once before app.py if you want something on screen:  python seed_demo.py
"""
import uuid
from datetime import datetime

from app import DatabaseManager

DEMO = [
    # (name, fake NIK, age, poli, urgency, queue number)
    ("Pasien Contoh A", "0000000000000001", 34, "Umum", "Reguler", "REG-UMU0001"),
    ("Pasien Contoh B", "0000000000000002", 7, "Anak", "Reguler", "REG-ANA0001"),
    ("Pasien Contoh C", "0000000000000003", 58, "Jantung", "UGD", "UGD-JAN0001"),
    ("Pasien Contoh D", "0000000000000004", 29, "Bedah", "UGD", "UGD-BED0001"),
]

db = DatabaseManager()
db.create_admin()
with db._get_connection() as conn:
    for nama, nik, umur, poli, urgency, number in DEMO:
        if conn.execute("SELECT 1 FROM patients WHERE nik=?", (nik,)).fetchone():
            continue
        pid = str(uuid.uuid4())
        conn.execute("INSERT INTO patients VALUES (?,?,?,?,?,?,?)",
                     (pid, nama, nik, umur, poli, urgency, datetime.now()))
        conn.execute("INSERT INTO queues VALUES (?,?,?,?,?,?)",
                     (str(uuid.uuid4()), pid, number, "Menunggu", datetime.now(), None))
    conn.commit()
print("Demo data inserted.")
