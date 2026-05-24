-- QuantBot AI — Schema PostgreSQL
-- Criação de todas as tabelas do sistema

-- ─── EXTENSÕES ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── USUÁRIOS ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    name            VARCHAR(255) NOT NULL,
    hashed_password TEXT NOT NULL,
    is_admin        BOOLEAN DEFAULT FALSE,
    is_active       BOOLEAN DEFAULT TRUE,
    plan            VARCHAR(50) DEFAULT 'free',  -- free | basic | pro
    -- Credenciais Binance criptografadas (AES-256)
    binance_api_key_enc     TEXT,
    binance_api_secret_enc  TEXT,
    -- Telegram
    telegram_token_enc  TEXT,
    telegram_chat_id    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ
);

-- ─── CONFIGURAÇÕES DO BOT ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_configs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    mode            VARCHAR(20) DEFAULT 'auto',  -- manual | semi | auto
    risk_pct        DECIMAL(5,2) DEFAULT 1.5,
    daily_limit     DECIMAL(10,2) DEFAULT 150.0,
    max_trades      INTEGER DEFAULT 12,
    stop_loss_pct   DECIMAL(5,2) DEFAULT 1.5,
    take_profit_pct DECIMAL(5,2) DEFAULT 3.0,
    trailing_stop   BOOLEAN DEFAULT FALSE,
    trailing_pct    DECIMAL(5,2) DEFAULT 0.5,
    pairs           TEXT[] DEFAULT ARRAY['BTCUSDT', 'ETHUSDT'],
    timeframe       VARCHAR(10) DEFAULT '15m',
    market_type     VARCHAR(10) DEFAULT 'spot',  -- spot | futures
    is_active       BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── OPERAÇÕES (TRADES) ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(10) NOT NULL,  -- LONG | SHORT
    order_type      VARCHAR(20) DEFAULT 'MARKET',
    status          VARCHAR(20) DEFAULT 'OPEN',  -- OPEN | CLOSED | CANCELLED
    -- Entrada
    entry_price     DECIMAL(20,8) NOT NULL,
    entry_quantity  DECIMAL(20,8) NOT NULL,
    entry_time      TIMESTAMPTZ DEFAULT NOW(),
    entry_order_id  BIGINT,
    -- Saída
    exit_price      DECIMAL(20,8),
    exit_time       TIMESTAMPTZ,
    exit_order_id   BIGINT,
    exit_reason     VARCHAR(50),  -- TAKE_PROFIT | STOP_LOSS | MANUAL | TRAILING
    -- Níveis
    stop_loss       DECIMAL(20,8),
    take_profit     DECIMAL(20,8),
    -- Resultado
    pnl_usdt        DECIMAL(12,4),
    pnl_pct         DECIMAL(8,4),
    commission      DECIMAL(12,8),
    result          VARCHAR(10),  -- WIN | LOSS | BREAKEVEN
    -- Metadados
    signal_id       UUID,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_operations_user_id ON operations(user_id);
CREATE INDEX idx_operations_symbol ON operations(symbol);
CREATE INDEX idx_operations_status ON operations(status);
CREATE INDEX idx_operations_entry_time ON operations(entry_time DESC);

-- ─── SINAIS DE IA ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    symbol          VARCHAR(20) NOT NULL,
    timeframe       VARCHAR(10) DEFAULT '15m',
    -- Classificação
    signal          VARCHAR(20) NOT NULL,  -- FORTE COMPRA | COMPRA | NEUTRO | VENDA | FORTE VENDA
    confidence      INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    reasoning       TEXT,
    provider        VARCHAR(30) DEFAULT 'rules_engine',  -- openai | gemini | rules_engine
    -- Níveis sugeridos
    entry_price     DECIMAL(20,8),
    stop_loss       DECIMAL(20,8),
    take_profit     DECIMAL(20,8),
    risk_reward     DECIMAL(6,2),
    -- Indicadores no momento do sinal (JSON)
    indicators      JSONB,
    -- Resultado (preenchido depois)
    outcome         VARCHAR(10),  -- WIN | LOSS | IGNORED
    outcome_pnl     DECIMAL(12,4),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_signals_user_symbol ON signals(user_id, symbol);
CREATE INDEX idx_signals_created ON signals(created_at DESC);

