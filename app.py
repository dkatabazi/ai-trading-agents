from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List
import json, uuid
from datetime import datetime, timezone, timedelta

# --- UAL v2 helpers (same as before) ---
TZ = timezone(timedelta(hours=3))
ACTS = {"PING","ACK","QUERY","INFORM","PROPOSE","VOTE","EXEC","ERROR"}

def ts_now():
    return datetime.now(TZ).isoformat(timespec="seconds")

def make_id():
    return uuid.uuid4().hex[:10]

def ual2_make(src, dst="*", act="INFORM", obj="general", conf=1.0,
             goal="", constraints=None, evidence=None, rule=None, decision=None, trace=None):
    if act not in ACTS:
        raise ValueError(f"bad act: {act}")
    msg = {
        "v": 2, "id": make_id(), "src": src, "dst": dst, "act": act, "obj": obj,
        "conf": float(conf), "goal": goal,
        "constraints": constraints or {}, "evidence": evidence or [],
        "rule": rule or {}, "decision": decision or {}, "trace": trace or [],
        "ts": ts_now()
    }
    return msg

# --- Your agents (same demo logic; replace later with your real rules) ---
class TrendAI:
    name = "trend_ai"
    def vote(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        rsi = proposal["decision"].get("rsi", 50)
        side = proposal["decision"].get("side", "BUY")
        agree = 1 if (side == "BUY" and rsi >= 50) or (side == "SELL" and rsi <= 50) else 0
        return {"vote": agree, "note": f"rsi={rsi}"}

class TrapAI:
    name = "trap_ai"
    def vote(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        trap = bool(proposal["decision"].get("trap_wick", False))
        return {"vote": 0 if trap else 1, "note": "trap_wick" if trap else "no_trap"}

class RiskAI:
    name = "risk_ai"
    def vote(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        d = proposal["decision"]
        entry = float(d.get("entry", 0)); sl = float(d.get("sl", 0)); tp = float(d.get("tp", 0))
        min_rr = float(proposal.get("constraints", {}).get("min_rr", 1.5))
        risk = abs(entry - sl); reward = abs(tp - entry)
        rr = (reward / risk) if risk > 0 else 0.0
        agree = 1 if rr >= min_rr and risk > 0 else 0
        max_size = 0.02 if risk <= 10 else 0.01
        return {"vote": agree, "rr": round(rr, 2), "max_size": max_size}

class ExecAI:
    name = "exec_ai"
    def decide(self, votes: List[Dict[str, Any]], proposal: Dict[str, Any]) -> Dict[str, Any]:
        yes = sum(v["decision"].get("vote", 0) for v in votes)
        if yes >= 2:
            sizes = [v["decision"].get("max_size", 0.02) for v in votes if "max_size" in v["decision"]]
            size = min(sizes) if sizes else 0.01
            final = dict(proposal["decision"])
            final["size"] = size
            final["approved_votes"] = yes
            return {"exec": True, "final": final}
        return {"exec": False, "reason": f"{yes}/3 votes approved"}

# --- FastAPI ---
app = FastAPI(title="UAL Trading Team API")

class Proposal(BaseModel):
    proposal: Dict[str, Any]  # should be a UAL v2 PROPOSE message (as dict)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/run")
def run_team(p: Proposal):
    proposal = p.proposal

    # vote messages
    trend = TrendAI(); trap = TrapAI(); risk = RiskAI(); execa = ExecAI()
    voters = [trend, trap, risk]

    votes = []
    for a in voters:
        decision = a.vote(proposal)
        vote_msg = ual2_make(
            src=a.name, dst="exec_ai", act="VOTE", obj="trade_decision", conf=0.8,
            goal="validate_proposal", decision=decision, trace=["evaluate", "vote"]
        )
        votes.append(vote_msg)

    result = execa.decide(votes=votes, proposal=proposal)

    if result["exec"]:
        exec_msg = ual2_make(
            src="exec_ai", dst="broker_or_bot", act="EXEC", obj="trade_execution", conf=0.9,
            goal="execute_trade", decision=result["final"], trace=["count_votes>=2","set_size","EXEC"]
        )
        return {"votes": votes, "result": exec_msg}

    reject_msg = ual2_make(
        src="exec_ai", dst=proposal.get("src", "entry_ai"), act="ERROR", obj="trade_rejected", conf=0.85,
        goal="avoid_bad_trade", decision=result, trace=["count_votes<2","reject"]
    )
    return {"votes": votes, "result": reject_msg}
