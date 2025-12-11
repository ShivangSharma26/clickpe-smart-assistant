# make_sample_csv.py -> run once, it creates sample_data/sample_txn_merchant_1.csv
import csv, os, random, datetime
os.makedirs("sample_data", exist_ok=True)
fname = "sample_data/sample_txn_merchant_1.csv"
start = datetime.date.today() - datetime.timedelta(days=30)
with open(fname,"w",newline="") as f:
    w = csv.writer(f)
    w.writerow(["date","gross_sales","cash_in_hand"])
    for i in range(31):
        d = start + datetime.timedelta(days=i)
        sales = random.randint(800,2500)
        w.writerow([d.isoformat(), sales, int(sales*0.6)])
print("Created", fname)
