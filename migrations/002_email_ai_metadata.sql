alter table public.daily_health_metrics
  add column if not exists morning_ai_provider text,
  add column if not exists morning_ai_model text,
  add column if not exists evening_ai_provider text,
  add column if not exists evening_ai_model text;
