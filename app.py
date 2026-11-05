"""Monitor de moedas Solana: atualiza a cada 60s e serve um painel web (Flask)."""
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template

TOKENS = [
    {"name": "Goatseus Maximus", "mint": "CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump"},
    {"name": "Peanut the Squirrel", "mint": "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump"},
    {"name": "Moo Deng", "mint": "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY"},
]

RPC_URL = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
INTERVAL = int(os.getenv("INTERVAL_SECONDS", "60"))
HEADERS = {"User-Agent": "solana-monitor/1.0"}

app = Flask(__name__)
lock = threading.Lock()
state = {"updated_at": None, "ranking": [], "tokens": {}, "history": deque(maxlen=60)}
creator_cache = {}


def rpc(method, params):
    r = requests.post(
        RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


def get_market(mint):
    """DexScreener: pega o par com maior liquidez e estima volume de compra."""
    r = requests.get(
        f"https://api.dexscreener.com/latest/dex/tokens/{mint}", headers=HEADERS, timeout=20
    )
    r.raise_for_status()
    pairs = [p for p in (r.json().get("pairs") or []) if p.get("chainId") == "solana"]
    if not pairs:
        return None
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
    tx5 = (p.get("txns") or {}).get("m5") or {}
    buys, sells = tx5.get("buys", 0), tx5.get("sells", 0)
    vol5 = (p.get("volume") or {}).get("m5") or 0
    share = buys / (buys + sells) if (buys + sells) else 0
    return {
        "pair": p.get("pairAddress"),
        "price_usd": p.get("priceUsd"),
        "buys_5m": buys,
        "sells_5m": sells,
        "volume_5m": vol5,
        "volume_1h": (p.get("volume") or {}).get("h1") or 0,
        # estimativa: volume total x proporção de transações de compra
        "buy_volume_5m_est": round(vol5 * share, 2),
        "liquidity_usd": (p.get("liquidity") or {}).get("usd") or 0,
        "dextools": f"https://www.dextools.io/app/solana/pair-explorer/{p.get('pairAddress')}",
    }


def get_top_holders(mint, limit=5):
    supply = float(rpc("getTokenSupply", [mint])["value"]["uiAmount"] or 0)
    accounts = rpc("getTokenLargestAccounts", [mint])["value"][:limit]
    infos = rpc(
        "getMultipleAccounts",
        [[a["address"] for a in accounts], {"encoding": "jsonParsed"}],
    )["value"]
    holders = []
    for acc, info in zip(accounts, infos):
        owner = None
        try:
            owner = info["data"]["parsed"]["info"]["owner"]
        except Exception:
            pass
        amount = float(acc.get("uiAmount") or 0)
        holders.append(
            {
                "token_account": acc["address"],
                "owner": owner,
                "amount": amount,
                "percent": round(amount / supply * 100, 2) if supply else None,
                "solscan": f"https://solscan.io/account/{owner}" if owner else None,
            }
        )
    return holders


def get_creator(mint):
    """Carteira criadora + outras moedas criadas por ela (pump.fun). Cacheado."""
    if mint in creator_cache:
        return creator_cache[mint]
    result = {"creator": None, "source": None, "created_coins": []}
    try:
        r = requests.get(f"https://frontend-api-v3.pump.fun/coins/{mint}", headers=HEADERS, timeout=20)
        if r.ok and r.json().get("creator"):
            creator = r.json()["creator"]
            result.update(creator=creator, source="pump.fun")
            r2 = requests.get(
                f"https://frontend-api-v3.pump.fun/coins/user-created-coins/{creator}",
                params={"offset": 0, "limit": 50, "includeNsfw": "false"},
                headers=HEADERS,
                timeout=20,
            )
            if r2.ok:
                items = r2.json()
                items = items if isinstance(items, list) else items.get("coins", [])
                result["created_coins"] = [
                    {"name": c.get("name"), "symbol": c.get("symbol"), "mint": c.get("mint")}
                    for c in items
                ]
    except Exception as e:
        result["error"] = str(e)
    if not result["creator"]:
        # fallback: autoridade de mint (nem sempre é o criador)
        try:
            info = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
            auth = info["data"]["parsed"]["info"].get("mintAuthority")
            if auth:
                result.update(creator=auth, source="mint authority (aproximação)")
        except Exception as e:
            result["error"] = str(e)
    if result["creator"]:
        result["solscan"] = f"https://solscan.io/account/{result['creator']}"
        creator_cache[mint] = result
    return result


def refresh():
    tokens, ranking = {}, []
    for t in TOKENS:
        entry = {"name": t["name"], "mint": t["mint"], "solscan": f"https://solscan.io/token/{t['mint']}"}
        for key, fn in (("market", get_market), ("holders", get_top_holders), ("creator", get_creator)):
            try:
                entry[key] = fn(t["mint"])
            except Exception as e:
                entry[key] = None
                entry.setdefault("errors", []).append(f"{key}: {e}")
        tokens[t["mint"]] = entry
        m = entry.get("market") or {}
        ranking.append(
            {
                "name": t["name"],
                "mint": t["mint"],
                "buy_volume_5m_est": m.get("buy_volume_5m_est", 0),
                "buys_5m": m.get("buys_5m", 0),
            }
        )
    ranking.sort(key=lambda x: x["buy_volume_5m_est"], reverse=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with lock:
        state.update(updated_at=now, ranking=ranking, tokens=tokens)
        state["history"].appendleft({"at": now, "top": ranking[0]["name"] if ranking else None, "ranking": ranking})


def loop():
    while True:
        try:
            refresh()
        except Exception as e:
            print("erro no ciclo:", e)
        time.sleep(INTERVAL)


@app.route("/")
def index():
    return render_template("index.html", interval=INTERVAL)


@app.route("/api/data")
def api_data():
    with lock:
        return jsonify(
            updated_at=state["updated_at"],
            ranking=state["ranking"],
            tokens=list(state["tokens"].values()),
            history=list(state["history"]),
        )


_started = False


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=loop, daemon=True).start()


start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
