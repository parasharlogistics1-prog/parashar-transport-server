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
    init_full_sync_schema()


class AndroidLR(BaseModel):
    vehicle_no: str = Field(min_length=1, max_length=40)
    loading_point: str = Field(default="CHHATA", max_length=100)
    station: str = Field(min_length=1, max_length=100)
    lr_no: str = Field(min_length=1, max_length=80)
    weight: str = Field(min_length=1, max_length=40)
    submitted_by: str = Field(default="Android User", max_length=80)


SYNC_TABLES = [
    "lr_records",
    "station_rates",
    "billing_documents",
    "billing_batches",
    "bill_payments",
    "transporters",
    "truck_supplier_notes",
    "bank_statement_uploads",
    "bank_transactions",
    "bank_transaction_allocations",
]

SYNC_META_SQL = """
CREATE TABLE IF NOT EXISTS sync_devices (
    device_id TEXT PRIMARY KEY,
    device_name TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_changes (
    id BIGSERIAL PRIMARY KEY,
    sync_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    device_id TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_changes_id
    ON sync_changes(id);

CREATE INDEX IF NOT EXISTS idx_sync_changes_table_sync
    ON sync_changes(table_name, sync_id);
"""

SYNC_COLUMNS_SQL = {
    "lr_records": """
        ALTER TABLE lr_records
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE lr_records
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "station_rates": """
        ALTER TABLE station_rates
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE station_rates
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "billing_documents": """
        ALTER TABLE billing_documents
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE billing_documents
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "billing_batches": """
        ALTER TABLE billing_batches
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE billing_batches
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "bill_payments": """
        ALTER TABLE bill_payments
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE bill_payments
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "transporters": """
        ALTER TABLE transporters
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE transporters
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "truck_supplier_notes": """
        ALTER TABLE truck_supplier_notes
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE truck_supplier_notes
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "bank_statement_uploads": """
        ALTER TABLE bank_statement_uploads
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE bank_statement_uploads
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "bank_transactions": """
        ALTER TABLE bank_transactions
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE bank_transactions
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
    "bank_transaction_allocations": """
        ALTER TABLE bank_transaction_allocations
        ADD COLUMN IF NOT EXISTS sync_id TEXT;
        ALTER TABLE bank_transaction_allocations
        ADD COLUMN IF NOT EXISTS sync_deleted INTEGER DEFAULT 0;
    """,
}


def init_full_sync_schema():
    c = conn()
    try:
        cur = c.cursor()
        cur.execute(SYNC_META_SQL)

        for sql in SYNC_COLUMNS_SQL.values():
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)

        # Backfill sync IDs for existing rows.
        # Most tables use "id" as their primary key.
        # bill_payments uses "bill_no" as its primary key.
        primary_key_map = {
            "bill_payments": "bill_no",
        }

        for table_name in SYNC_TABLES:
            pk_column = primary_key_map.get(table_name, "id")

            cur.execute(
                f"""
                UPDATE {table_name}
                SET sync_id = %s || ':' || {pk_column}::text
                WHERE sync_id IS NULL OR BTRIM(sync_id) = ''
                """,
                (table_name,)
            )

            cur.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_{table_name}_sync_id
                ON {table_name}(sync_id)
                """
            )

        c.commit()
    finally:
        c.close()


class SyncPushItem(BaseModel):
    table_name: str
    sync_id: str
    operation: str = "UPSERT"
    row_data: Dict[str, Any] = {}
    device_id: str


class SyncPushRequest(BaseModel):
    items: list[SyncPushItem] = Field(default_factory=list)


class SyncPullRequest(BaseModel):
    device_id: str
    after_change_id: int = 0
    limit: int = 500


