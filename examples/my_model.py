"""A model of your own, written as a program (docs/models.md, "Your own copy").

Your copy runs this once per call: the request arrives as JSON on standard
input and the reply leaves as JSON on standard output (the format is in
`vp/llm/command.py`). This one is a rule, not a language model: for a
match, it asks for each team's recent results with the same tool a
language model would use, and answers with the first team's share of the
wins. Anything else gets an even chance. Change it into whatever you like.

Set it as your copy's model with:

    VP_DEMO_PROVIDER=command
    VP_DEMO_BASE_URL="python /models/my_model.py"

The strategy assistant and the research assistant need a language model
to talk to; a rule like this one answers forecasts only.
"""

import json
import re
import sys


def reply(text: str = "", calls: list | None = None) -> None:
    content = [{"type": "text", "text": text}] if text else []
    content += calls or []
    print(
        json.dumps(
            {"content": content, "usage": {"input_tokens": 0, "output_tokens": 0}}
        )
    )


request = json.load(sys.stdin)
messages = request["messages"]
question = messages[0]["content"] if messages else ""
wants_probability = "probability" in json.dumps(request.get("schema") or {})
tools = {t["name"] for t in request.get("tools", [])}
# The question lists the market's structured fields, one "  name: value"
# a line; a match names the side the question is about and both teams.
fields = dict(re.findall(r"^  (\w+): (.+)$", str(question), re.MULTILINE))
side = fields.get("side")
other = fields.get("team_b") if side == fields.get("team_a") else fields.get("team_a")
teams = [(side, other)] if side and other else []

if not wants_probability:
    reply(
        "This model is a rule that answers forecasts only; "
        "connect a language model for conversation."
    )
elif len(messages) == 1 and teams and "team_results" in tools:
    first, second = teams[0]
    reply(
        calls=[
            {
                "type": "tool_use",
                "id": "a",
                "name": "team_results",
                "input": {"team": first, "limit": 10},
            },
            {
                "type": "tool_use",
                "id": "b",
                "name": "team_results",
                "input": {"team": second, "limit": 10},
            },
        ]
    )
else:
    results = {
        block["tool_use_id"]: str(block.get("content", ""))
        for block in (
            messages[-1]["content"] if isinstance(messages[-1]["content"], list) else []
        )
        if block.get("type") == "tool_result"
    }
    p = 0.5

    def wins(lines: str, team: str) -> int:
        """Results whose winner is this team (the tools use short names)."""
        won = [ln.lower().rsplit("winner ", 1)[-1].strip() for ln in lines.splitlines()]
        return sum(1 for w in won if w and w in team.lower())

    if teams and results:
        first, second = teams[0]
        wins_a, wins_b = (
            wins(results.get("a", ""), first),
            wins(results.get("b", ""), second),
        )
        p = (wins_a + 1) / (wins_a + wins_b + 2)  # one win each to start with
    reply(
        json.dumps(
            {
                "probability": round(p, 3),
                "rationale": f"recent wins share, rule-based ({p:.2f})",
            }
        )
    )
