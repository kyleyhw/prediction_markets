"""The hosted platform around the engine.

`vp/` is the engine: it takes data roots, specs and cutoffs, and knows
nothing about users, HTTP or money. `vp/platform/` is everything the engine
is wrapped in so that many people can use it at once: configuration,
identity, per-workspace storage, background jobs and, later, the web
service.

The division is the first principle of `docs/scaling.md`: the engine never
knows who is calling. Nothing in this package may be imported by a module
under `vp/` outside it.
"""
