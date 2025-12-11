# backend/main.py
import os
import io
import datetime
from typing import Optional
from dotenv import load_dotenv

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import pandas as pd
import supabase
import logging

# Import your AI engine function
from ai_engine import process_chat  # expects (session_id, message) -> str

load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- Env checks ---
REQ_ENV = ["SUPABASE_URL", "SUPABASE_KEY"]
missing = [k for k in REQ_ENV if not os.getenv(k)]
if missing:
    logging.warning(f"Missing env vars: {missing} (some DB endpoints will fallback to local save)")

# Supabase client (used where available)
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")
supa = None
if SUPA_URL and SUPA_KEY:
    try:
        supa = supabase.create_client(SUPA_URL, SUPA_KEY)
    except Exception as e:
        logging.exception("Failed to create Supabase client")

app = FastAPI()
# serve /static if you have assets
app.mount("/static", StaticFiles(directory="static"), name="static")
# templates/index.html should be present in templates/
templates = Jinja2Templates(directory="templates")

# allow all origins during dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request models ---
class ChatReq(BaseModel):
    session_id: str
    message: str

# --- Helpers ---
def compute_plan_from_df(df: pd.DataFrame, monthly_emi: int, wallet_balance: float):
    df = df.copy()
    if 'gross_sales' not in df.columns:
        raise ValueError("CSV missing gross_sales column")
    df['gross_sales'] = pd.to_numeric(df['gross_sales'], errors='coerce').fillna(0)
    avg_daily = float(df['gross_sales'].mean())
    today = datetime.date.today()
    # end of month
    last_day = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    remaining_days = max(1, (last_day - today).days + 1)
    required = max(0, monthly_emi - wallet_balance)
    base_daily = required / remaining_days
    cap = avg_daily * 0.8
    recommended_daily = int(round(max(1, min(base_daily, cap))))
    return {
        "avg_daily": round(avg_daily,2),
        "base_daily": round(base_daily,2),
        "recommended_daily": recommended_daily,
        "remaining_days": remaining_days
    }

# --- Routes ---

@app.get("/")
async def root(request: Request):
    # Serve templates/index.html
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/chat")
async def chat_api(req: ChatReq):
    try:
        # persist user message to chat_memory (if supabase configured)
        try:
            if supa:
                supa.table("chat_memory").insert({
                    "session_id": req.session_id,
                    "role": "user",
                    "content": req.message,
                    "created_at": datetime.datetime.utcnow().isoformat()
                }).execute()
        except Exception:
            logging.exception("Failed to persist user chat (continuing)")

        # call AI engine (synchronous)
        response_text = process_chat(req.session_id, req.message)

        # persist assistant reply
        try:
            if supa:
                supa.table("chat_memory").insert({
                    "session_id": req.session_id,
                    "role": "assistant",
                    "content": response_text,
                    "created_at": datetime.datetime.utcnow().isoformat()
                }).execute()
        except Exception:
            logging.exception("Failed to persist assistant reply (continuing)")

        # Return both keys 'response' and 'reply' to keep frontend compatible
        return JSONResponse({"response": response_text, "reply": response_text})

    except Exception as e:
        logging.exception("Error in /api/chat")
        return JSONResponse({"response": "Server busy. Try again.", "reply": "Server busy. Try again."}, status_code=500)

@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...), merchant_id: str = Form(...), monthly_emi: Optional[int] = Form(3000)):
    """
    Accepts CSV file (date,gross_sales[,cash_in_hand]) and stores rows into supabase 'transactions' (if configured).
    Returns computed avg_daily and recommended_daily.
    """
    try:
        content = await file.read()
        text = content.decode('utf-8', errors='ignore')
        df = pd.read_csv(io.StringIO(text))
        # basic validation
        if 'date' not in df.columns or 'gross_sales' not in df.columns:
            return JSONResponse({"error":"CSV must contain 'date' and 'gross_sales' columns"}, status_code=400)

        # Insert transactions into Supabase if available
        rows_to_insert = []
        for _, r in df.iterrows():
            rows_to_insert.append({
                "merchant_id": merchant_id,
                "date": str(r['date']),
                "gross_sales": float(r['gross_sales']),
                "cash_in_hand": float(r.get('cash_in_hand', 0))
            })
        try:
            if supa:
                # bulk insert (adjust table names if needed)
                supa.table("transactions").insert(rows_to_insert).execute()
        except Exception:
            logging.exception("Supabase insert failed; falling back to local save")
            # fallback: save locally
            os.makedirs("sample_data", exist_ok=True)
            fname = f"sample_data/{merchant_id}_{int(datetime.datetime.utcnow().timestamp())}.csv"
            with open(fname, "wb") as f:
                f.write(content)

        # Try to get wallet balance from merchant_profiles
        wallet_balance = 0.0
        try:
            if supa:
                res = supa.table("merchant_profiles").select("*").eq("merchant_id", merchant_id).execute()
                profs = res.data
                if profs:
                    wallet_balance = float(profs[0].get("wallet_balance", 0))
        except Exception:
            logging.exception("Could not fetch merchant profile (wallet_balance fallback to 0)")

        plan = compute_plan_from_df(df, int(monthly_emi), wallet_balance)
        return JSONResponse(plan)
    except Exception as e:
        logging.exception("Error in /api/upload-csv")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/dashboard")
async def dashboard_api():
    try:
        if not supa:
            return JSONResponse({"total_volume":0,"failed_count":0,"logs":[],"db_status":"not-configured"})
        response = supa.table("transaction_logs").select("*").order("created_at", desc=True).limit(50).execute()
        logs = response.data or []
        failed_count = len([l for l in logs if l.get('status','').lower() == 'failed'])
        total = len(logs)
        return JSONResponse({
            "total_volume": total,
            "failed_count": failed_count,
            "logs": logs,
            "db_status": "Connected"
        })
    except Exception:
        logging.exception("Error in /api/dashboard")
        return JSONResponse({"total_volume":0,"failed_count":0,"logs":[],"db_status":"error"}, status_code=500)

@app.get("/api/transactions/logs")
async def transaction_logs(limit: int = 10, offset: int = 0):
    try:
        if not supa:
            return JSONResponse({"transactions": [], "total": 0})
        res = supa.table("transaction_logs").select("*").order("created_at", desc=True).limit(limit).offset(offset).execute()
        rows = res.data or []
        return JSONResponse({"transactions": rows, "total": len(rows)})
    except Exception:
        logging.exception("Error in /api/transactions/logs")
        return JSONResponse({"transactions": [], "total": 0}, status_code=500)

@app.get("/health")
async def health():
    return JSONResponse({"status":"ok", "time": datetime.datetime.utcnow().isoformat()})
