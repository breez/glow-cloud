CREATE TABLE IF NOT EXISTS api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_hash TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  max_amount_sats BIGINT,
  budget_sats BIGINT,
  budget_period TEXT CHECK (budget_period IN ('daily', 'weekly', 'monthly')),
  permissions TEXT[] NOT NULL DEFAULT ARRAY['balance', 'receive'],
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budget_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  api_key_id UUID NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
  amount_sats BIGINT NOT NULL,
  operation TEXT NOT NULL,
  period_start TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_budget_usage_key_period ON budget_usage (api_key_id, period_start);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (key_hash) WHERE is_active = true;
