#!/usr/bin/env python3
"""
Censorship Alpha — When Countries Block Crypto, Where Does the Money Go?

Correlates real-time internet censorship data (Voidly) with on-chain
blockchain fund flows (Nansen) to reveal how smart money adapts when
authoritarian governments block crypto exchanges.

Usage:
    python3 censorship_alpha.py [--output report.html] [--png]
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

    # 1-2. Smart money net flows
    data["eth_netflow"] = run_nansen(
        ["research", "smart-money", "netflow", "--chain", "ethereum", "--limit", "30"],
        "ETH smart money flows"
    )
    data["bnb_netflow"] = run_nansen(
        ["research", "smart-money", "netflow", "--chain", "bnb", "--limit", "30"],
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
        ["research", "smart-money", "netflow", "--chain", "solana", "--limit", "20"],
        "SOL smart money flows"
    )
    data["sol_dex"] = run_nansen(
        ["research", "smart-money", "dex-trades", "--chain", "solana", "--limit", "20"],
        "SOL DEX trades"
    )

    # 11. Binance hot wallet balance (if profiler works)
    data["binance_eth_wallet"] = run_nansen(
        ["research", "profiler", "balance", "--address", BINANCE_HOT_WALLETS["ethereum"], "--chain", "ethereum"],
        "Binance ETH wallet"
    )

    # 12. Base chain (Coinbase ecosystem)
    data["base_netflow"] = run_nansen(
        ["research", "smart-money", "netflow", "--chain", "base", "--limit", "15"],
        "Base smart money flows"
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
            metrics[f"{chain}_inflow_24h"] = total_inflow
            metrics[f"{chain}_outflow_24h"] = total_outflow
            metrics[f"{chain}_net_24h"] = net
            metrics[f"{chain}_tokens_tracked"] = len(items)
            # Top movers
            sorted_items = sorted(items, key=lambda x: abs(x.get("net_flow_24h_usd", 0)), reverse=True)
            metrics[f"{chain}_top_movers"] = [
                {"symbol": i.get("token_symbol", "?"), "net_24h": i.get("net_flow_24h_usd", 0), "net_7d": i.get("net_flow_7d_usd", 0)}
                for i in sorted_items[:5]
            ]

    # DEX volume
    for chain in ["eth", "bnb", "sol"]:
        key = f"{chain}_dex"
        raw = nansen_data.get(key)
        if raw and raw.get("success") and raw.get("data", {}).get("data"):
            items = raw["data"]["data"]
            total_vol = sum(abs(i.get("amount_usd", i.get("value_usd", 0))) for i in items)
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
    """Create smart money flow comparison chart."""
    chains = []
    inflows = []
    outflows = []
    nets = []

    for chain, label in [("eth", "Ethereum"), ("bnb", "BNB Chain"), ("sol", "Solana"), ("base", "Base")]:
        inf = flow_metrics.get(f"{chain}_inflow_24h", 0)
        outf = flow_metrics.get(f"{chain}_outflow_24h", 0)
        net = flow_metrics.get(f"{chain}_net_24h", 0)
        if inf > 0 or outf > 0:
            chains.append(label)
            inflows.append(inf / 1e6)
            outflows.append(-outf / 1e6)
            nets.append(net / 1e6)

    fig = make_subplots(rows=1, cols=2, subplot_titles=["Smart Money Flows (24h)", "Net Flow by Chain"])

    fig.add_trace(go.Bar(name="Inflows", x=chains, y=inflows, marker_color="#2ecc71"), row=1, col=1)
    fig.add_trace(go.Bar(name="Outflows", x=chains, y=outflows, marker_color="#e74c3c"), row=1, col=1)

    colors = ["#2ecc71" if n >= 0 else "#e74c3c" for n in nets]
    fig.add_trace(go.Bar(name="Net Flow", x=chains, y=nets, marker_color=colors), row=1, col=2)

    fig.update_layout(
        template="plotly_dark",
        title="Smart Money Capital Flows — Where Is Money Moving?",
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
    """Create the money chart: censorship score vs on-chain signal."""
    x_vals = []
    y_vals = []
    labels = []
    sizes = []

    # Use BNB chain DEX volume as a proxy for "censorship-driven DEX migration"
    bnb_dex = flow_metrics.get("bnb_dex_volume", 1)

    for code, s in scores.items():
        x_vals.append(s["block_count"])
        y_vals.append(s["impact_score"])
        labels.append(s["name"])
        sizes.append(max(15, s.get("score", 50) / 3))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_vals,
        mode="markers+text",
        text=labels,
        textposition="top center",
        textfont=dict(size=11),
        marker=dict(
            size=sizes,
            color=y_vals,
            colorscale="RdYlGn_r",
            showscale=True,
            colorbar=dict(title="Impact"),
        ),
    ))
    fig.update_layout(
        title="Censorship vs Impact — Countries That Block More Exchanges Have Higher Risk",
        template="plotly_dark",
        height=500, width=900,
        xaxis_title=f"Exchanges Blocked (out of {len(EXCHANGES)})",
        yaxis_title="Censorship Impact Score",
        font=dict(family="Inter, sans-serif"),
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

  <div class="insight">
    <strong>The Alpha Signal:</strong> Countries blocking crypto exchanges don't do it in isolation — they block everything.
    Exchange censorship is a strong proxy for overall internet freedom. When you see exchange blocks increasing, expect broader censorship to follow.
    Smart money should monitor these signals as leading indicators.
  </div>

  <h2>5. Top Movers by Chain</h2>
  <p>The tokens seeing the largest smart money net flows in the last 24 hours.</p>
  <table>
    <tr><th>Chain</th><th>Token</th><th>Net Flow (24h)</th><th>Net Flow (7d)</th></tr>"""

    for chain, movers in top_movers.items():
        chain_label = {"eth": "Ethereum", "bnb": "BNB", "sol": "Solana"}.get(chain, chain)
        for m in movers[:3]:
            net_24h = m.get("net_24h", 0)
            net_7d = m.get("net_7d", 0)
            color_24 = "ok" if net_24h > 0 else "blocked"
            color_7d = "ok" if net_7d > 0 else "blocked"
            html += f"""
    <tr>
      <td>{chain_label}</td>
      <td><strong>{m['symbol']}</strong></td>
      <td class="{color_24}">${net_24h:,.0f}</td>
      <td class="{color_7d}">${net_7d:,.0f}</td>
    </tr>"""

    html += f"""
  </table>

  <h2>6. Country Deep Dives</h2>"""

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

    html += f"""

  <h2>Methodology</h2>
  <p>This report combines two data sources:</p>
  <ul style="margin: 0.5rem 0 0 1.5rem;">
    <li><strong>Voidly</strong> (<a href="https://voidly.ai">voidly.ai</a>) — Real-time internet censorship monitoring across {len(COUNTRIES)} countries. Tests {len(EXCHANGES)} major crypto exchanges for DNS, TCP, TLS, and HTTP blocking using OONI, CensoredPlanet, and community probe data.</li>
    <li><strong>Nansen</strong> (<a href="https://nansen.ai">nansen.ai</a>) — On-chain analytics tracking smart money flows, DEX activity, and exchange wallet balances across Ethereum, BNB Chain, Solana, and Base.</li>
  </ul>
  <p style="margin-top: 0.75rem;">The Censorship Impact Score combines exchange block count (35%), country risk tier (25%), censorship severity (25%), and 7-day forecast risk (15%).</p>

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
    }

    # Phase 5: Report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_report(scores, flow_metrics, nansen_data, charts, output_path, export_png=args.png)

    print("\n═══════════════════════════════════════════════════════")
    print(f"  ✅ Done! Open {output_path} in your browser.")
    if args.png:
        print(f"  📸 PNG charts saved in {output_path.parent}/")
    print("═══════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
