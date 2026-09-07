begin;

alter table public.daily_health_metrics
  drop column if exists evening_email_sent_at,
  drop column if exists evening_data_hash,
  drop column if exists evening_ai_provider,
  drop column if exists evening_ai_model,
  drop column if exists partial_day_as_of;

alter table public.health_accounts
  drop column if exists refresh_token_ciphertext;

commit;
