-- Migration 0008: who paid for a model call.
--
-- A workspace may use its own provider key (stored under envelope
-- encryption in `provider_keys`). Its calls are still recorded, so the
-- person sees what their runs cost, but they are not the platform's
-- spending and do not count against the monthly budget.

alter table spend add column paid_by text not null default 'platform'
    check (paid_by in ('platform', 'own_key'));
