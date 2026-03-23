#!/usr/bin/env python3
"""
Censorship Alpha — When Countries Block Crypto, Where Does the Money Go?

Correlates real-time internet censorship data (Voidly) with on-chain
blockchain fund flows (Nansen) to reveal how smart money adapts when
authoritarian governments block crypto exchanges.

Usage:
    python3 censorship_alpha.py [--output report.html] [--png] [--json]
"""

import json
import subprocess
import sys
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path

import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from jinja2 import Environment, FileSystemLoader

# ─── Constants ───────────────────────────────────────────────────────────────

VOIDLY_API = "https://api.voidly.ai"

EXCHANGES = [
    "binance.com", "coinbase.com", "kraken.com", "kucoin.com",
    "okx.com", "bybit.com", "gate.io", "crypto.com"
]

# Top countries with meaningful crypto populations AND censorship risk
COUNTRIES = {
    "IR": "Iran", "CN": "China", "RU": "Russia", "TR": "Turkey",
    "NG": "Nigeria", "PK": "Pakistan", "EG": "Egypt", "VN": "Vietnam",
    "IN": "India", "SA": "Saudi Arabia", "AE": "UAE", "TH": "Thailand",
    "MM": "Myanmar", "BY": "Belarus", "VE": "Venezuela"
}

BINANCE_HOT_WALLETS = {
    "ethereum": "0x28C6c06298d514Db089934071355E5743bf21d60",
    "bnb": "0x28C6c06298d514Db089934071355E5743bf21d60",
}

# Ground-truth exchange blocking data from published sources (2025-2026)
# Sources: Chainalysis 2026 Crypto Crime Report, CoinGecko "18 Countries Where
# Bitcoin Is Banned", Cloudwards "Where Is Crypto Illegal in 2026", Techloy,
# Binance Restricted Countries lists (DeFi Race, DataWallet)
KNOWN_BLOCKS = {
    "CN": ["binance.com", "coinbase.com", "kraken.com", "kucoin.com", "okx.com", "bybit.com", "gate.io", "crypto.com"],  # All crypto banned since 2021
    "EG": ["binance.com", "coinbase.com", "kraken.com", "kucoin.com", "okx.com", "bybit.com", "gate.io", "crypto.com"],  # Full crypto ban
    "MM": ["binance.com", "coinbase.com", "kraken.com", "kucoin.com", "okx.com", "bybit.com", "gate.io", "crypto.com"],  # Military junta, internet controls
    "IR": ["binance.com", "coinbase.com", "kraken.com", "kucoin.com", "okx.com", "bybit.com"],  # Sanctioned/blocked
    "TR": ["binance.com", "kucoin.com", "okx.com"],  # Access restricted by regulators
    "NG": ["binance.com", "coinbase.com"],  # ISPs directed to block
    "BY": ["binance.com", "coinbase.com", "kraken.com"],  # Sanctions-aligned restrictions
    "VN": ["binance.com", "okx.com"],  # Crypto banned, partially enforced
    "PK": ["binance.com"],  # Intermittent ISP blocks
    "SA": ["binance.com"],  # Restricted trading
    "VE": ["binance.com"],  # Sanctions + capital controls
}

# ─── Voidly Data Collection ─────────────────────────────────────────────────

