create extension if not exists pgcrypto;

create table if not exists public.health_accounts (
  id uuid primary key default gen_random_uuid(),
  account_key text not null unique,
  google_health_user_id text,
  google_legacy_user_id text,
  authorized_scopes text[] not null default '{}',
  refresh_token_ref text,
  refresh_token_ciphertext text,
  last_sync_started_at timestamptz,
  last_sync_completed_at timestamptz,
  last_sync_status text,
  last_sync_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.health_records (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.health_accounts(id) on delete cascade,
  data_type text not null,
  source_record_id text not null,
  source_record_hash text not null,
  metric_date date,
  observed_start_at timestamptz,
  observed_end_at timestamptz,
  value_json jsonb not null default '{}'::jsonb,
  raw_json jsonb not null default '{}'::jsonb,
  synced_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account_id, source_record_id)
);

create index if not exists health_records_account_date_idx
  on public.health_records(account_id, metric_date);

create index if not exists health_records_account_type_date_idx
  on public.health_records(account_id, data_type, metric_date);

create table if not exists public.daily_health_metrics (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.health_accounts(id) on delete cascade,
  metric_date date not null,

  sleep_start_at timestamptz,
  sleep_end_at timestamptz,
  sleep_minutes_total numeric,
  sleep_minutes_asleep numeric,
  sleep_minutes_awake numeric,
  sleep_minutes_light numeric,
  sleep_minutes_deep numeric,
  sleep_minutes_rem numeric,
  sleep_efficiency numeric,

  hrv_rmssd_ms numeric,
  resting_hr_bpm numeric,
  respiratory_rate_bpm numeric,
  spo2_avg_pct numeric,
  sleep_temp_delta_c numeric,
  vo2_max numeric,
  weight_kg numeric,

  steps integer,
  active_zone_minutes numeric,
  active_minutes_total numeric,
  active_minutes_light numeric,
  active_minutes_moderate numeric,
  active_minutes_vigorous numeric,
  exercise_minutes numeric,
  sedentary_minutes numeric,

  readiness_score numeric,
  strain_score numeric,
  partial_day_as_of timestamptz,
  data_quality jsonb not null default '{}'::jsonb,
  baseline_7d jsonb not null default '{}'::jsonb,
  baseline_28d jsonb not null default '{}'::jsonb,

  morning_email_sent_at timestamptz,
  evening_email_sent_at timestamptz,
  morning_data_hash text,
  evening_data_hash text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account_id, metric_date)
);

create index if not exists daily_health_metrics_account_date_idx
  on public.daily_health_metrics(account_id, metric_date);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists health_accounts_updated_at on public.health_accounts;
create trigger health_accounts_updated_at
before update on public.health_accounts
for each row execute function public.set_updated_at();

drop trigger if exists health_records_updated_at on public.health_records;
create trigger health_records_updated_at
before update on public.health_records
for each row execute function public.set_updated_at();

drop trigger if exists daily_health_metrics_updated_at on public.daily_health_metrics;
create trigger daily_health_metrics_updated_at
before update on public.daily_health_metrics
for each row execute function public.set_updated_at();

