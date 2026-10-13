"""An AI model as the forecaster: your own model and key, asked per market.

Set the model and its key as environment variables, then run it on a few
markets first (each market is one call, billed by your provider unless its
plan is free):

    export VP_MODEL=gemini:gemini-3.1-flash-lite GEMINI_API_KEY=...
    uv run vp strategy backtest strategies/example_ai/strategy.json \
        --script strategies/example_ai/forecast.py --max-markets 20

``VP_MODEL`` is ``provider:model`` for any provider in docs/models.md
(``anthropic:...``, ``openai:...``, ``groq:...``, ``ollama:...``); the key
is ``<PROVIDER>_API_KEY``. A model trained after the matches may remember
how they ended, so its backtest flatters it: paper trading, on matches not
yet played, is the honest test (docs/forecasters.md).
"""

import json
import os

from vp.forecast.evidence import canonical
from vp.forecast.llm import client_for_model

MODEL = os.environ.get("VP_MODEL", "gemini:gemini-3.1-flash-lite")
client, model = client_for_model(MODEL)


def forecast(market, evidence):
    fields = market.parsed
    if fields.get("kind") != "match":
        return None
    team = canonical(fields.get("side") or fields["team_a"])
    recent = [
        f"{r.settled:%Y-%m-%d} {r.team_a} v {r.team_b}: {r.winner}"
        for r in evidence.results(market.domain)
        if team in (r.team_a, r.team_b)
    ][-10:]
    prompt = (
        f"Date: {evidence.cutoff:%Y-%m-%d}. Question: {market.question}\n"
        f"Recent results of {team} (winner after the colon):\n"
        + "\n".join(recent or ["none known"])
        + '\nAnswer with JSON only: {"chance": <0 to 1>, "reason": "<one line>"}'
    )
    reply = client.messages.create(
        model=model,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in reply.content if b.type == "text")
    try:
        answer = json.loads(text[text.index("{") : text.rindex("}") + 1])
        return float(answer["chance"]), str(answer.get("reason", ""))
    except ValueError, KeyError:
        return None  # an answer that is not a chance: skip the market