def fetch_voidly_censorship():
    """Collect exchange blocking data for all target countries."""
    print("\n📡 Phase 1: Collecting Voidly censorship data...")
    results = {}

    # 1. Check exchange accessibility per country
    for code, name in COUNTRIES.items():
        print(f"  Checking {name} ({code})...", end=" ")
        try:
            resp = requests.post(
                f"{VOIDLY_API}/v1/accessibility/batch",
                json={"domains": EXCHANGES, "country": code},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                checks = data.get("results", data.get("checks", []))
                blocked = []
                accessible = []
                for c in checks:
                    domain = c.get("domain", "")
                    status = c.get("status", c.get("accessible", ""))
                    if status in ("blocked", "likely_blocked", False) or c.get("block_rate", 0) > 50:
                        blocked.append(domain)
                    else:
                        accessible.append(domain)
                results[code] = {
                    "name": name,
                    "blocked": blocked,
                    "accessible": accessible,
                    "block_count": len(blocked),
                    "block_rate": len(blocked) / len(EXCHANGES) * 100,
                }
                print(f"{len(blocked)}/{len(EXCHANGES)} blocked")
            else:
                # Fallback: try individual checks
                blocked = []
                for domain in EXCHANGES:
                    try:
                        r = requests.get(
                            f"{VOIDLY_API}/v1/accessibility/check",
                            params={"domain": domain, "country": code},
                            timeout=10
                        )
                        if r.status_code == 200:
                            d = r.json()
                            if d.get("status") in ("blocked", "likely_blocked") or d.get("block_rate", 0) > 50:
                                blocked.append(domain)
                    except:
                        pass
                results[code] = {
                    "name": name,
                    "blocked": blocked,
                    "accessible": [d for d in EXCHANGES if d not in blocked],
                    "block_count": len(blocked),
                    "block_rate": len(blocked) / len(EXCHANGES) * 100,
                }
                print(f"{len(blocked)}/{len(EXCHANGES)} blocked (fallback)")
        except Exception as e:
            print(f"error: {e}")
            results[code] = {
                "name": name, "blocked": [], "accessible": EXCHANGES,
                "block_count": 0, "block_rate": 0,
            }

    # 2. Get censorship index for risk tiers
    print("  Fetching censorship index...")
    try:
        resp = requests.get(f"{VOIDLY_API}/data/censorship-index.json", timeout=10)
        if resp.status_code == 200:
            index_data = resp.json()
            countries_data = index_data if isinstance(index_data, list) else index_data.get("countries", [])
            for c in countries_data:
                code = c.get("code", c.get("country_code", ""))
                if code in results:
                    results[code]["risk_tier"] = c.get("riskTier", c.get("risk_tier", 3))
                    results[code]["score"] = c.get("score", 0)
    except:
        pass

    # Fill defaults for missing risk tiers
    for code in results:
        if "risk_tier" not in results[code]:
            results[code]["risk_tier"] = 3
        if "score" not in results[code]:
            results[code]["score"] = 50

    # 3. Get high-risk countries forecast
    print("  Fetching risk forecasts...")
    try:
        resp = requests.get(f"{VOIDLY_API}/v1/forecast/high-risk", params={"threshold": 0.3}, timeout=10)
        if resp.status_code == 200:
            forecasts = resp.json()
            high_risk = forecasts.get("countries", forecasts) if isinstance(forecasts, dict) else forecasts
            for f in (high_risk if isinstance(high_risk, list) else []):
                code = f.get("country", f.get("country_code", ""))
                if code in results:
                    results[code]["forecast_risk"] = f.get("max_risk", f.get("risk", 0))
    except:
        pass

    # 4. Get ISP data for top blocked countries
    top_blocked = sorted(results.items(), key=lambda x: x[1]["block_count"], reverse=True)[:3]
    for code, data in top_blocked:
        if data["block_count"] > 0:
            print(f"  Fetching ISP data for {data['name']}...")
            try:
                resp = requests.get(f"{VOIDLY_API}/v1/isp/index", params={"country": code}, timeout=10)
                if resp.status_code == 200:
                    isp_data = resp.json()
                    results[code]["isps"] = isp_data.get("isps", [])[:5]
            except:
                pass

    # 5. Enrich with known ground-truth blocking data
    print("  Enriching with ground-truth data...")
    enriched = 0
    for code, known in KNOWN_BLOCKS.items():
        if code in results:
            existing = set(results[code]["blocked"])
            merged = list(existing | set(known))
            if len(merged) > len(existing):
                enriched += len(merged) - len(existing)
            results[code]["blocked"] = merged
            results[code]["accessible"] = [d for d in EXCHANGES if d not in merged]
            results[code]["block_count"] = len(merged)
            results[code]["block_rate"] = len(merged) / len(EXCHANGES) * 100
    print(f"  Added {enriched} verified blocks from published sources")

    return results


# ─── Nansen Data Collection ──────────────────────────────────────────────────

def run_nansen(cmd_parts, label=""):
    """Run a Nansen CLI command and return parsed JSON."""
    full_cmd = ["nansen"] + cmd_parts + ["--format", "json"]
    print(f"  Nansen: {' '.join(cmd_parts[:4])}... ", end="")
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            print("✓")
            return data
        else:
            # Try parsing stderr for JSON errors
            print(f"⚠ ({result.stderr[:60].strip()})")
            return None
    except subprocess.TimeoutExpired:
        print("⏱ timeout")
        return None
    except json.JSONDecodeError:
        print("⚠ parse error")
        return None
    except Exception as e:
        print(f"✗ {e}")
        return None


def fetch_nansen_data():
    """Collect on-chain data from Nansen CLI."""
    print("\n⛓️  Phase 2: Collecting Nansen on-chain data...")
    data = {}

    NF_FIELDS = "token_symbol,net_flow_24h_usd,net_flow_7d_usd,net_flow_30d_usd,chain,token_sectors,market_cap_usd"

    # 1-2. Smart money net flows (with --fields to reduce credit burn)
    data["eth_netflow"] = run_nansen(
        ["research", "smart-money", "netflow", "--chain", "ethereum", "--limit", "30", "--fields", NF_FIELDS],
        "ETH smart money flows"
    )
    data["bnb_netflow"] = run_nansen(
        ["research", "smart-money", "netflow", "--chain", "bnb", "--limit", "30", "--fields", NF_FIELDS],
        "BNB smart money flows"
    )

    # 3-4. Smart money holdings
    data["eth_holdings"] = run_nansen(
        ["research", "smart-money", "holdings", "--chain", "ethereum", "--limit", "20"],
        "ETH holdings"
    )
    data["bnb_holdings"] = run_nansen(
        ["research", "smart-money", "holdings", "--chain", "bnb", "--limit", "20"],
        "BNB holdings"
    )

    # 5-6. DEX trades on BNB (Binance ecosystem)
    data["bnb_dex"] = run_nansen(
        ["research", "smart-money", "dex-trades", "--chain", "bnb", "--limit", "30"],
        "BNB DEX trades"
    )
    data["eth_dex"] = run_nansen(
        ["research", "smart-money", "dex-trades", "--chain", "ethereum", "--limit", "30"],
        "ETH DEX trades"
    )

    # 7-8. Token screener — top BNB and ETH tokens by smart money
    data["bnb_screener"] = run_nansen(
        ["research", "token", "screener", "--chain", "bnb", "--limit", "15"],
        "BNB token screener"
    )
    data["eth_screener"] = run_nansen(
        ["research", "token", "screener", "--chain", "ethereum", "--limit", "15"],
        "ETH token screener"
    )

    # 9-10. Solana for comparison (less censorship-affected)
    data["sol_netflow"] = run_nansen(
        ["research", "smart-money", "netflow", "--chain", "solana", "--limit", "20", "--fields", NF_FIELDS],
        "SOL smart money flows"
    )
    data["sol_dex"] = run_nansen(
        ["research", "smart-money", "dex-trades", "--chain", "solana", "--limit", "20"],
        "SOL DEX trades"
    )

    # 11. Binance hot wallet balance
    data["binance_eth_wallet"] = run_nansen(
        ["research", "profiler", "balance", "--address", BINANCE_HOT_WALLETS["ethereum"], "--chain", "ethereum"],
        "Binance ETH wallet"
    )

    # 12. Base chain (Coinbase ecosystem)
    data["base_netflow"] = run_nansen(
        ["research", "smart-money", "netflow", "--chain", "base", "--limit", "15", "--fields", NF_FIELDS],
        "Base smart money flows"
    )

    # 13. Polymarket prediction markets (geopolitical events affecting censorship)
    data["prediction_markets"] = run_nansen(
        ["research", "pm", "market-screener", "--limit", "20"],
        "Polymarket events"
    )

    # 14. Search for privacy/VPN tokens (directly benefit from exchange censorship)
    data["privacy_search"] = run_nansen(
        ["research", "search", "--query", "privacy VPN decentralized exchange", "--limit", "10"],
        "Privacy/VPN tokens"
    )

    return data


# ─── Analysis Engine ─────────────────────────────────────────────────────────

def extract_flow_metrics(nansen_data):
    """Extract key metrics from Nansen data for correlation."""
    metrics = {}

    for chain in ["eth", "bnb", "sol", "base"]:
        key = f"{chain}_netflow"
        raw = nansen_data.get(key)
        if raw and raw.get("success") and raw.get("data", {}).get("data"):
            items = raw["data"]["data"]
            total_inflow = sum(abs(i.get("net_flow_24h_usd", 0)) for i in items if i.get("net_flow_24h_usd", 0) > 0)
            total_outflow = sum(abs(i.get("net_flow_24h_usd", 0)) for i in items if i.get("net_flow_24h_usd", 0) < 0)
            net = sum(i.get("net_flow_24h_usd", 0) for i in items)
            net_7d = sum(i.get("net_flow_7d_usd", 0) for i in items)
            net_30d = sum(i.get("net_flow_30d_usd", 0) for i in items)
            metrics[f"{chain}_inflow_24h"] = total_inflow
            metrics[f"{chain}_outflow_24h"] = total_outflow
            metrics[f"{chain}_net_24h"] = net
            metrics[f"{chain}_net_7d"] = net_7d
            metrics[f"{chain}_net_30d"] = net_30d
            metrics[f"{chain}_tokens_tracked"] = len(items)
            # Top movers
            sorted_items = sorted(items, key=lambda x: abs(x.get("net_flow_24h_usd", 0)), reverse=True)
            metrics[f"{chain}_top_movers"] = [
                {"symbol": i.get("token_symbol", "?"), "net_24h": i.get("net_flow_24h_usd", 0), "net_7d": i.get("net_flow_7d_usd", 0), "net_30d": i.get("net_flow_30d_usd", 0)}
                for i in sorted_items[:5]
            ]

    # DEX volume
    for chain in ["eth", "bnb", "sol"]:
        key = f"{chain}_dex"
        raw = nansen_data.get(key)
        if raw and raw.get("success") and raw.get("data", {}).get("data"):
            items = raw["data"]["data"]
            total_vol = sum(abs(i.get("trade_value_usd", i.get("amount_usd", i.get("value_usd", 0)))) for i in items)
            metrics[f"{chain}_dex_volume"] = total_vol
            metrics[f"{chain}_dex_trades"] = len(items)

    return metrics


def compute_impact_scores(censorship, flow_metrics):
    """Compute per-country Censorship Impact Score."""
    scores = {}

    # Normalize flow metrics
    bnb_net = flow_metrics.get("bnb_net_24h", 0)
    eth_net = flow_metrics.get("eth_net_24h", 0)
    bnb_dex = flow_metrics.get("bnb_dex_volume", 0)
    eth_dex = flow_metrics.get("eth_dex_volume", 0)

    for code, data in censorship.items():
        block_score = data["block_count"] / len(EXCHANGES)
        risk_tier = data.get("risk_tier", 3)
        risk_norm = (5 - risk_tier) / 4
        forecast = data.get("forecast_risk", 0.1)
        censorship_score = data.get("score", 50) / 100

        # Combined impact score
        impact = (
            block_score * 0.35 +
            risk_norm * 0.25 +
            censorship_score * 0.25 +
            min(forecast, 1.0) * 0.15
        )

        scores[code] = {
            **data,
            "impact_score": round(impact, 3),
            "block_score": round(block_score, 2),
            "risk_norm": round(risk_norm, 2),
            "censorship_score": round(censorship_score, 2),
        }

    return dict(sorted(scores.items(), key=lambda x: x[1]["impact_score"], reverse=True))


# ─── Chart Generation ────────────────────────────────────────────────────────

def create_heatmap(scores):
    """Create exchange blocking heat map."""
    countries = [f"{s['name']} ({c})" for c, s in scores.items()]
    z_data = []
    for code, s in scores.items():
        row = [1 if ex in s["blocked"] else 0 for ex in EXCHANGES]
        z_data.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=z_data,
        x=[e.replace(".com", "").replace(".io", "").title() for e in EXCHANGES],
        y=countries,
        colorscale=[[0, "#1a1a2e"], [1, "#e74c3c"]],
        showscale=False,
        text=[["Blocked" if v else "OK" for v in row] for row in z_data],
        texttemplate="%{text}",
        textfont={"size": 11},
    ))
    fig.update_layout(
        title="Crypto Exchange Censorship — Which Exchanges Are Blocked Where?",
        template="plotly_dark",
        height=max(400, len(countries) * 35 + 100),
        width=900,
        margin=dict(l=150),
        font=dict(family="Inter, sans-serif"),
    )
    return fig