@app.post("/api/sync/register")
def sync_register(device_id: str, device_name: str = "", x_api_key: str = Header(default="")):
    auth(x_api_key)

    device_id = device_id.strip()
    device_name = device_name.strip() or device_id

    if not device_id:
        raise HTTPException(400, "device_id is required")

    now = now_iso()

    c = conn()
    try:
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO sync_devices
            (device_id, device_name, last_seen_at, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (device_id)
            DO UPDATE SET
                device_name=EXCLUDED.device_name,
                last_seen_at=EXCLUDED.last_seen_at,
                updated_at=EXCLUDED.updated_at
            """,
            (device_id, device_name, now, now, now),
        )
        c.commit()
        return {
            "ok": True,
            "device_id": device_id,
            "server_time": now,
        }
    finally:
        c.close()


@app.get("/api/sync/status")
def sync_status(x_api_key: str = Header(default="")):
    auth(x_api_key)

    c = conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT COALESCE(MAX(id),0) FROM sync_changes")
        last_change_id = int(cur.fetchone()[0] or 0)

        result = {}
        for table_name in SYNC_TABLES:
            cur.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE COALESCE(sync_deleted,0)=0"
            )
            result[table_name] = int(cur.fetchone()[0] or 0)

        return {
            "ok": True,
            "last_change_id": last_change_id,
            "tables": result,
            "server_time": now_iso(),
        }
    finally:
        c.close()


SYNC_PUSHABLE_TABLES = {
    "lr_records",
    "station_rates",
    "billing_documents",
    "billing_batches",
    "bill_payments",
    "transporters",
    "truck_supplier_notes",
    "bank_statement_uploads",
    "bank_transactions",
    "bank_transaction_allocations",
}

TABLE_COLUMNS = {
    "lr_records": [
        "date","vou_no","account","entry_type","truck_no","bilty_gr_no",
        "loading_point","city","weight","driver","driver_mobile","route",
        "party","mobile","remark","party_gstin","booked_amount",
        "expense_amount","net_amount","amount_status","petrol_pump","pp_rec_no",
        "pp_amount","pp_remark","driver_amount","cash_payment","cash_account",
        "bank_payment","mode","bank_name","bank_remark","account_holder",
        "driver_ac","ifsc","payment_ref","payment_status","document",
        "pod_paid_amount","pod_payment_remark","pod_cleared_at","pod_status",
        "created_at","updated_at"
    ],
    "station_rates": [
        "station","contract_year","effective_from","rate_85","rate_10","active"
    ],
    "billing_documents": [
        "lr_id","bill_no","bill_date","created_at"
    ],
    "billing_batches": [
        "batch_key","bill_no","bill_date","created_at"
    ],
    "bill_payments": [
        "bill_no","amount_received","deduction_amount","is_cleared",
        "payment_date","status","updated_at"
    ],
    "transporters": [
        "transporter_name","gst_no","contact_number","address","active",
        "created_at","updated_at"
    ],
    "truck_supplier_notes": [
        "note_no","loading_date","supplier_name","supplier_truck_no",
        "owner_name","owner_number","lr_no","lr_date","from_place","to_place",
        "weight","load_type","truck_type","weight_guarantee","oversize",
        "pay_by","freight_amount","freight_type","halting_charge",
        "extra_charge","commission_charge","bilty_charge","bank_name",
        "bank_account_no","bank_ifsc","remark","shortage_amount","created_at",
        "updated_at","status","amount_paid","payment_status"
    ],
    "bank_statement_uploads": [
        "file_name","file_hash","account_number","bank_name","statement_from",
        "statement_to","imported_at","transaction_count","skipped_count"
    ],
    "bank_transactions": [
        "upload_id","account_number","bank_name","transaction_date",
        "value_date","reference","narration","transaction_type","amount",
        "balance","fingerprint","created_at"
    ],
    "bank_transaction_allocations": [
        "transaction_id","supplier_note_id","allocated_amount","allocated_at"
    ],
}


def record_sync_change(cur, sync_id, table_name, operation, device_id, changed_at):
    cur.execute(
        """
        INSERT INTO sync_changes
        (sync_id, table_name, operation, device_id, changed_at)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (sync_id, table_name, operation, device_id, changed_at),
    )


def safe_sync_row(table_name, row_data):
    allowed = TABLE_COLUMNS.get(table_name)
    if not allowed:
        raise HTTPException(400, f"Unsupported sync table: {table_name}")

    result = {}
    for col in allowed:
        if col in row_data:
            result[col] = row_data[col]

    return result


def upsert_sync_row(cur, item, changed_at):
    table_name = item.table_name.strip()

    if table_name not in SYNC_PUSHABLE_TABLES:
        raise HTTPException(400, f"Unsupported sync table: {table_name}")

    sync_id = item.sync_id.strip()
    device_id = item.device_id.strip()
    operation = item.operation.strip().upper()

    if not sync_id:
        raise HTTPException(400, "sync_id is required")

    if not device_id:
        raise HTTPException(400, "device_id is required")

    if operation == "DELETE":
        cur.execute(
            f"""
            UPDATE {table_name}
            SET sync_deleted = 1
            WHERE sync_id = %s
            """,
            (sync_id,),
        )

        if cur.rowcount == 0:
            row = {"sync_deleted": 1}

            cur.execute(
                f"""
                INSERT INTO {table_name} (sync_id, sync_deleted)
                VALUES (%s, 1)
                ON CONFLICT (sync_id)
                DO UPDATE SET sync_deleted = 1
                """,
                (sync_id,),
            )

        record_sync_change(
            cur,
            sync_id,
            table_name,
            "DELETE",
            device_id,
            changed_at,
        )
        return "DELETE"

    row_data = safe_sync_row(table_name, item.row_data)
    row_data["sync_id"] = sync_id
    row_data["sync_deleted"] = 0

    columns = list(row_data.keys())
    values = [row_data[c] for c in columns]

    assignments = [
        f"{c}=EXCLUDED.{c}"
        for c in columns
        if c != "sync_id"
    ]

    columns_sql = ",".join(columns)
    placeholders = ",".join(["%s"] * len(values))
    assignments_sql = ",".join(assignments)

    cur.execute(
        f"""
        INSERT INTO {table_name} ({columns_sql})
        VALUES ({placeholders})
        ON CONFLICT (sync_id)
        DO UPDATE SET {assignments_sql}
        """,
        values,
    )

    record_sync_change(
        cur,
        sync_id,
        table_name,
        "UPSERT",
        device_id,
        changed_at,
    )

    return "UPSERT"


