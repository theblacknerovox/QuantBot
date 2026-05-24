# ⚡ QuantBot AI — Plataforma Profissional de Day Trading

Sistema automatizado de análise e execução de operações em criptomoedas com Inteligência Artificial integrada à Binance.

---

## 🗂 Estrutura do Projeto

```
quantbot-ai/
├── index.html                  ← Dashboard completo (MVP standalone)
│
├── backend/
│   ├── main.py                 ← FastAPI — rotas principais
│   ├── trading_engine.py       ← Motor de execução automática
│   ├── indicators.py           ← RSI, MACD, EMA, Volume, Price Action
│   ├── requirements.txt        ← Dependências Python
│   ├── Dockerfile
│   └── services/
│       ├── ai_service.py       ← OpenAI / Gemini / Motor de Regras
│       ├── binance_service.py  ← Wrapper Binance API
│       ├── risk_manager.py     ← Gerenciamento de risco
│       └── telegram_service.py ← Alertas Telegram
│
├── database/
│   └── schema.sql              ← Schema PostgreSQL completo
│
├── docker-compose.yml          ← Stack completa (DB + Redis + Backend + Frontend)
├── .env.example                ← Template de variáveis de ambiente
├── deploy.sh                   ← Script automático para VPS Ubuntu
└── README.md
```

---

## 🚀 Quick Start

### Opção 1 — Dashboard Standalone (sem backend)
Abra `index.html` diretamente no navegador. Funciona com dados simulados em tempo real.

### Opção 2 — Stack Completa com Docker

```bash
# 1. Clonar e configurar
git clone https://github.com/seuusuario/quantbot-ai
cd quantbot-ai
cp .env.example .env
# Edite o .env com suas chaves

# 2. Subir tudo
docker compose up -d

# 3. Acessar
# Frontend: http://localhost:3000
# API Docs: http://localhost:8000/docs
```

### Opção 3 — Deploy em VPS Ubuntu
```bash
# No servidor (Ubuntu 22.04)
curl -sSL https://raw.githubusercontent.com/.../deploy.sh | bash
```

---

## ⚙️ Configuração

### Variáveis obrigatórias no `.env`

| Variável | Descrição |
|---|---|
| `SECRET_KEY` | Chave secreta da aplicação (64+ chars) |
| `ENCRYPTION_KEY` | Chave AES-256 para criptografar API keys |
| `DATABASE_URL` | URL PostgreSQL |
| `OPENAI_API_KEY` | Para IA via GPT-4 (ou use Gemini) |
| `GEMINI_API_KEY` | Para IA via Gemini Pro |
| `AI_PROVIDER` | `openai` \| `gemini` \| `rules` |

### Credenciais Binance
Cada usuário cadastra suas próprias chaves via painel de Configurações.
As chaves são criptografadas com AES-256 antes de salvar no banco.

---

## 🤖 Como a IA Funciona

```
Candles OHLCV
     ↓
TechnicalAnalysis (indicators.py)
  → RSI, MACD, EMA 9/21, Volume, Bollinger, ATR
  → Suporte/Resistência (pivot points)
  → Price Action (hammer, engulfing, doji)
  → Tendência do mercado
     ↓
AIService (ai_service.py)
  → Prompt estruturado para GPT-4/Gemini
  → Fallback: motor de regras local (sem custo)
  → Memória operacional: aprende com trades passados
     ↓
Classificação:
  FORTE COMPRA | COMPRA | NEUTRO | VENDA | FORTE VENDA
  + Confiança 0-100%
  + Justificativa em português
  + TP / SL sugeridos
     ↓
TradingEngine (trading_engine.py)
  → Valida com RiskManager
  → Executa ordem na Binance
  → Monitora posição (TP/SL/Trailing)
  → Notifica via Telegram
```

---

## 📊 Estratégia Base

**COMPRAR quando:**
- EMA 9 cruza EMA 21 para cima (crossover bullish)
- RSI saindo de sobrevenda (< 30 → subindo)
- Volume 50%+ acima da média de 20 períodos
- IA confirma tendência de alta com confiança ≥ 65%

**VENDER/FECHAR quando:**
- EMA 9 cruza EMA 21 para baixo
- RSI entra em sobrecompra (> 70)
- Take Profit atingido (padrão: 3x o risco)
- Stop Loss atingido (padrão: 1.5% do preço)

---

## 🛡 Gerenciamento de Risco

| Proteção | Descrição |
|---|---|
| Risco por operação | 1.5% do saldo (configurável) |
| Limite diário de perda | $150 USDT (configurável) |
| Max trades por dia | 12 (configurável) |
| Pausa automática | Após 3 perdas consecutivas (90min) |
| Proteção overtrade | Bloqueio automático |
| Tamanho de posição | Calculado pelo Kelly Criterion adaptado |

---

## 🔌 Endpoints da API

```
POST /auth/register          Cadastrar usuário
POST /auth/login             Login JWT

POST /binance/connect        Salvar e testar API keys
GET  /binance/account        Saldo e posições
GET  /binance/history        Histórico de trades

GET  /analysis/{symbol}      Análise técnica + IA
GET  /scanner                Scanner de todos os pares

POST /bot/start              Iniciar bot automático
POST /bot/stop               Pausar bot
POST /bot/config             Salvar configurações
POST /order/manual           Executar ordem manual

POST /backtest               Rodar backtest
GET  /metrics                Métricas do usuário

WS   /ws/{user_id}           WebSocket tempo real
```

---

## 📱 Integração Telegram

Configure no painel de Configurações. O bot envia:
- 🚀 Sinais gerados pela IA
- ✅ Trades abertos e fechados
- ⚠️ Alertas de risco
- 📊 Resumo diário às 23:59

---

## 🔐 Segurança

- Credenciais Binance criptografadas com AES-256
- JWT com expiração configurável
- Rate limiting por IP e por usuário
- Logs de auditoria completos
- Validação de ordens em múltiplas camadas
- Fail-safe: bot para automaticamente em caso de erro crítico

---

## 📈 Expansão Futura

- [ ] Suporte a mais exchanges (Bybit, OKX, Kraken)
- [ ] Estratégias customizáveis via UI (drag & drop)
- [ ] Copy trading entre usuários
- [ ] Alertas por email e push notification
- [ ] App mobile (React Native)
- [ ] Análise on-chain (whale watching)
- [ ] Integração com TradingView via webhooks

---

## ⚠️ Disclaimer

Este software é fornecido para fins educacionais e de pesquisa. Trading de criptomoedas envolve risco substancial de perda. Nunca invista mais do que pode perder. Resultados passados não garantem resultados futuros.