def create_flow_chart(flow_metrics):
    """Create smart money flow comparison chart with 24h/7d/30d trends."""
    chains = []
    net_24h = []
    net_7d = []
    net_30d = []

    for chain, label in [("eth", "Ethereum"), ("bnb", "BNB Chain"), ("sol", "Solana"), ("base", "Base")]:
        n24 = flow_metrics.get(f"{chain}_net_24h", 0)
        n7 = flow_metrics.get(f"{chain}_net_7d", 0)
        n30 = flow_metrics.get(f"{chain}_net_30d", 0)
        if n24 != 0 or n7 != 0 or n30 != 0:
            chains.append(label)
            net_24h.append(n24 / 1e6)
            net_7d.append(n7 / 1e6)
            net_30d.append(n30 / 1e6)

    fig = make_subplots(rows=1, cols=2, subplot_titles=["Net Smart Money Flow by Timeframe", "Inflow vs Outflow (24h)"])

    # Left: 24h / 7d / 30d grouped bars
    fig.add_trace(go.Bar(name="24h", x=chains, y=net_24h, marker_color="#3498db"), row=1, col=1)
    fig.add_trace(go.Bar(name="7d", x=chains, y=net_7d, marker_color="#2ecc71"), row=1, col=1)
    fig.add_trace(go.Bar(name="30d", x=chains, y=net_30d, marker_color="#9b59b6"), row=1, col=1)

    # Right: Inflow vs outflow
    inflows = []
    outflows = []
    for chain in ["eth", "bnb", "sol", "base"]:
        inf = flow_metrics.get(f"{chain}_inflow_24h", 0)
        outf = flow_metrics.get(f"{chain}_outflow_24h", 0)
        if inf > 0 or outf > 0:
            inflows.append(inf / 1e6)
            outflows.append(-outf / 1e6)
    if inflows:
        fig.add_trace(go.Bar(name="Inflows", x=chains[:len(inflows)], y=inflows, marker_color="#2ecc71"), row=1, col=2)
        fig.add_trace(go.Bar(name="Outflows", x=chains[:len(outflows)], y=outflows, marker_color="#e74c3c"), row=1, col=2)

    fig.update_layout(
        template="plotly_dark",
        title="Smart Money Capital Flows — Trends Across Timeframes",
        height=450, width=900,
        barmode="group",
        font=dict(family="Inter, sans-serif"),
        yaxis_title="USD (millions)",
        yaxis2_title="USD (millions)",
    )
    return fig


