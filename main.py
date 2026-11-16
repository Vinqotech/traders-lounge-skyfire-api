import os, requests, jwt
from jwt import PyJWKClient
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf

app = FastAPI(
    title="Traders Lounge Quantitative Market & Alpha API",
    description="Enterprise M2M Financial Intelligence API providing real-time 1Y & 5Y quantitative backtests, $10,000 compound return simulations, max peak-to-trough drawdown risk metrics, live watchlist pulse, and breaking market catalysts for AI trading agents.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SKYFIRE_API_KEY = os.environ.get("SKYFIRE_SELLER_API_KEY", "")
SKYFIRE_JWKS_URL = "https://skyfire.xyz"
jwks_client = PyJWKClient(SKYFIRE_JWKS_URL)

WATCHLIST = [
    ("BTC-USD", "BTC"), ("ETH-USD", "ETH"), ("SOL-USD", "SOL"),
    ("^GSPC", "S&P 500"), ("QQQ", "NASDAQ"), ("GC=F", "GOLD"),
    ("NVDA", "NVDA"), ("TSLA", "TSLA")
]


def verify_and_charge_skyfire(skyfire_pay_id: str | None):
    if not skyfire_pay_id:
        raise HTTPException(
            status_code=402,
            detail="Payment Required: Include a valid 'skyfire-pay-id' token header from Skyfire."
        )
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(skyfire_pay_id)
        claims = jwt.decode(
            skyfire_pay_id,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            options={"verify_aud": False}
        )
        if SKYFIRE_API_KEY:
            charge_res = requests.post(
                "https://skyfire.xyz",
                headers={
                    "skyfire-api-key": SKYFIRE_API_KEY,
                    "Content-Type": "application/json"
                },
                json={"token": skyfire_pay_id, "chargeAmount": "0.01"},
                timeout=10
            )
            if not charge_res.ok:
                raise HTTPException(status_code=402, detail=f"Skyfire charge failed: {charge_res.text}")
        return claims
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Skyfire PAY token: {str(e)}")


def analyze_asset(symbol: str):
    def get_closes(period: str):
        s = yf.Ticker(symbol).history(period=period).get("Close")
        vals = [round(float(x), 4) for x in s.dropna().tolist()] if s is not None else []
        if len(vals) < 2:
            raise HTTPException(status_code=400, detail=f"Insufficient historical market data for symbol '{symbol}'.")
        return vals

    c1y = get_closes("1y")
    c5y = get_closes("5y")

    ret_1y = round(((c1y[-1] / c1y) - 1) * 100, 2)
    ret_5y = round(((c5y[-1] / c5y) - 1) * 100, 2)

    peak, worst_dd = c5y, 0.0
    for price in c5y:
        if price > peak:
            peak = price
        dd = (price / peak) - 1
        if dd < worst_dd:
            worst_dd = dd

    headlines = []
    try:
        for item in (yf.Ticker(symbol).news or [])[:3]:
            title = item.get("title") or (item.get("content") or {}).get("title")
            if title:
                headlines.append(title)
    except Exception:
        pass

    return {
        "symbol": symbol.upper(),
        "current_price": round(c5y[-1], 2),
        "return_1y_pct": ret_1y,
        "hypothetical_10k_1y_usd": round(10000 * (1 + ret_1y / 100), 2),
        "return_5y_pct": ret_5y,
        "hypothetical_10k_5y_usd": round(10000 * (1 + ret_5y / 100), 2),
        "max_drawdown_5y_pct": round(worst_dd * 100, 2),
        "latest_headlines": headlines
    }


@app.get("/")
def health_check():
    return {
        "service": "Traders Lounge Quantitative Market & Alpha API",
        "status": "online",
        "openapi_spec": "/openapi.json",
        "endpoints": ["/v1/quant-compare", "/v1/market-pulse"]
    }


@app.get("/v1/quant-compare")
def quant_compare(
    t1: str = Query("BTC-USD", description="Primary Yahoo Finance ticker symbol (e.g. NVDA, BTC-USD, AAPL)"),
    t2: str = Query("^GSPC", description="Benchmark or comparison ticker symbol (e.g. ^GSPC, ETH-USD, GOLD)"),
    skyfire_pay_id: str | None = Header(None, alias="skyfire-pay-id")
):
    claims = verify_and_charge_skyfire(skyfire_pay_id)
    a1 = analyze_asset(t1)
    a2 = analyze_asset(t2)
    growth_leader = a1["symbol"] if a1["return_5y_pct"] > a2["return_5y_pct"] else a2["symbol"]
    stability_leader = a1["symbol"] if a1["max_drawdown_5y_pct"] > a2["max_drawdown_5y_pct"] else a2["symbol"]

    return {
        "provider": "Traders Lounge Quant Desk",
        "buyer_id": claims.get("sub", "verified-agent"),
        "asset_1": a1,
        "asset_2": a2,
        "quantitative_verdict": {
            "growth_leader_5y": growth_leader,
            "stability_leader_5y": stability_leader,
            "return_spread_5y_pct": round(a1["return_5y_pct"] - a2["return_5y_pct"], 2)
        }
    }


@app.get("/v1/market-pulse")
def market_pulse(skyfire_pay_id: str | None = Header(None, alias="skyfire-pay-id")):
    claims = verify_and_charge_skyfire(skyfire_pay_id)
    pulse = []
    for sym, label in WATCHLIST:
        try:
            closes = yf.Ticker(sym).history(period="5d").get("Close").dropna().tolist()
            cur = float(closes[-1])
            prev = float(closes[-2]) if len(closes) > 1 else cur
            pulse.append({
                "asset": label,
                "symbol": sym,
                "price": round(cur, 2),
                "change_24h_pct": round(((cur / prev) - 1) * 100, 2)
            })
        except Exception:
            pass
    return {
        "provider": "Traders Lounge Quant Desk",
        "buyer_id": claims.get("sub", "verified-agent"),
        "watchlist": pulse
    }
