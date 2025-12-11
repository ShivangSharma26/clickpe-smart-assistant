# overwrite ai_engine.py with this exact file
# ai_engine.py (REPLACE your existing file)
import os, logging, datetime, json
from typing import Dict, Any, TypedDict, List
from dotenv import load_dotenv
import supabase
import re
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
#USE_LLM=False
USE_LLM = os.getenv("USE_LLM", "1") == "1"


load_dotenv()
logging.basicConfig(level=logging.INFO)

# sanity env
REQUIRED = ["SUPABASE_URL","SUPABASE_KEY","GOOGLE_API_KEY"]
missing = [k for k in REQUIRED if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing env: {missing}")

# clients
supa = supabase.create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=os.getenv("GOOGLE_API_KEY"), temperature=0.2)
emb = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_store = SupabaseVectorStore(client=supa, embedding=emb, table_name="documents", query_name="match_documents")

class AgentState(TypedDict):
    session_id: str
    user_query: str
    intent: str
    context: str
    final_response: str

# deterministic eligibility check (simple, transparent rules)
def eligibility_check(merchant_id: str, requested_amount: int, tenor_months: int) -> Dict[str,Any]:
    # fetch required data
    try:
        rows = supa.table("merchant_profiles").select("*").eq("merchant_id", merchant_id).execute().data
        profile = rows[0] if rows else {}
    except Exception:
        profile = {}
    # fetch last 90 days txn
    try:
        txns = supa.table("transactions").select("*").eq("merchant_id", merchant_id).order("date", desc=True).limit(180).execute().data
    except Exception:
        txns = []
    # defaults
    avg_daily = 0
    if txns:
        # assume transactions have 'gross_sales' and 'date'
        # compute simple avg over last 30 days if available
        last_30 = txns[:30]
        try:
            avg_daily = sum(float(t.get("gross_sales",0)) for t in last_30) / max(1,len(last_30))
        except Exception:
            avg_daily = 0
    wallet_balance = float(profile.get("wallet_balance",0))
    mandate = profile.get("mandate_status","UNKNOWN")

    # compute requested monthly EMI (simple equal principal+interest placeholder)
    monthly_installment = max(1, int(requested_amount / max(1, tenor_months)))

    coverage_ratio = (avg_daily * 30) / monthly_installment if monthly_installment>0 else 0
    # on-time rate from transaction logs (simple)
    try:
        logs = supa.table("transaction_logs").select("*").eq("merchant_id", merchant_id).order("created_at", desc=True).limit(180).execute().data
        attempts = [l for l in logs if l.get("type")=="debit_attempt"]
        success = [l for l in attempts if l.get("status") in ("Success","Succeeded","success")]
        on_time_rate = (len(success)/len(attempts))*100 if attempts else 100.0
    except Exception:
        on_time_rate = 100.0

    reasons = []
    eligible = True
    if mandate != "ACTIVE":
        eligible = False
        reasons.append("Mandate not ACTIVE")
    if on_time_rate < 70:
        eligible = False
        reasons.append(f"On-time debit rate low ({on_time_rate:.0f}%)")
    if coverage_ratio < 1.1:
        eligible = False
        reasons.append(f"Coverage ratio low ({coverage_ratio:.2f})")
    # if wallet very low, flag
    if wallet_balance < monthly_installment * 0.25:
        reasons.append("Wallet low vs monthly installment")

    return {
        "eligible": eligible,
        "monthly_installment": monthly_installment,
        "avg_daily": round(avg_daily,2),
        "coverage_ratio": round(coverage_ratio,2),
        "on_time_rate": round(on_time_rate,1),
        "wallet_balance": wallet_balance,
        "mandate_status": mandate,
        "reasons": reasons
    }

# Router: decide path
def router_node(state: Dict[str,Any]) -> Dict[str,str]:
    q = (state.get("user_query") or "").lower()
    
    # 1. Loan Requests (Amount/Money related)
    if any(k in q for k in ["loan", "lakh", "apply", "money"]):
        return {"intent":"loan_request"}
        
    # 2. Ops / Failures (Error related)
    if any(k in q for k in ["failed", "why debit", "deducted", "insufficient", "error"]):
        return {"intent":"database"}

    # 3. NEW FEATURE: Savings / Daily Plan
    # Agar user puche "kitna save karu", "aaj ka plan", "emi"
    if any(k in q for k in ["save", "saving", "how much", "today", "plan", "emi"]):
        return {"intent":"savings_plan"}

    # Default Policy
    return {"intent":"policy"}

