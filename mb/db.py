"""
Optional Supabase persistence for swing history.

If SUPABASE_URL + SUPABASE_KEY (service role or anon with RLS) are set,
history is stored in table `swing_signals` and stats can grow without
JSON size limits. Otherwise falls back to local JSON (SWING_HISTORY_JSON).

SQL to create the table (run once in Supabase SQL editor):

create table if not exists swing_signals (
  id bigserial primary key,
  signal_date date not null,
  ticker text not null,
  entry double precision,
  stop_loss double precision,
  t1 double precision,
  t2 double precision,
  t3 double precision,
  confidence double precision,
  status text not null default 'active',
  outcome text,
  hit_t1 boolean default false,
  hit_t2 boolean default false,
  hit_t3 boolean default false,
  days_held int default 0,
  exit_price double precision,
  exit_date date,
  r_multiple double precision,
  last_price double precision,
  as_of text,
  reasons jsonb default '[]'::jsonb,
  updated_at timestamptz default now(),
  unique (signal_date, ticker)
);

create index if not exists swing_signals_status_idx on swing_signals (status);
create index if not exists swing_signals_date_idx on swing_signals (signal_date desc);
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from mb.utils import load_json, save_json
from mb.config import SWING_HISTORY_JSON

_client = None


def supabase_enabled() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not supabase_enabled():
        return None
    try:
        from supabase import create_client
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        return _client
    except Exception as e:
        print(f"Supabase client init failed, using JSON: {e}")
        return None


def _row_to_sig(row: dict) -> dict:
    return {
        "date": str(row.get("signal_date") or "")[:10],
        "ticker": row.get("ticker"),
        "entry": row.get("entry"),
        "stop_loss": row.get("stop_loss"),
        "t1": row.get("t1"),
        "t2": row.get("t2"),
        "t3": row.get("t3"),
        "confidence": row.get("confidence"),
        "status": row.get("status") or "active",
        "outcome": row.get("outcome"),
        "hit_t1": bool(row.get("hit_t1")),
        "hit_t2": bool(row.get("hit_t2")),
        "hit_t3": bool(row.get("hit_t3")),
        "days_held": row.get("days_held") or 0,
        "exit_price": row.get("exit_price"),
        "exit_date": str(row["exit_date"])[:10] if row.get("exit_date") else None,
        "r_multiple": row.get("r_multiple"),
        "last_price": row.get("last_price"),
        "as_of": row.get("as_of"),
        "reasons": row.get("reasons") or [],
    }


def _sig_to_row(s: dict) -> dict:
    return {
        "signal_date": s.get("date"),
        "ticker": s.get("ticker"),
        "entry": s.get("entry"),
        "stop_loss": s.get("stop_loss"),
        "t1": s.get("t1"),
        "t2": s.get("t2"),
        "t3": s.get("t3"),
        "confidence": s.get("confidence"),
        "status": s.get("status") or "active",
        "outcome": s.get("outcome"),
        "hit_t1": bool(s.get("hit_t1")),
        "hit_t2": bool(s.get("hit_t2")),
        "hit_t3": bool(s.get("hit_t3")),
        "days_held": s.get("days_held") or 0,
        "exit_price": s.get("exit_price"),
        "exit_date": s.get("exit_date"),
        "r_multiple": s.get("r_multiple"),
        "last_price": s.get("last_price"),
        "as_of": s.get("as_of"),
        "reasons": s.get("reasons") or [],
    }


def load_swing_history() -> List[Dict[str, Any]]:
    """Load history from Supabase if configured, else JSON."""
    client = _get_client()
    if client is None:
        return load_json(SWING_HISTORY_JSON, [])

    try:
        # Active + last 100 closed
        r1 = (
            client.table("swing_signals")
            .select("*")
            .eq("status", "active")
            .execute()
        )
        r2 = (
            client.table("swing_signals")
            .select("*")
            .neq("status", "active")
            .order("exit_date", desc=True)
            .limit(100)
            .execute()
        )
        rows = (r1.data or []) + (r2.data or [])
        return [_row_to_sig(r) for r in rows]
    except Exception as e:
        print(f"Supabase load failed, falling back to JSON: {e}")
        return load_json(SWING_HISTORY_JSON, [])


def save_swing_history(history: List[Dict[str, Any]]) -> None:
    """Upsert history to Supabase if configured; always also write JSON backup."""
    # Always keep local JSON as backup / offline mode
    save_json(SWING_HISTORY_JSON, history)

    client = _get_client()
    if client is None:
        return

    try:
        rows = [_sig_to_row(s) for s in history if s.get("ticker") and s.get("date")]
        if not rows:
            return
        # Upsert in chunks
        for i in range(0, len(rows), 50):
            chunk = rows[i : i + 50]
            client.table("swing_signals").upsert(
                chunk, on_conflict="signal_date,ticker"
            ).execute()
        print(f"Supabase: upserted {len(rows)} swing_signals rows")
    except Exception as e:
        print(f"Supabase save failed (JSON backup kept): {e}")