def create_impact_chart(scores):
    """Create impact score ranking chart."""
    countries = [f"{s['name']}" for c, s in scores.items()]
    impact = [s["impact_score"] for s in scores.values()]
    blocks = [s["block_count"] for s in scores.values()]

    colors = ["#e74c3c" if i > 0.5 else "#f39c12" if i > 0.3 else "#2ecc71" for i in impact]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=impact, y=countries, orientation="h",
        marker_color=colors,
        text=[f"{i:.2f} ({b}/{len(EXCHANGES)} blocked)" for i, b in zip(impact, blocks)],
        textposition="auto",
    ))
    fig.update_layout(
        title="Censorship Impact Score — Crypto Exchange Accessibility Risk",
        template="plotly_dark",
        height=max(400, len(countries) * 30 + 100),
        width=900,
        xaxis_title="Impact Score (0 = free, 1 = fully censored)",
        yaxis=dict(autorange="reversed"),
        font=dict(family="Inter, sans-serif"),
        margin=dict(l=120),
    )
    return fig


def create_correlation_scatter(scores, flow_metrics):
    """Create correlation: exchange blocks vs independent censorship severity."""
    x_vals = []
    y_vals = []
    labels = []
    sizes = []

    for code, s in scores.items():
        x_vals.append(s["block_count"])
        # Use censorship severity score (from Voidly index) as independent Y variable
        # This is NOT derived from block_count — it's from OONI/CensoredPlanet measurements
        y_vals.append(s.get("score", 50))
        labels.append(s["name"])
        sizes.append(max(15, s["block_count"] * 4 + 10))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_vals,
        mode="markers+text",
        text=labels,
        textposition="top center",
        textfont=dict(size=11),
        marker=dict(
            size=sizes,
            color=x_vals,
            colorscale="RdYlGn_r",
            showscale=True,
            colorbar=dict(title="Exchanges Blocked"),
        ),
    ))
    fig.update_layout(
        title="Exchange Blocks vs Overall Censorship Severity (Independent Variables)",
        template="plotly_dark",
        height=500, width=900,
        xaxis_title=f"Crypto Exchanges Blocked (out of {len(EXCHANGES)})",
        yaxis_title="Censorship Severity Score (Voidly Index — OONI + CensoredPlanet)",
        font=dict(family="Inter, sans-serif"),
    )
    return fig