@app.post("/api/sync/push")
def sync_push(payload: SyncPushRequest, x_api_key: str = Header(default="")):
    auth(x_api_key)

    if len(payload.items) > 1000:
        raise HTTPException(400, "Maximum 1000 sync items per request")

    c = conn()
    try:
        cur = c.cursor()
        changed_at = now_iso()
        results = []

        for item in payload.items:
            operation = upsert_sync_row(cur, item, changed_at)
            results.append({
                "table_name": item.table_name,
                "sync_id": item.sync_id,
                "operation": operation,
            })

        c.commit()

        return {
            "ok": True,
            "processed": len(results),
            "items": results,
            "server_time": changed_at,
        }

    except HTTPException:
        c.rollback()
        raise

    except psycopg2.errors.UniqueViolation as e:
        c.rollback()
        raise HTTPException(
            409,
            "Sync record conflicts with an existing unique record"
        )

    except Exception as e:
        c.rollback()
        raise HTTPException(500, f"Sync push error: {e}")

    finally:
        c.close()


@app.post("/api/sync/pull")
def sync_pull(
    payload: SyncPullRequest,
    x_api_key: str = Header(default="")
):
    auth(x_api_key)

    device_id = payload.device_id.strip()
    after_id = max(0, int(payload.after_change_id))
    limit = max(1, min(int(payload.limit), 1000))

    if not device_id:
        raise HTTPException(400, "device_id is required")

    c = conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                sync_id,
                table_name,
                operation,
                device_id,
                changed_at
            FROM sync_changes
            WHERE id > %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (after_id, limit),
        )

        changes = cur.fetchall()

        output = []

        for change in changes:
            table_name = change["table_name"]
            sync_id = change["sync_id"]

            if table_name not in SYNC_PUSHABLE_TABLES:
                continue

            cur.execute(
                f"""
                SELECT *
                FROM {table_name}
                WHERE sync_id = %s
                LIMIT 1
                """,
                (sync_id,),
            )

            row = cur.fetchone()

            output.append({
                "change_id": int(change["id"]),
                "table_name": table_name,
                "sync_id": sync_id,
                "operation": change["operation"],
                "source_device_id": change["device_id"],
                "changed_at": change["changed_at"],
                "row_data": dict(row) if row else None,
            })

        last_change_id = after_id
        if changes:
            last_change_id = int(changes[-1]["id"])

        return {
            "ok": True,
            "device_id": device_id,
            "after_change_id": after_id,
            "last_change_id": last_change_id,
            "count": len(output),
            "items": output,
            "server_time": now_iso(),
        }

    finally:
        c.close()


@app.get("/api/sync/bootstrap")
def sync_bootstrap(x_api_key: str = Header(default="")):
    auth(x_api_key)

    c = conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Parent/dependency order is intentional.
        table_order = [
            "lr_records",
            "station_rates",
            "billing_batches",
            "billing_documents",
            "bill_payments",
            "transporters",
            "truck_supplier_notes",
            "bank_statement_uploads",
            "bank_transactions",
            "bank_transaction_allocations",
        ]

        snapshot = {}

        for table_name in table_order:
            cur.execute(
                f"""
                SELECT *
                FROM {table_name}
                ORDER BY sync_id NULLS LAST
                """
            )

            rows = cur.fetchall()
            snapshot[table_name] = [dict(row) for row in rows]

        return {
            "ok": True,
            "version": "V43",
            "server_time": now_iso(),
            "tables": snapshot,
        }

    finally:
        c.close()


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
        sync_id = f"lr_records:{now.replace('-', '').replace(':', '').replace('.', '').replace('+', '').replace('T', '')}:{vehicle}:{lr}".upper()

        cur.execute("""
            INSERT INTO lr_records
            (date, vou_no, entry_type, truck_no, bilty_gr_no, loading_point, city, weight,
             created_at, updated_at, sync_id, sync_deleted)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
            RETURNING id
        """, (now[:10], None, "ANDROID", vehicle, lr, loading_point, station, weight,
              now, now, sync_id))

        rid = cur.fetchone()[0]

        record_sync_change(
            cur,
            sync_id,
            "lr_records",
            "UPSERT",
            user,
            now,
        )

        c.commit()

        return {
            "ok": True,
            "id": rid,
            "sync_id": sync_id,
            "message": "LR submitted to V43 central database",
            "submitted_at": now,
        }
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