def database_node(state: Dict[str,Any]) -> Dict[str,str]:
    mid = state.get("session_id","m_001")
    try:
        logs = supa.table("transaction_logs").select("*").eq("merchant_id", mid).order("created_at", desc=True).limit(10).execute().data
    except Exception:
        logs = []
    return {"context": json.dumps({"recent_logs": logs}, default=str)}

def policy_rag_node(state: Dict[str,Any]) -> Dict[str,str]:
    query = state.get("user_query","")
    try:
        docs = vector_store.similarity_search(query, k=3)
        ctx = "\n".join(getattr(d,"page_content",str(d)) for d in docs)
        if not ctx.strip():
            ctx = "No policy doc found"
    except Exception:
        ctx = "RAG search failed"
    return {"context": ctx}

def generator_node(state: Dict[str,Any]) -> Dict[str,str]:
    import time, re
    user_q = state.get("user_query","")
    sid = state.get("session_id","m_001")
    intent = state.get("intent","policy")

    # ============================================================
    # 1. LOAN REQUEST LOGIC 
    # ============================================================
    if intent == "loan_request":
        nums = re.findall(r"\d+", user_q.replace(",",""))
        requested_amount = 100000
        tenor = 2
        
        # Logic to extract 'lakh'
        if "lakh" in user_q.lower():
            m = re.search(r"(\d+)\s*lakh", user_q.lower())
            if m:
                requested_amount = int(m.group(1)) * 100000
        elif nums:
            requested_amount = int(nums[0])
            
        # Logic to extract 'months'
        m2 = re.search(r"(\d+)\s*month", user_q.lower())
        if m2:
            tenor = int(m2.group(1))

        mid = sid
        res = eligibility_check(mid, requested_amount, tenor)

        reply = f"Pre-check for ₹{requested_amount:,} over {tenor} months:\n"
        reply += f"Monthly est: ₹{res['monthly_installment']} | Avg daily: ₹{res['avg_daily']} | Coverage: {res['coverage_ratio']} | On-time: {res['on_time_rate']}%\n"
        if res["eligible"]:
            reply += "Status: Preliminary eligible → Manual underwriting required (collect KYC / 30-day monitoring)."
        else:
            reply += "Status: Not eligible. Reasons: " + "; ".join(res["reasons"]) + ". Suggestions: increase daily savings, ensure mandate active, improve on-time payments."

        try:
            supa.table("chat_memory").insert({
                "session_id": sid, "role": "assistant", "content": reply, "created_at": datetime.datetime.utcnow().isoformat()
            }).execute()
        except Exception:
            pass
        return {"final_response": reply}

    # ============================================================
    # 2. DAILY SAVINGS PLANNER (NEW ADDITION)
    # ============================================================
    if intent == "savings_plan":
        mid = sid
        avg_daily = 0
        
        # Fetch Sales Data from Supabase Transactions table
        try:
            txns = supa.table("transactions").select("*").eq("merchant_id", mid).order("date", desc=True).limit(30).execute().data
            if txns:
                # Robustly sum up sales handling string/float differences
                total = sum(float(str(t.get("gross_sales", 0)).replace(",","")) for t in txns)
                avg_daily = total / max(1, len(txns))
            else:
                avg_daily = 0
        except:
            avg_daily = 0

        # Logic: ClickPe recommends saving 20% of daily sales for EMI
        if avg_daily > 0:
            target_save = int(avg_daily * 0.20)
            
            reply = (
                f"📅 **Daily Savings Plan**\n\n"
                f"Based on your CSV upload, your Average Daily Sale is ₹**{avg_daily:.0f}**.\n\n"
                f"To afford a standard ClickPe loan, you should set aside **₹{target_save} today** (approx 20%).\n\n"
                f"*Tip: Keep this amount in your wallet now to ensure easy repayment!*"
            )
        else:
            reply = "I don't see any sales data yet. Please **Upload your CSV** first so I can calculate your daily savings target."

        # Persist reply
        try:
            supa.table("chat_memory").insert({
                "session_id": sid, "role": "assistant", "content": reply, "created_at": datetime.datetime.utcnow().isoformat()
            }).execute()
        except Exception:
            pass
        return {"final_response": reply}

    # ============================================================
    # 3. NON-LOAN FLOW: LLM or FALLBACK (Unchanged)
    # ============================================================
    ctx = state.get("context","")

    system = SystemMessage(content=(
        "You are ClickPe assistant. NEVER approve loans. Use the provided CONTEXT. Keep answer short (<=60 words). Cite logs/policy snippets when used."
    ))
    human = HumanMessage(content=f"Context:\n{ctx}\n\nUser: {user_q}\n\nAnswer succinctly and include next action.")

    # If LLM usage disabled, skip remote call and use fallback
    if not globals().get("USE_LLM", True):
        # simple rule-based fallback using context
        fallback_text = simple_fallback_reply(user_q, ctx)
        persist_reply_safe(sid, fallback_text)
        return {"final_response": fallback_text}

    # Try LLM with retry/backoff (handles 429)
    max_retries = 3
    delay = 1.0
    llm_text = None
    for attempt in range(max_retries):
        try:
            resp = llm.invoke([system, human])
            llm_text = getattr(resp, "content", None) or getattr(resp, "text", None) or str(resp)
            break
        except Exception as e:
            # If quota / 429 from Google, wait and retry with backoff
            logging.exception(f"LLM invoke attempt {attempt+1} failed")
            time.sleep(delay)
            delay *= 2
    if not llm_text:
        # LLM failed repeatedly → fallback
        fallback_text = simple_fallback_reply(user_q, ctx)
        persist_reply_safe(sid, fallback_text)
        return {"final_response": fallback_text}

    # Persist LLM reply
    try:
        supa.table("chat_memory").insert({
            "session_id": sid, "role": "assistant", "content": llm_text, "created_at": datetime.datetime.utcnow().isoformat()
        }).execute()
    except Exception:
        logging.exception("Failed to persist LLM reply")

    return {"final_response": llm_text}
