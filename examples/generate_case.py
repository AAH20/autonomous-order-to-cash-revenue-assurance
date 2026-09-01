from __future__ import annotations
import hashlib,json
from pathlib import Path

transactions=[];recovered={}
for i in range(10000):
    value=round(500+(i%40)*125.5,2);kind=i%100
    tx={"order_id":f"ORD-{i:06d}","customer_id":f"CUS-{i%800:05d}","currency":["USD","EUR","GBP"][i%3],"ordered_usd":value,"fulfilled_usd":value,"invoiced_usd":value,"paid_usd":value,"applied_usd":value,"ledger_usd":value,"expected_price_usd":value,"invoiced_price_usd":value,"order_accepted":True,"shipment_complete":True,"invoice_created":True,"payment_received":True,"dispute_open":False,"credit_hold":False,"age_days":i%61,"duplicate_invoice_count":0,"duplicate_payment_count":0}
    anomaly=None;exposure=0
    if kind==1:tx["invoice_created"]=False;tx["invoiced_usd"]=0;anomaly="shipped-not-invoiced";exposure=value
    elif kind==2:tx["applied_usd"]=0;anomaly="unapplied-cash";exposure=value
    elif kind==3:tx["invoiced_price_usd"]=round(value+75,2);anomaly="pricing-mismatch";exposure=75
    elif kind==4:tx["duplicate_invoice_count"]=1;anomaly="duplicate-invoice";exposure=value
    elif kind==5:tx["dispute_open"]=True;tx["paid_usd"]=0;tx["applied_usd"]=0;tx["ledger_usd"]=0;tx["age_days"]=45;anomaly="aged-dispute";exposure=value
    elif kind==6:tx["ledger_usd"]=0;anomaly="ledger-reconciliation-gap";exposure=value
    elif kind==7:tx["duplicate_payment_count"]=1;anomaly="duplicate-payment";exposure=value
    elif kind==8:tx["credit_hold"]=True;tx["age_days"]=10;anomaly="stale-credit-hold";exposure=value
    if anomaly and i%2==0:
        key=hashlib.sha256(f'{tx["order_id"]}:{anomaly}:{round(exposure,2)}'.encode()).hexdigest()[:24];recovered[key]=round(exposure*.8,2)
    transactions.append(tx)
case={"transactions":transactions,"verified_recovery":recovered,"platform_cost_usd":18500.0}
Path(__file__).with_name("synthetic-10000-orders.json").write_text(json.dumps(case,separators=(",",":"))+"\n",encoding="utf-8")