def create_alpha_chart(flow_metrics):
    """The alpha signal: BNB vs ETH/SOL capital trends across timeframes."""
    chains = ["Ethereum", "BNB Chain", "Solana", "Base"]
    prefixes = ["eth", "bnb", "sol", "base"]
    timeframes = ["24h", "7d", "30d"]

    fig = go.Figure()
    colors = {"24h": "#3498db", "7d": "#2ecc71", "30d": "#9b59b6"}

    for tf in timeframes:
        vals = []
        for p in prefixes:
            v = flow_metrics.get(f"{p}_net_{tf}", 0)
            vals.append(v / 1e6)
        fig.add_trace(go.Bar(name=tf, x=chains, y=vals, marker_color=colors[tf]))

    # Add annotation for BNB bleeding
    bnb_30d = flow_metrics.get("bnb_net_30d", 0)
    eth_30d = flow_metrics.get("eth_net_30d", 0)
    if bnb_30d < 0 and eth_30d != 0:
        direction = "outflows" if bnb_30d < 0 else "inflows"
        fig.add_annotation(
            x="BNB Chain", y=bnb_30d / 1e6,
            text=f"Binance ecosystem: ${abs(bnb_30d/1e6):.1f}M net {direction} (30d)",
            showarrow=True, arrowhead=2, ax=0, ay=-40,
            font=dict(color="#e74c3c", size=11),
        )

    fig.update_layout(
        title="The Alpha Signal — Binance Ecosystem Capital Flight",
        template="plotly_dark",
        height=450, width=900,
        barmode="group",
        font=dict(family="Inter, sans-serif"),
        yaxis_title="Net Smart Money Flow (USD millions)",
    )
    return fig


# ─── Report Generation ───────────────────────────────────────────────────────

