"""Local, deterministic read-only sources. No credentials or external services."""

import asyncio
import hashlib

from fastapi import FastAPI, Header
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Rowstead demo sources")


async def seeded_failure(identifier, attempt):
    name = identifier.upper()
    if name == "TIMEOUT":
        await asyncio.sleep(20)
    status = {"MISSING": 404, "LOGIN": 401, "BLOCKED": 403, "ALWAYS-ERROR": 500}.get(name)
    if name == "RATE-ONCE" and attempt <= 1:
        status = 429
    if name == "ERROR-ONCE" and attempt <= 1:
        status = 500
    if status:
        return JSONResponse(
            {"message": "Seeded demo failure", "status": status},
            status_code=status,
            headers={"Retry-After": "1"} if status == 429 else {},
        )
    return None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/registry/{identifier}")
async def registry(identifier: str, x_batchflow_attempt: int = Header(default=1)):
    failure = await seeded_failure(identifier, x_batchflow_attempt)
    if failure is not None:
        return failure
    seed = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16)
    return {
        "identifier": identifier,
        "company_name": f"Example Company {identifier}",
        "country": ["Poland", "Germany", "United Kingdom", "United States"][seed % 4],
        "industry": ["Software", "Manufacturing", "Retail", "Logistics"][seed % 4],
        "employees": 5 + seed % 995,
        "active": seed % 7 != 0,
        "risk_score": seed % 101,
    }


@app.get("/calculator", response_class=HTMLResponse)
async def calculator(identifier: str = "BF-0001", attempt: int = 1):
    failure = await seeded_failure(identifier, attempt)
    if failure is not None:
        return failure
    return HTMLResponse(CALCULATOR)


CALCULATOR = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rowstead Demo Calculator</title>
<style>body{font:17px system-ui;max-width:650px;margin:60px auto;padding:24px;background:#f3f5fa;color:#152137}label{display:block;margin:18px 0}input{display:block;width:95%;padding:10px;margin-top:7px}button{background:#355ce4;color:white;border:0;padding:14px 22px;border-radius:6px}dl{display:grid;grid-template-columns:1fr 1fr;gap:12px;background:white;padding:24px}dd{margin:0;text-align:right}</style>
<h1>Demo order calculator</h1><p>A controlled source for Rowstead. Results use a fixed tax rate of 20%.</p>
<form id="form"><label>Identifier<input id="identifier" required></label><label>Quantity<input id="quantity" type="number" value="1" min="1" step="any"></label><label>Unit price<input id="unit_price" type="number" value="10" min="0" step="any"></label><label>Discount (%)<input id="discount" type="number" value="0" min="0" max="100" step="any"></label><button id="calculate">Calculate</button></form>
<dl id="results" data-ready="false" hidden></dl>
<script>document.querySelector('#form').addEventListener('submit',event=>{event.preventDefault();const get=id=>document.getElementById(id).value;const q=Number(get('quantity')),p=Number(get('unit_price')),d=Number(get('discount'));const subtotal=Math.round(q*p*100)/100,discount=Math.round(subtotal*d)/100,tax=Math.round((subtotal-discount)*20)/100;const values={identifier:get('identifier'),quantity:String(q),unit_price:p.toFixed(2),subtotal:subtotal.toFixed(2),discount_amount:discount.toFixed(2),tax:tax.toFixed(2),total:(subtotal-discount+tax).toFixed(2)};const results=document.querySelector('#results');results.replaceChildren();for(const [key,value] of Object.entries(values)){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key.replaceAll('_',' ');dd.dataset.result=key;dd.textContent=value;results.append(dt,dd)}results.hidden=false;results.dataset.ready='true'});</script></html>"""