-- ─── LOGS DO SISTEMA ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_logs (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    level       VARCHAR(10) NOT NULL,  -- INFO | SUCCESS | WARN | ERROR
    category    VARCHAR(50),           -- TRADE | AI | SYSTEM | BINANCE | RISK
    message     TEXT NOT NULL,
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_logs_user_created ON system_logs(user_id, created_at DESC);
CREATE INDEX idx_logs_level ON system_logs(level);

-- Limpeza automática de logs antigos (>30 dias)
CREATE OR REPLACE FUNCTION cleanup_old_logs()
RETURNS void AS $$
BEGIN
    DELETE FROM system_logs WHERE created_at < NOW() - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;

-- ─── MÉTRICAS DIÁRIAS ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_metrics (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    -- P&L
    total_pnl       DECIMAL(12,4) DEFAULT 0,
    realized_pnl    DECIMAL(12,4) DEFAULT 0,
    -- Trades
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    losing_trades   INTEGER DEFAULT 0,
    win_rate        DECIMAL(5,2),
    -- Risco
    max_drawdown    DECIMAL(8,4),
    daily_loss      DECIMAL(12,4) DEFAULT 0,
    -- Volume
    total_volume    DECIMAL(20,4) DEFAULT 0,
    UNIQUE(user_id, date)
);

-- ─── HISTÓRICO DE IA (MEMÓRIA OPERACIONAL) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_memory (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    winning_conditions  JSONB DEFAULT '[]',
    losing_conditions   JSONB DEFAULT '[]',
    filter_adjustments  JSONB DEFAULT '{}',
    total_analyses      INTEGER DEFAULT 0,
    last_updated        TIMESTAMPTZ DEFAULT NOW()
);

-- ─── BACKTEST RESULTS ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backtest_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    symbol          VARCHAR(20),
    timeframe       VARCHAR(10),
    start_date      DATE,
    end_date        DATE,
    initial_capital DECIMAL(12,2),
    final_capital   DECIMAL(12,2),
    roi             DECIMAL(8,4),
    win_rate        DECIMAL(5,2),
    profit_factor   DECIMAL(8,4),
    max_drawdown    DECIMAL(8,4),
    total_trades    INTEGER,
    sharpe_ratio    DECIMAL(8,4),
    equity_curve    JSONB,    -- Array de valores
    config_snapshot JSONB,    -- Config usada no backtest
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── SESSÕES / AUDITORIA ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID REFERENCES users(id),
    action      VARCHAR(100) NOT NULL,  -- LOGIN | API_KEY_UPDATED | ORDER_PLACED | etc
    ip_address  INET,
    user_agent  TEXT,
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── VIEWS ÚTEIS ─────────────────────────────────────────────────────────────

-- Resumo de performance por usuário
CREATE OR REPLACE VIEW user_performance_summary AS
SELECT
    u.id,
    u.name,
    u.email,
    COUNT(o.id) AS total_trades,
    SUM(CASE WHEN o.result = 'WIN' THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN o.result = 'LOSS' THEN 1 ELSE 0 END) AS losses,
    ROUND(
        100.0 * SUM(CASE WHEN o.result = 'WIN' THEN 1 ELSE 0 END) / NULLIF(COUNT(o.id), 0),
        2
    ) AS win_rate_pct,
    ROUND(COALESCE(SUM(o.pnl_usdt), 0), 2) AS total_pnl,
    ROUND(COALESCE(
        SUM(CASE WHEN o.result = 'WIN' THEN o.pnl_usdt ELSE 0 END) /
        NULLIF(ABS(SUM(CASE WHEN o.result = 'LOSS' THEN o.pnl_usdt ELSE 0 END)), 0),
        0
    ), 2) AS profit_factor
FROM users u
LEFT JOIN operations o ON o.user_id = u.id AND o.status = 'CLOSED'
GROUP BY u.id, u.name, u.email;

-- Melhores pares por win rate
CREATE OR REPLACE VIEW best_pairs AS
SELECT
    user_id,
    symbol,
    COUNT(*) AS total_trades,
    ROUND(100.0 * SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) / COUNT(*), 2) AS win_rate,
    ROUND(SUM(pnl_usdt), 2) AS total_pnl
FROM operations
WHERE status = 'CLOSED'
GROUP BY user_id, symbol
ORDER BY win_rate DESC, total_trades DESC;
