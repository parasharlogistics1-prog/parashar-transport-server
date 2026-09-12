import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
import psycopg2
import psycopg2.extras

from dotenv import load_dotenv
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
API_KEY = os.getenv("PARASHAR_API_KEY", "").strip()

app = FastAPI(title="PARASHAR TRANSPORT Internet API", version="V43")

LR_COLUMNS = [
    "date", "vou_no", "account", "entry_type", "truck_no", "bilty_gr_no",
    "loading_point", "city", "weight", "driver", "driver_mobile", "route",
    "party", "mobile", "remark", "party_gstin", "booked_amount",
    "expense_amount", "net_amount", "amount_status", "petrol_pump", "pp_rec_no",
    "pp_amount", "pp_remark", "driver_amount", "cash_payment", "cash_account",
    "bank_payment", "mode", "bank_name", "bank_remark", "account_holder",
    "driver_ac", "ifsc", "payment_ref", "payment_status", "document",
    "pod_paid_amount", "pod_payment_remark", "pod_cleared_at", "pod_status",
    "created_at", "updated_at"
]


def conn():
    if not DATABASE_URL:
        raise HTTPException(503, "DATABASE_URL is not configured")
    return psycopg2.connect(DATABASE_URL)


def auth(x_api_key: str):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "Invalid API key")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_lr(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def lr_parts(value: str):
    raw = str(value or "").strip().upper()
    return {p for p in re.split(r"[^A-Z0-9]+", raw) if p}


def find_locked_lr(cur, bilty_gr_no: str, exclude_id: Optional[int] = None):
    key = normalize_lr(bilty_gr_no)
    parts = lr_parts(bilty_gr_no)
    if not key and not parts:
        return None
    cur.execute("SELECT id, bilty_gr_no FROM lr_records WHERE bilty_gr_no IS NOT NULL AND BTRIM(bilty_gr_no) <> ''")
    for row in cur.fetchall():
        rid, existing = row
        if exclude_id is not None and int(rid) == int(exclude_id):
            continue
        existing = str(existing or "")
        if key and normalize_lr(existing) == key:
            return existing
        ep = lr_parts(existing)
        if parts and ep and parts.intersection(ep):
            return existing
    return None


def init_schema():
    c = conn()
    try:
        cur = c.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS app_credentials (
            id INTEGER PRIMARY KEY CHECK (id=1),
            username TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            updated_at TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lr_records (
            id BIGSERIAL PRIMARY KEY,
            date TEXT, vou_no TEXT UNIQUE, account TEXT, entry_type TEXT,
            truck_no TEXT NOT NULL, bilty_gr_no TEXT NOT NULL,
            loading_point TEXT, city TEXT, weight TEXT, driver TEXT,
            driver_mobile TEXT, route TEXT, party TEXT, mobile TEXT, remark TEXT,
            party_gstin TEXT, booked_amount DOUBLE PRECISION DEFAULT 0,
            expense_amount DOUBLE PRECISION DEFAULT 0, net_amount DOUBLE PRECISION DEFAULT 0,
            amount_status TEXT, petrol_pump TEXT, pp_rec_no TEXT,
            pp_amount DOUBLE PRECISION DEFAULT 0, pp_remark TEXT,
            driver_amount DOUBLE PRECISION DEFAULT 0, cash_payment DOUBLE PRECISION DEFAULT 0,
            cash_account TEXT, bank_payment DOUBLE PRECISION DEFAULT 0, mode TEXT,
            bank_name TEXT, bank_remark TEXT, account_holder TEXT, driver_ac TEXT,
            ifsc TEXT, payment_ref TEXT, payment_status TEXT, document TEXT,
            pod_paid_amount DOUBLE PRECISION DEFAULT 0, pod_payment_remark TEXT,
            pod_cleared_at TEXT, pod_status TEXT DEFAULT 'Pending',
            created_at TEXT, updated_at TEXT
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lr_records_bilty ON lr_records(bilty_gr_no)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lr_records_date ON lr_records(date)")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS station_rates (
            id BIGSERIAL PRIMARY KEY, station TEXT NOT NULL, contract_year TEXT NOT NULL,
            effective_from TEXT DEFAULT '01.08.2025', rate_85 DOUBLE PRECISION DEFAULT 0,
            rate_10 DOUBLE PRECISION DEFAULT 0, active TEXT DEFAULT 'Active',
            UNIQUE(station, contract_year, effective_from)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS billing_documents (
            id BIGSERIAL PRIMARY KEY, lr_id BIGINT UNIQUE NOT NULL,
            bill_no INTEGER NOT NULL, bill_date TEXT NOT NULL, created_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS billing_batches (
            id BIGSERIAL PRIMARY KEY, batch_key TEXT UNIQUE NOT NULL,
            bill_no INTEGER UNIQUE NOT NULL, bill_date TEXT NOT NULL, created_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bill_payments (
            bill_no INTEGER PRIMARY KEY, amount_received DOUBLE PRECISION DEFAULT 0,
            deduction_amount DOUBLE PRECISION DEFAULT 0, is_cleared INTEGER DEFAULT 0,
            payment_date TEXT, status TEXT DEFAULT 'Pending', updated_at TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS transporters (
            id BIGSERIAL PRIMARY KEY, transporter_name TEXT UNIQUE NOT NULL,
            gst_no TEXT, contact_number TEXT, address TEXT, active TEXT DEFAULT 'Active',
            created_at TEXT, updated_at TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS truck_supplier_notes (
            id BIGSERIAL PRIMARY KEY, note_no TEXT UNIQUE NOT NULL, loading_date TEXT NOT NULL,
            supplier_name TEXT, supplier_truck_no TEXT, owner_name TEXT, owner_number TEXT,
            lr_no TEXT, lr_date TEXT, from_place TEXT, to_place TEXT, weight TEXT,
            load_type TEXT DEFAULT 'Full Load', truck_type TEXT, weight_guarantee TEXT,
            oversize TEXT DEFAULT 'No', pay_by TEXT DEFAULT 'Consignor',
            freight_amount DOUBLE PRECISION DEFAULT 0, freight_type TEXT DEFAULT 'FIX',
            halting_charge DOUBLE PRECISION DEFAULT 0, extra_charge DOUBLE PRECISION DEFAULT 0,
            commission_charge DOUBLE PRECISION DEFAULT 0, bilty_charge DOUBLE PRECISION DEFAULT 0,
            bank_name TEXT, bank_account_no TEXT, bank_ifsc TEXT, remark TEXT,
            shortage_amount DOUBLE PRECISION DEFAULT 0, created_at TEXT, updated_at TEXT,
            status TEXT DEFAULT 'Pending', amount_paid DOUBLE PRECISION DEFAULT 0,
            payment_status TEXT DEFAULT 'Pending'
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bank_statement_uploads (
            id BIGSERIAL PRIMARY KEY, file_name TEXT NOT NULL, file_hash TEXT UNIQUE NOT NULL,
            account_number TEXT, bank_name TEXT, statement_from TEXT, statement_to TEXT,
            imported_at TEXT NOT NULL, transaction_count INTEGER DEFAULT 0, skipped_count INTEGER DEFAULT 0
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id BIGSERIAL PRIMARY KEY, upload_id BIGINT NOT NULL REFERENCES bank_statement_uploads(id),
            account_number TEXT, bank_name TEXT, transaction_date TEXT, value_date TEXT,
            reference TEXT, narration TEXT, transaction_type TEXT, amount DOUBLE PRECISION NOT NULL,
            balance DOUBLE PRECISION, fingerprint TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bank_transaction_allocations (
            id BIGSERIAL PRIMARY KEY, transaction_id BIGINT UNIQUE NOT NULL REFERENCES bank_transactions(id),
            supplier_note_id BIGINT UNIQUE NOT NULL REFERENCES truck_supplier_notes(id),
            allocated_amount DOUBLE PRECISION NOT NULL, allocated_at TEXT NOT NULL
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bank_tx_date ON bank_transactions(transaction_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bank_tx_type ON bank_transactions(transaction_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bank_alloc_note ON bank_transaction_allocations(supplier_note_id)")
        c.commit()
    finally:
        c.close()


@app.on_event("startup")
def startup():
    init_schema()


class AndroidLR(BaseModel):
    vehicle_no: str = Field(min_length=1, max_length=40)
    loading_point: str = Field(default="CHHATA", max_length=100)
    station: str = Field(min_length=1, max_length=100)
    lr_no: str = Field(min_length=1, max_length=80)
    weight: str = Field(min_length=1, max_length=40)
    submitted_by: str = Field(default="Android User", max_length=80)


@app.get("/health")
def health():
    c = conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT 1")
        return {"ok": True, "service": "PARASHAR TRANSPORT", "database": "postgresql", "version": "V43", "utc": now_iso()}
    finally:
        c.close()


@app.post("/api/lr")
def create_android_lr(item: AndroidLR, x_api_key: str = Header(default="")):
    auth(x_api_key)
    vehicle = item.vehicle_no.strip().upper()
    loading_point = item.loading_point.strip().upper() or "CHHATA"
    station = item.station.strip()
    lr = item.lr_no.strip()
    weight = item.weight.strip()
    user = item.submitted_by.strip() or "Android User"
    locked = None
    c = conn()
    try:
        cur = c.cursor()
        locked = find_locked_lr(cur, lr)
        if locked:
            raise HTTPException(409, f"LR number already used: {locked}")
        now = now_iso()
        # Android's four fields are mapped into the real V43 LR record.
        # station -> city, LR -> bilty_gr_no, vehicle -> truck_no, weight -> weight.
        cur.execute("""
            INSERT INTO lr_records
            (date, vou_no, entry_type, truck_no, bilty_gr_no, loading_point, city, weight,
             created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (now[:10], None, "ANDROID", vehicle, lr, loading_point, station, weight, now, now))
        rid = cur.fetchone()[0]
        c.commit()
        return {"ok": True, "id": rid, "message": "LR submitted to V43 central database", "submitted_at": now}
    except HTTPException:
        c.rollback(); raise
    except psycopg2.errors.UniqueViolation:
        c.rollback()
        raise HTTPException(409, "LR record conflicts with an existing V43 record")
    except Exception as e:
        c.rollback()
        raise HTTPException(500, f"Database error: {e}")
    finally:
        c.close()


@app.get("/api/lr/recent")
def recent(limit: int = 30, x_api_key: str = Header(default="")):
    auth(x_api_key)
    limit = max(1, min(limit, 200))
    c = conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id,date,vou_no,truck_no,bilty_gr_no,loading_point,city,weight,entry_type,created_at,updated_at
            FROM lr_records ORDER BY id DESC LIMIT %s
        """, (limit,))
        return cur.fetchall()
    finally:
        c.close()


@app.get("/api/lr/{lr_id}")
def get_lr(lr_id: int, x_api_key: str = Header(default="")):
    auth(x_api_key)
    c = conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM lr_records WHERE id=%s", (lr_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "LR record not found")
        return row
    finally:
        c.close()


@app.get("/api/station-rates")
def station_rates(x_api_key: str = Header(default="")):
    auth(x_api_key)
    c = conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM station_rates ORDER BY station, effective_from")
        return cur.fetchall()
    finally:
        c.close()
