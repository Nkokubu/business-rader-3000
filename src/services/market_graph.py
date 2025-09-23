from __future__ import annotations
import os
from typing import Dict, List, Tuple, Optional, Callable

import networkx as nx
import plotly.graph_objects as go

# type of your existing similar-companies function:
# Callable[[str], List[Dict[str, str]]]
# it returns items like {"name": "...", "website": "https://..."}

def build_market_graph(
    seed_company: str,
    get_similar: Callable[[str], List[Dict[str, str]]],
    max_depth: int = 1,
    max_per_company: int = 8,
) -> nx.Graph:
    """
    Build an undirected graph:
      - Add seed node
      - Connect seed -> its similar companies (up to max_per_company)
      - If max_depth > 1, expand peers recursively (breadth-first, one level each)
    Node attrs: {"name": str, "website": Optional[str], "seed": bool}
    Edge attrs: {"relation": "similar"}
    """
    seed = (seed_company or "").strip()
    G = nx.Graph()
    if not seed:
        return G

    G.add_node(seed, name=seed, website=None, seed=True)

    # BFS frontier: (company_name, depth)
    frontier: List[Tuple[str, int]] = [(seed, 0)]
    seen: set[str] = {seed}

    while frontier:
        company, depth = frontier.pop(0)
        if depth >= max_depth:
            continue

        try:
            peers = get_similar(company)[:max_per_company] if max_per_company else get_similar(company)
        except Exception:
            peers = []

        for p in peers:
            name = (p.get("name") or "").strip()
            if not name or name == company:
                continue
            website = (p.get("website") or "").strip() or None

            if name not in G:
                G.add_node(name, name=name, website=website, seed=False)
            else:
                # enrich website if missing
                if website and not G.nodes[name].get("website"):
                    G.nodes[name]["website"] = website

            if not G.has_edge(company, name):
                G.add_edge(company, name, relation="similar")

            if name not in seen:
                seen.add(name)
                frontier.append((name, depth + 1))

    return G


def graph_to_edge_list(G: nx.Graph) -> List[Dict[str, str]]:
    """Return a simple edge list for export/debug."""
    edges = []
    for u, v, d in G.edges(data=True):
        edges.append({"source": u, "target": v, "relation": d.get("relation", "similar")})
    return edges


def render_market_graph_html(
    G: nx.Graph,
    out_path: str = "exports/market_map.html",
    title: Optional[str] = None,
) -> str:
    """
    Save an interactive HTML (Plotly).
    - Node size ~ degree
    - Seed node highlighted
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if G.number_of_nodes() == 0:
        # Create a tiny placeholder chart
        fig = go.Figure()
        fig.update_layout(title=title or "Market Map (empty)", showlegend=False)
        fig.write_html(out_path, include_plotlyjs="cdn")
        return out_path

    # layout
    pos = nx.spring_layout(G, k=0.6 / (len(G.nodes()) ** 0.5), seed=42)

    # edges
    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1),
        hoverinfo="none",
        name="links",
    )

    # nodes
    node_x, node_y, node_text, node_size, node_color = [], [], [], [], []
    degrees = dict(G.degree())
    max_deg = max(degrees.values()) if degrees else 1

    for n, data in G.nodes(data=True):
        x, y = pos[n]
        node_x.append(x); node_y.append(y)
        label = data.get("name") or n
        website = data.get("website") or ""
        node_text.append(label + (f"\n{website}" if website else ""))
        # size: seed bigger, else scale by degree
        base = 22 if data.get("seed") else 8 + 12 * (degrees[n] / max_deg if max_deg else 0)
        node_size.append(base)
        node_color.append("#2b8a3e" if data.get("seed") else "#1d4ed8")

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers",
        hoverinfo="text",
        text=node_text,
        marker=dict(size=node_size, opacity=0.9),
        name="companies",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=title or "Similar Market Map",
        showlegend=False,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
    )

    fig.write_html(out_path, include_plotlyjs="cdn")
    return out_path

def _sanitize_for_gexf(G: nx.Graph) -> nx.Graph:
    """
    Return a copy of G with all node/edge attributes converted to
    GEXF-safe types (str/int/float/bool) and with None removed.
    """
    H = G.copy()
    # Nodes
    for n, data in list(H.nodes(data=True)):
        for k, v in list(data.items()):
            if v is None:
                del H.nodes[n][k]
            elif isinstance(v, (str, int, float, bool)):
                # ok
                pass
            else:
                H.nodes[n][k] = str(v)
    # Edges
    for u, v, data in list(H.edges(data=True)):
        for k, val in list(data.items()):
            if val is None:
                del H.edges[u, v][k]
            elif isinstance(val, (str, int, float, bool)):
                pass
            else:
                H.edges[u, v][k] = str(val)
    return H



def save_graph_gexf(G: nx.Graph, out_path: str = "exports/market_map.gexf") -> str:
    """
    Save a GEXF file (open in Gephi) for deeper graph analysis.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    safe = _sanitize_for_gexf(G)
    nx.write_gexf(safe, out_path)
    return out_path


def build_and_render_market_map(
    seed_company: str,
    get_similar: Callable[[str], List[Dict[str, str]]],
    max_depth: int = 1,
    max_per_company: int = 8,
    html_out: str = "exports/market_map.html",
    gexf_out: Optional[str] = None,
) -> Dict[str, str]:
    """
    Convenience: build graph then write HTML (and optional GEXF).
    Returns paths.
    """
    G = build_market_graph(seed_company, get_similar, max_depth=max_depth, max_per_company=max_per_company)
    html_path = render_market_graph_html(G, out_path=html_out, title=f"Market Map: {seed_company}")
    out = {"html": html_path}
    if gexf_out:
        out["gexf"] = save_graph_gexf(G, gexf_out)
    return out