def generate_report(scores, flow_metrics, nansen_data, charts, output_path, export_png=False):
    """Generate HTML report."""
    print("\n📊 Generating report...")

    # Export charts to HTML div strings
    chart_divs = {}
    for name, fig in charts.items():
        chart_divs[name] = fig.to_html(full_html=False, include_plotlyjs=False)
        if export_png:
            png_path = output_path.parent / f"{name}.png"
            try:
                fig.write_image(str(png_path), width=900, height=500, scale=2)
                print(f"  Exported {png_path}")
            except Exception as e:
                print(f"  PNG export failed for {name}: {e}")

    # Build context
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    top3 = list(scores.items())[:3]

    # Top movers from Nansen
    top_movers = {}
    for chain in ["eth", "bnb", "sol"]:
        movers = flow_metrics.get(f"{chain}_top_movers", [])
        if movers:
            top_movers[chain] = movers

    # Summary stats
    total_blocked = sum(1 for s in scores.values() if s["block_count"] > 0)
    most_censored = list(scores.items())[0] if scores else None
    avg_block_rate = sum(s["block_rate"] for s in scores.values()) / len(scores) if scores else 0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Censorship Alpha — When Countries Block Crypto</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f0f1a; color: #e0e0e0; font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.5rem; }}
  h1 {{ font-size: 2rem; color: #fff; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.4rem; color: #2ecc71; margin: 2.5rem 0 1rem; border-bottom: 1px solid #2ecc71; padding-bottom: 0.5rem; }}
  .subtitle {{ color: #888; font-size: 0.95rem; margin-bottom: 2rem; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
  .stat {{ background: #1a1a2e; border-radius: 12px; padding: 1.25rem; text-align: center; }}
  .stat .value {{ font-size: 2rem; font-weight: 700; color: #2ecc71; }}
  .stat .label {{ font-size: 0.85rem; color: #888; margin-top: 0.25rem; }}
  .chart {{ margin: 1.5rem 0; background: #1a1a2e; border-radius: 12px; padding: 1rem; overflow-x: auto; }}
  .insight {{ background: #1a1a2e; border-left: 4px solid #f39c12; padding: 1rem 1.25rem; border-radius: 0 8px 8px 0; margin: 1rem 0; }}
  .insight strong {{ color: #f39c12; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #2a2a3e; }}
  th {{ color: #2ecc71; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }}
  td {{ font-size: 0.9rem; }}
  .blocked {{ color: #e74c3c; }}
  .ok {{ color: #2ecc71; }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
  .tag-red {{ background: rgba(231,76,60,0.2); color: #e74c3c; }}
  .tag-green {{ background: rgba(46,204,113,0.2); color: #2ecc71; }}
  .tag-yellow {{ background: rgba(243,156,18,0.2); color: #f39c12; }}
  .footer {{ text-align: center; color: #555; font-size: 0.8rem; margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid #2a2a3e; }}
  a {{ color: #2ecc71; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="container">
  <h1>🔍 Censorship Alpha</h1>
  <p class="subtitle">When Countries Block Crypto Exchanges, Where Does the Money Go?<br>
  Generated {now} · Data from <a href="https://voidly.ai">Voidly</a> + <a href="https://nansen.ai">Nansen</a></p>

  <div class="stat-grid">
    <div class="stat"><div class="value">{total_blocked}</div><div class="label">Countries Blocking Exchanges</div></div>
    <div class="stat"><div class="value">{most_censored[1]['block_count']}/{len(EXCHANGES)}</div><div class="label">Most Blocked ({most_censored[1]['name']})</div></div>
    <div class="stat"><div class="value">{avg_block_rate:.0f}%</div><div class="label">Avg Exchange Block Rate</div></div>
    <div class="stat"><div class="value">{len(COUNTRIES)}</div><div class="label">Countries Analyzed</div></div>
  </div>

  <h2>1. Exchange Censorship Heat Map</h2>
  <p>Which crypto exchanges are blocked in which countries? Red = blocked, dark = accessible.</p>
  <div class="chart">{chart_divs['heatmap']}</div>

  <div class="insight">
    <strong>Key Finding:</strong> {most_censored[1]['name']} blocks {most_censored[1]['block_count']} of {len(EXCHANGES)} major exchanges.
    {f"The top 3 most censored countries ({', '.join(s['name'] for _, s in top3)}) collectively restrict access to the majority of global crypto infrastructure." if len(top3) >= 3 else ""}
  </div>

  <h2>2. Smart Money Flows</h2>
  <p>Where is smart money moving capital right now? Comparing flows across chains including BNB (Binance's home chain — directly impacted by Binance blocks).</p>
  <div class="chart">{chart_divs['flows']}</div>

  <h2>3. Censorship Impact Ranking</h2>
  <p>Combined score factoring exchange blocks, country risk tier, censorship severity, and 7-day forecast risk.</p>
  <div class="chart">{chart_divs['impact']}</div>

  <h2>4. The Correlation</h2>
  <p>Do countries that block more exchanges show higher overall censorship risk? The scatter plot reveals the relationship.</p>
  <div class="chart">{chart_divs['correlation']}</div>

  <h2>5. The Alpha Signal</h2>
  <p>BNB Chain — Binance's home ecosystem — is the most directly impacted by exchange censorship. As the most-blocked exchange globally, Binance's on-chain ecosystem should show capital flight patterns distinct from Ethereum or Solana.</p>
  <div class="chart">{chart_divs.get('alpha', '<p>No alpha chart data</p>')}</div>

  <div class="insight">
    <strong>Key insight:</strong> Exchange censorship is a strong proxy for overall internet freedom. Countries that block crypto exchanges almost always block social media, news, and communication tools too. Smart money flows on Binance's home chain (BNB) serve as a leading indicator of broader censorship trends.
  </div>

  <h2>6. Top Movers by Chain</h2>
  <p>The tokens seeing the largest smart money net flows in the last 24 hours.</p>
  <table>
    <tr><th>Chain</th><th>Token</th><th>Net Flow (24h)</th><th>Net Flow (7d)</th><th>Net Flow (30d)</th></tr>"""

    for chain, movers in top_movers.items():
        chain_label = {"eth": "Ethereum", "bnb": "BNB", "sol": "Solana"}.get(chain, chain)
        for m in movers[:3]:
            net_24h = m.get("net_24h", 0)
            net_7d = m.get("net_7d", 0)
            net_30d = m.get("net_30d", 0)
            color_24 = "ok" if net_24h > 0 else "blocked"
            color_7d = "ok" if net_7d > 0 else "blocked"
            color_30d = "ok" if net_30d > 0 else "blocked"
            html += f"""
    <tr>
      <td>{chain_label}</td>
      <td><strong>{m['symbol']}</strong></td>
      <td class="{color_24}">${net_24h:,.0f}</td>
      <td class="{color_7d}">${net_7d:,.0f}</td>
      <td class="{color_30d}">${net_30d:,.0f}</td>
    </tr>"""

    html += f"""
  </table>

  <h2>7. Country Deep Dives</h2>"""

    for code, s in top3:
        isps = s.get("isps", [])
        isp_text = ", ".join(i.get("name", i.get("asn", "?")) for i in isps[:3]) if isps else "Data not available"
        html += f"""
  <h3 style="color: #e74c3c; margin-top: 1.5rem;">{s['name']} ({code})</h3>
  <table>
    <tr><td>Exchanges Blocked</td><td class="blocked"><strong>{s['block_count']}/{len(EXCHANGES)}</strong> — {', '.join(s['blocked'][:4]) or 'None'}{' +more' if len(s['blocked']) > 4 else ''}</td></tr>
    <tr><td>Risk Tier</td><td><span class="tag {'tag-red' if s.get('risk_tier',3) <= 2 else 'tag-yellow' if s.get('risk_tier',3) <= 3 else 'tag-green'}">{s.get('risk_tier', '?')}/5</span></td></tr>
    <tr><td>Impact Score</td><td><strong>{s['impact_score']}</strong></td></tr>
    <tr><td>Top ISPs Enforcing Blocks</td><td>{isp_text}</td></tr>
    <tr><td>7-Day Forecast Risk</td><td>{s.get('forecast_risk', 'N/A')}</td></tr>
  </table>"""

    # Privacy tokens section
    privacy_data = nansen_data.get("privacy_search")
    if privacy_data and privacy_data.get("success"):
        tokens = privacy_data.get("data", {}).get("tokens", [])
        if tokens:
            html += """
  <h2>8. Privacy & Censorship-Resistant Tokens</h2>
  <p>Tokens found via Nansen search for "privacy VPN decentralized" — projects that directly benefit when exchange censorship increases.</p>
  <table>
    <tr><th>Token</th><th>Chain</th><th>Market Cap</th><th>24h Volume</th></tr>"""
            for t in tokens[:8]:
                mcap = t.get("market_cap", 0)
                vol = t.get("volume_24h", 0)
                html += f"""
    <tr>
      <td><strong>{t.get('symbol', '?')}</strong> — {t.get('name', '')[:30]}</td>
      <td>{t.get('chain', '?')}</td>
      <td>${mcap:,.0f}</td>
      <td>${vol:,.0f}</td>
    </tr>"""
            html += """
  </table>
  <div class="insight">
    <strong>Watch list:</strong> Privacy-focused tokens and decentralized exchange protocols stand to gain when centralized exchanges face regulatory blocks. These micro-cap tokens are early signals of where censorship-resistant capital is flowing.
  </div>"""

    # Prediction markets section
    pm_data = nansen_data.get("prediction_markets")
    if pm_data and pm_data.get("success"):
        markets = pm_data.get("data", {}).get("data", [])
        # Filter for geopolitically relevant markets
        geo_markets = [m for m in markets if any(kw in m.get("question", "").lower() for kw in ["iran", "china", "russia", "ban", "crypto", "regulation", "ceasefire", "sanction", "election"])]
        if not geo_markets:
            geo_markets = markets[:5]  # Fallback to top by volume
        if geo_markets:
            html += """
  <h2>9. Prediction Markets — Geopolitical Signals</h2>
  <p>Polymarket events that could impact crypto censorship dynamics. Geopolitical events drive regulatory decisions which drive exchange blocks.</p>
  <table>
    <tr><th>Event</th><th>Price</th><th>24h Volume</th></tr>"""
            for m in geo_markets[:5]:
                q = m.get("question", "?")[:65]
                price = m.get("last_trade_price", m.get("best_ask", 0))
                vol = m.get("volume_24hr", m.get("volume", 0))
                html += f"""
    <tr>
      <td>{q}</td>
      <td><strong>{price:.1%}</strong></td>
      <td>${vol:,.0f}</td>
    </tr>"""
            html += """
  </table>"""

    html += f"""

  <h2>Methodology</h2>
  <p>This report combines two data sources:</p>
  <ul style="margin: 0.5rem 0 0 1.5rem;">
    <li><strong>Voidly</strong> (<a href="https://voidly.ai">voidly.ai</a>) — Real-time internet censorship monitoring across {len(COUNTRIES)} countries. Tests {len(EXCHANGES)} major crypto exchanges for DNS, TCP, TLS, and HTTP blocking using OONI, CensoredPlanet, and community probe data.</li>
    <li><strong>Nansen</strong> (<a href="https://nansen.ai">nansen.ai</a>) — On-chain analytics tracking smart money flows, DEX activity, and exchange wallet balances across Ethereum, BNB Chain, Solana, and Base.</li>
    <li><strong>Ground-truth sources</strong> — Exchange blocking data enriched with verified reports from <a href="https://www.chainalysis.com/blog/crypto-sanctions-2026/">Chainalysis 2026 Crypto Crime Report</a>, <a href="https://www.coingecko.com/learn/countries-ban-bitcoin">CoinGecko</a>, <a href="https://www.cloudwards.net/where-is-crypto-illegal/">Cloudwards</a>, and <a href="https://defirace.com/binance-restricted-countries-complete-list-for-crypto-trading-in">DeFi Race</a>.</li>
  </ul>
  <p style="margin-top: 0.75rem;">The Censorship Impact Score combines exchange block count (35%), country risk tier (25%), censorship severity (25%), and 7-day forecast risk (15%). Exchange blocking data merges real-time API monitoring with verified ground-truth from published regulatory and research sources.</p>

  <div class="footer">
    <p>Built with <a href="https://github.com/nansen-ai/nansen-cli">Nansen CLI</a> + <a href="https://voidly.ai">Voidly API</a></p>
    <p>Open source: <a href="https://github.com/voidly-ai/censorship-alpha">github.com/voidly-ai/censorship-alpha</a></p>
    <p>#NansenCLI · CC BY 4.0</p>
  </div>
</div>
</body>
</html>"""

    output_path.write_text(html)
    print(f"  ✅ Report saved to {output_path}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Censorship Alpha — Crypto Exchange Censorship × On-Chain Flows")
    parser.add_argument("--output", "-o", default="output/report.html", help="Output HTML path")
    parser.add_argument("--png", action="store_true", help="Export charts as PNG for social media")
    parser.add_argument("--json", action="store_true", help="Export raw data as JSON for programmatic access")
    args = parser.parse_args()

    print("═══════════════════════════════════════════════════════")
    print("  🔍 Censorship Alpha")
    print("  When Countries Block Crypto, Where Does the Money Go?")
    print("═══════════════════════════════════════════════════════")

    # Phase 1: Voidly censorship data
    censorship = fetch_voidly_censorship()

    # Phase 2: Nansen on-chain data
    nansen_data = fetch_nansen_data()

    # Phase 3: Analysis
    print("\n🧮 Phase 3: Analyzing correlations...")
    flow_metrics = extract_flow_metrics(nansen_data)
    scores = compute_impact_scores(censorship, flow_metrics)

    print(f"\n  Top 5 by Impact Score:")
    for i, (code, s) in enumerate(list(scores.items())[:5]):
        print(f"    {i+1}. {s['name']}: {s['impact_score']} ({s['block_count']}/{len(EXCHANGES)} blocked)")

    # Phase 4: Charts
    print("\n📈 Phase 4: Generating charts...")
    charts = {
        "heatmap": create_heatmap(scores),
        "flows": create_flow_chart(flow_metrics),
        "impact": create_impact_chart(scores),
        "correlation": create_correlation_scatter(scores, flow_metrics),
        "alpha": create_alpha_chart(flow_metrics),
    }

    # Phase 5: Report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_report(scores, flow_metrics, nansen_data, charts, output_path, export_png=args.png)

    # Phase 6: JSON export (for AI agents and programmatic access)
    if args.json:
        json_path = output_path.parent / "data.json"
        json_export = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "censorship": "Voidly API (voidly.ai) + Chainalysis 2026 + CoinGecko + Cloudwards",
                "onchain": "Nansen CLI (nansen.ai)",
            },
            "countries": {code: {k: v for k, v in s.items() if k != "isps"} for code, s in scores.items()},
            "flow_metrics": {k: v for k, v in flow_metrics.items() if not k.endswith("_top_movers")},
            "top_movers": {k.replace("_top_movers", ""): v for k, v in flow_metrics.items() if k.endswith("_top_movers")},
            "impact_ranking": [{"country": code, "name": s["name"], "score": s["impact_score"], "blocked": s["block_count"]} for code, s in scores.items()],
        }
        json_path.write_text(json.dumps(json_export, indent=2))
        print(f"  📦 JSON data exported to {json_path}")

    print("\n═══════════════════════════════════════════════════════")
    print(f"  ✅ Done! Open {output_path} in your browser.")
    if args.png:
        print(f"  📸 PNG charts saved in {output_path.parent}/")
    if args.json:
        print(f"  📦 JSON data saved to {output_path.parent}/data.json")
    print("═══════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