# --- helper utilities used by generator_node ---
def simple_fallback_reply(user_q: str, ctx: str) -> str:
    """
    Small rule-based summarizer used when LLM is unavailable.
    It handles:
      - failed debit queries (search for 'FAILED' / 'insufficient' in ctx)
      - short-summaries: returns avg lines of context
      - otherwise ask for missing data
    """
    q = user_q.lower()
    # if user asks about failure, try extract reason from ctx
    if any(k in q for k in ["failed", "why debit", "why did my debit", "insufficient", "failed_debit", "deducted"]):
        # look for common tokens in ctx
        lowered = ctx.lower()
        if "insufficient" in lowered or "insufficient_balance" in lowered:
            return "Failure likely: insufficient wallet balance at debit time. Action: ask merchant to top-up and retry."
        if "mandate_expired" in lowered or "mandate expired" in lowered:
            return "Failure due to expired mandate. Action: ask merchant to re-authorize the mandate."
        # fallback generic
        snippet = (ctx[:300] + "...") if ctx else ""
        return "Couldn't access AI right now. From logs/context: " + snippet + " Please provide merchant ID or upload recent CSV for deeper check."
    # if user asks simple policy/cashflow questions, compute simple guidance
    if any(k in q for k in ["save", "how much", "today", "save today"]):
        # try to parse avg_daily from ctx (if present)
        m = re.search(r"avg[:=]?\s*?(\d+\.?\d*)", ctx.lower())
        avg = float(m.group(1)) if m else None
        if avg:
            est = int(max(1, round(avg * 0.2)))
            return f"Quick suggestion: Save approx ₹{est}/day (≈20% of avg daily sales). For precise plan, upload CSV."
        return "I need your recent sales CSV to compute exact daily saving. Please upload the CSV."
    # default fallback
    snippet = (ctx[:400] + "...") if ctx else ""
    return "Temporary fallback: AI unavailable. Context: " + snippet + " Please try again or upload data."

def persist_reply_safe(session_id: str, text: str):
    try:
        supa.table("chat_memory").insert({
            "session_id": session_id, "role": "assistant", "content": text, "created_at": datetime.datetime.utcnow().isoformat()
        }).execute()
    except Exception:
        logging.exception("Failed to persist fallback reply")


# build graph
workflow = StateGraph(AgentState)
workflow.add_node("router", router_node)
workflow.add_node("db_tool", database_node)
workflow.add_node("rag_tool", policy_rag_node)
workflow.add_node("generator", generator_node)
workflow.set_entry_point("router")
workflow.add_conditional_edges("router", lambda x: "db_tool" if x["intent"]=="database" else ("rag_tool" if x["intent"]=="policy" else "generator"), {"db_tool":"db_tool","rag_tool":"rag_tool","generator":"generator"})
workflow.add_edge("db_tool","generator")
workflow.add_edge("rag_tool","generator")
workflow.add_edge("generator", END)
app_graph = workflow.compile()

def process_chat(session_id: str, message: str) -> str:
    inputs = {"session_id": session_id, "user_query": message}
    out = app_graph.invoke(inputs)
    if isinstance(out, dict):
        return out.get("final_response","Sorry.")
    return str(out)
