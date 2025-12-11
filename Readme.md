# 🚀 ClickPe Smart Assistant: AI Co-Pilot for FinTech Ops

A Production-Grade Hybrid AI System for Loan Underwriting, Daily Cashflow Planning, and Failure Forensics.

---

## 💡 The Inspiration & The Problem

ClickPe operates on a unique model: **"Daily Deductions" (EDI)**. Instead of one big monthly EMI, merchants pay a small amount daily.

### The Merchant's Problem
> "How much should I leave in my wallet today so my EMI doesn't bounce?"

### The Ops Team's Problem
> "Why did Transaction #TXN_998 failed? Was it insufficient funds? Or a server error?"

**ClickPe Smart Assistant** solves both. It is not just a chatbot; it is a **Full-Stack Financial Intelligence System** that reads real transaction logs, calculates loan eligibility using deterministic math, and helps merchants plan their savings.

---

## 🛠️ System Architecture (The "Hybrid" Approach)

Unlike basic wrappers around ChatGPT, this project uses a **Router-Based Architecture (LangGraph)**. It intelligently switches between **Deterministic Logic** (for Math/Money) and **Generative AI** (for explanations).

### Architecture Diagram

![System Architecture](https://app.eraser.io/workspace/2v0BXoqatrm7pU16EPeM/preview)

> 📊 [View Interactive Diagram on Eraser.io](https://app.eraser.io/workspace/2v0BXoqatrm7pU16EPeM?origin=share)


## ⚡ Key Innovations

- **Zero-Hallucination Math**: Loan eligibility is calculated via Python logic, not an LLM. (If sales are ₹0, the bot knows it's ₹0).
- **Persistent Memory**: Uses Supabase to store chat history. You can refresh the page, and the bot remembers context.
- **Real-Time RAG**: Queries live SQL logs to diagnose transaction failures instantly.

---

## ✨ Key Features

### 1. 💸 The "Daily Savings" Planner (Innovative Feature)

ClickPe merchants need to maintain a specific balance daily.

- **Logic**: The system fetches the merchant's last 30 days of sales from the `transactions` table.
- **Algorithm**: It calculates the Average Daily Sales and applies the **20% Rule** (A standard Fintech heuristic).
- **Output**: *"Your avg sale is ₹1,743. Please set aside ₹348 today to avoid a bounce."*

### 2. 🏦 Automated Loan Underwriting (Pre-Check)

Instead of asking 10 questions, the bot checks the database immediately.

**Input**: "I want a loan of 2 Lakhs."

**Process**:
- Checks `transactions` for revenue coverage.
- Checks `merchant_profiles` for Wallet Balance and Mandate Status.
- Checks `transaction_logs` for On-Time Repayment Rate.

**Result**: A strict **Eligible / Not Eligible** verdict based on data, not vibes.

### 3. 🕵️‍♂️ Ops Co-Pilot (The Detective)

For the internal Ops team.

**Query**: "Why did the last transaction fail?"

**Action**: The bot runs a SQL query on the `transaction_logs` table.

**Result**: *"Transaction failed due to insufficient_funds. Reason: Wallet balance was ₹20 vs EMI ₹300."*

---

## 🗄️ Database Schema (Supabase)

The project leverages a robust Relational Database (PostgreSQL) hosted on Supabase.

| Table Name | Purpose | Key Columns |
|------------|---------|-------------|
| `transactions` | Stores raw CSV data uploaded by merchants. Used for calculating Average Daily Sales. | `merchant_id`, `gross_sales`, `date` |
| `transaction_logs` | Stores system events. Used by Ops Co-Pilot to debug failures. | `status` (success/failed), `reason`, `type` |
| `merchant_profiles` | Stores KYC details. Used for eligibility checks. | `wallet_balance`, `mandate_status` (ACTIVE) |
| `chat_memory` | Stores conversation history for context awareness. | `session_id`, `role`, `content` |

---

## ⚙️ Tech Stack

- **Brain**: 🐍 Python (FastAPI) + 🦜⛓️ LangGraph (State Orchestration)
- **Database**: ⚡ Supabase (PostgreSQL + pgvector)
- **Frontend**: 🎨 HTML5 + TailwindCSS (Dark Mode enabled)
- **AI Model**: Google Gemini 1.5 Flash (via LangChain)
- **Data Processing**: Pandas (for CSV analysis)

---

## 🚀 How to Run Locally

### 1. Clone the Repo

```bash
git clone https://github.com/yourusername/clickpe-smart-assistant.git
cd clickpe-smart-assistant
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Environment Variables

Create a `.env` file and add your credentials:

```env
SUPABASE_URL="your_supabase_url"
SUPABASE_KEY="your_supabase_anon_key"
GOOGLE_API_KEY="your_gemini_key"
USE_LLM="1"
```

### 4. Run the Server

```bash
uvicorn main:app --reload
```

### 5. Access the App

Open `http://localhost:8000` in your browser.

---

## 🧪 Testing the Flow (Demo Script)

1. **Upload Data**: Upload the provided `sample_txn_merchant_1.csv`.
   - **Observation**: Toast notification confirms "Avg Daily Sales: ₹1,595".

2. **Ask for Savings Plan**: Type "How much should I save today?"
   - **Observation**: Bot suggests saving ~₹320 (20%) based on the uploaded CSV.

3. **Request Loan**: Type "I want a loan of 50,000 for 6 months."
   - **Observation**: Bot checks Database, calculates EMI vs Income, and returns "Eligible/Not Eligible" with reasons.

4. **Ops Debugging**: Type "Why did the last transaction fail?"
   - **Observation**: Bot fetches the specific error log from Supabase (`insufficient_funds`).

---

## 🔮 Future Roadmap

- **WhatsApp Integration**: Deploy this logic on WhatsApp API for real-time merchant alerts.
- **Predictive AI**: Use Time-Series forecasting to predict next month's sales instead of just averaging.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

This project is licensed under the MIT License.

---

**Built with ❤️ for the ClickPe Engineering Assignment.**