# PARASHAR TRANSPORT — Internet API

This is the central internet API for Android LR entry + audit.

## Local test
```bash
python -m pip install -r requirements.txt
set PARASHAR_API_KEY=YOUR_SECRET
uvicorn main:app --host 0.0.0.0 --port 8000
```
Health: `/health`

## Production
Deploy this folder to a cloud service that supports Docker (or Python/uvicorn). Set `PARASHAR_API_KEY` as a secret and use the HTTPS URL.

The Android app should call:
`POST https://YOUR-DOMAIN/api/lr`
with header `X-API-Key` and JSON fields `vehicle_no, station, lr_no, weight, submitted_by`.

Do not expose the SQLite file directly. For a larger production deployment, move the API database to managed PostgreSQL.
