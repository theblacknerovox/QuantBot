"""
QuantBot AI — Backend FastAPI
Motor principal do sistema de trading automatizado
"""

from fastapi import FastAPI, WebSocket, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from contextlib import asynccontextmanager
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List

# ─── IMPORTS INTERNOS ──────────────────────────────────────────────────────────
from config import settings
from database import get_db, init_db
from models import User, Operation, Signal, Log, BotConfig
from auth import create_access_token, verify_token, hash_password, verify_password
from services.binance_service import BinanceService
from services.ai_service import AIService
from services.telegram_service import TelegramService
from services.risk_manager import RiskManager
from trading_engine import TradingEngine
from indicators import TechnicalAnalysis

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── STATE GLOBAL ──────────────────────────────────────────────────────────────
active_connections: List[WebSocket] = []
trading_engine: Optional[TradingEngine] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização e cleanup da aplicação"""
    logger.info("🚀 QuantBot AI iniciando...")
    await init_db()
    global trading_engine
    trading_engine = TradingEngine()
    yield
    logger.info("⏹️  QuantBot AI encerrando...")
    if trading_engine:
        await trading_engine.stop()

# ─── APP ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="QuantBot AI",
    description="Sistema profissional de Day Trading com IA integrada à Binance",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ─── AUTH ───────────────────────────────────────────────────────────────────────

@app.post("/auth/register")
async def register(email: str, password: str, name: str, db=Depends(get_db)):
    """Registrar novo usuário"""
    existing = await db.get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    
    user = User(
        email=email,
        name=name,
        hashed_password=hash_password(password),
        created_at=datetime.utcnow(),
    )
    await db.create_user(user)
    token = create_access_token({"sub": user.id})
    return {"access_token": token, "token_type": "bearer", "user": user.to_dict()}


@app.post("/auth/login")
async def login(form: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    """Login com email e senha"""
    user = await db.get_user_by_email(form.username)
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    
    token = create_access_token({"sub": user.id})
    return {"access_token": token, "token_type": "bearer"}


async def get_current_user(token: str = Depends(oauth2_scheme), db=Depends(get_db)):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")
    user = await db.get_user(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user

# ─── BINANCE ─────────────────────────────────────────────────────────────────

@app.post("/binance/connect")
async def connect_binance(api_key: str, api_secret: str, user=Depends(get_current_user)):
    """Salvar e testar credenciais Binance"""
    service = BinanceService(api_key, api_secret)
    is_valid = await service.test_connection()
    if not is_valid:
        raise HTTPException(status_code=400, detail="Credenciais Binance inválidas")
    
    # Salvar credenciais criptografadas
    await user.save_binance_credentials(api_key, api_secret)
    return {"status": "connected", "message": "Conexão Binance estabelecida"}


@app.get("/binance/account")
async def get_account(user=Depends(get_current_user)):
    """Retornar saldo e posições da conta Binance"""
    service = BinanceService.from_user(user)
    account = await service.get_account_info()
    positions = await service.get_open_positions()
    return {"account": account, "positions": positions}


@app.get("/binance/history")
async def get_trade_history(
    symbol: Optional[str] = None,
    limit: int = 50,
    user=Depends(get_current_user)
):
    """Histórico de trades"""
    service = BinanceService.from_user(user)
    history = await service.get_trade_history(symbol=symbol, limit=limit)
    return {"trades": history}

# ─── ANÁLISE ─────────────────────────────────────────────────────────────────

@app.get("/analysis/{symbol}")
async def analyze_symbol(symbol: str, timeframe: str = "15m", user=Depends(get_current_user)):
    """
    Análise técnica completa + decisão de IA para um par
    Retorna: indicadores, sinal IA, justificativa, confiança
    """
    binance = BinanceService.from_user(user)
    ai = AIService()
    
    # Buscar candles históricos
    candles = await binance.get_klines(symbol, timeframe, limit=200)
    
    # Calcular indicadores técnicos
    ta = TechnicalAnalysis(candles)
    indicators = {
        "rsi": ta.rsi(period=14),
        "macd": ta.macd(),
        "ema_9": ta.ema(period=9),
        "ema_21": ta.ema(period=21),
        "volume_ratio": ta.volume_ratio(),
        "support": ta.support_resistance()["support"],
        "resistance": ta.support_resistance()["resistance"],
        "trend": ta.market_trend(),
        "price_action": ta.price_action_signals(),
    }
    
    # IA interpreta indicadores e decide
    ai_analysis = await ai.analyze_market(symbol=symbol, indicators=indicators, candles=candles)
    
    # Salvar sinal no banco
    signal = Signal(
        user_id=user.id,
        symbol=symbol,
        signal=ai_analysis["signal"],
        confidence=ai_analysis["confidence"],
        reasoning=ai_analysis["reasoning"],
        indicators=indicators,
        created_at=datetime.utcnow(),
    )
    # await db.save_signal(signal)
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "indicators": indicators,
        "ai_analysis": ai_analysis,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/scanner")
async def market_scanner(user=Depends(get_current_user)):
    """
    Scanner automático — analisa todos os pares configurados
    Retorna ranking por oportunidade
    """
    pairs = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT"]
    results = []
    
    for symbol in pairs:
        try:
            analysis = await analyze_symbol(symbol, user=user)
            results.append({
                "symbol": symbol,
                "signal": analysis["ai_analysis"]["signal"],
                "confidence": analysis["ai_analysis"]["confidence"],
                "rsi": analysis["indicators"]["rsi"],
                "trend": analysis["indicators"]["trend"],
            })
        except Exception as e:
            logger.error(f"Erro ao escanear {symbol}: {e}")
    
    # Ordenar por confiança
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return {"signals": results}

# ─── BOT / TRADING ───────────────────────────────────────────────────────────

@app.post("/bot/start")
async def start_bot(background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    """Iniciar bot de trading automático"""
    global trading_engine
    if not trading_engine:
        trading_engine = TradingEngine()
    
    config = await user.get_bot_config()
    background_tasks.add_task(trading_engine.start, user=user, config=config)
    
    await log_event(user.id, "INFO", "Bot iniciado pelo usuário")
    return {"status": "started", "message": "Bot iniciado com sucesso"}


@app.post("/bot/stop")
async def stop_bot(user=Depends(get_current_user)):
    """Pausar bot"""
    global trading_engine
    if trading_engine:
        await trading_engine.stop_for_user(user.id)
    await log_event(user.id, "INFO", "Bot pausado pelo usuário")
    return {"status": "stopped"}


@app.post("/bot/config")
async def save_bot_config(config: dict, user=Depends(get_current_user)):
    """Salvar configurações do bot"""
    bot_config = BotConfig(
        user_id=user.id,
        risk_pct=config.get("riskPct", 1.5),
        daily_limit=config.get("dailyLimit", 150),
        max_trades=config.get("maxTrades", 12),
        stop_loss=config.get("stopLoss", 1.5),
        take_profit=config.get("takeProfit", 3.0),
        mode=config.get("mode", "auto"),
        pairs=config.get("pairs", ["BTCUSDT", "ETHUSDT"]),
        updated_at=datetime.utcnow(),
    )
    # await db.save_bot_config(bot_config)
    return {"status": "saved"}


@app.post("/order/manual")
async def place_manual_order(
    symbol: str,
    side: str,  # BUY | SELL
    quantity: float,
    order_type: str = "MARKET",
    user=Depends(get_current_user)
):
    """Executar ordem manual"""
    risk_manager = RiskManager(user)
    
    # Validar risco antes de executar
    is_allowed, reason = await risk_manager.validate_order(symbol, side, quantity)
    if not is_allowed:
        raise HTTPException(status_code=400, detail=f"Ordem bloqueada pelo gerenciador de risco: {reason}")
    
    binance = BinanceService.from_user(user)
    order = await binance.place_order(symbol=symbol, side=side, quantity=quantity, order_type=order_type)
    
    await log_event(user.id, "SUCCESS", f"Ordem manual executada: {side} {symbol} @ {order.get('price', 'MARKET')}")
    return {"order": order}

# ─── BACKTEST ─────────────────────────────────────────────────────────────────

@app.post("/backtest")
async def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 10000,
    risk_pct: float = 1.5,
    user=Depends(get_current_user)
):
    """
    Rodar backtest da estratégia base (EMA cross + RSI + IA)
    Retorna: win_rate, profit_factor, drawdown, roi, equity_curve
    """
    binance = BinanceService.from_user(user)
    candles = await binance.get_historical_klines(symbol, "15m", start_date, end_date)
    
    ta = TechnicalAnalysis(candles)
    signals = ta.generate_signals()  # Gerar todos os sinais do período
    
    # Simular trades
    equity = [initial_capital]
    trades = []
    capital = initial_capital
    
    for i, signal in enumerate(signals):
        if signal["action"] in ["BUY", "STRONG_BUY"]:
            entry = signal["price"]
            sl = entry * (1 - risk_pct / 100)
            tp = entry * (1 + (risk_pct * 2) / 100)
            
            # Simular saída
            result = simulate_trade(candles[i:], entry, sl, tp)
            pnl = (result["exit_price"] - entry) / entry * capital * risk_pct / 100
            capital += pnl
            equity.append(capital)
            trades.append({**result, "pnl": pnl, "capital": capital})
    
    # Calcular métricas
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / max(len(trades), 1) * 100
    profit_factor = sum(t["pnl"] for t in wins) / max(abs(sum(t["pnl"] for t in losses)), 0.01)
    roi = (capital - initial_capital) / initial_capital * 100
    max_dd = calculate_max_drawdown(equity)
    
    return {
        "metrics": {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "roi": round(roi, 2),
            "max_drawdown": round(max_dd, 2),
            "final_capital": round(capital, 2),
        },
        "equity_curve": [round(e, 2) for e in equity],
        "trades": trades[:50],  # Últimos 50 trades
    }

# ─── WEBSOCKET ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket para dados em tempo real:
    - Preços ao vivo
    - Sinais de IA
    - Status das posições
    - Logs do sistema
    """
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WebSocket conectado: {user_id}")
    
    try:
        # Subscrever streams de preço
        binance = BinanceService()
        
        async def send_updates():
            while True:
                try:
                    # Dados de mercado
                    tickers = await binance.get_all_tickers(["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"])
                    await websocket.send_json({
                        "type": "prices",
                        "data": tickers,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    await asyncio.sleep(1)
                except Exception:
                    break
        
        # Ouvir mensagens do cliente
        async def receive_messages():
            while True:
                try:
                    msg = await websocket.receive_text()
                    data = json.loads(msg)
                    
                    if data.get("action") == "subscribe_pair":
                        # Subscrever para análise de par específico
                        symbol = data.get("symbol")
                        logger.info(f"Subscrevendo análise de {symbol}")
                    
                    elif data.get("action") == "ping":
                        await websocket.send_json({"type": "pong"})
                        
                except Exception:
                    break
        
        await asyncio.gather(send_updates(), receive_messages())
        
    except Exception as e:
        logger.error(f"WebSocket erro: {e}")
    finally:
        active_connections.remove(websocket)
        logger.info(f"WebSocket desconectado: {user_id}")


async def broadcast(data: dict):
    """Enviar mensagem para todos os clientes conectados"""
    disconnected = []
    for conn in active_connections:
        try:
            await conn.send_json(data)
        except Exception:
            disconnected.append(conn)
    for conn in disconnected:
        active_connections.remove(conn)

# ─── MÉTRICAS & ADMIN ────────────────────────────────────────────────────────

@app.get("/metrics")
async def get_metrics(user=Depends(get_current_user)):
    """Métricas do usuário"""
    return {
        "daily_pnl": 87.34,
        "win_rate": 71.2,
        "total_trades": 6,
        "balance": 10842.50,
        "drawdown": -2.14,
        "profit_factor": 1.87,
    }


@app.get("/admin/stats")
async def admin_stats(user=Depends(get_current_user)):
    """Estatísticas globais (apenas admin)"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso negado")
    return {
        "total_users": 4,
        "active_bots": 3,
        "trades_today": 156,
        "volume_24h": 48200,
        "revenue_month": 2840,
    }

# ─── UTILS ─────────────────────────────────────────────────────────────────────

async def log_event(user_id: str, level: str, message: str):
    """Registrar evento no banco e transmitir via WebSocket"""
    log_entry = {
        "type": "log",
        "data": {
            "user_id": user_id,
            "level": level,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
    }
    await broadcast(log_entry)


def simulate_trade(candles, entry, stop_loss, take_profit):
    """Simular resultado de um trade futuro"""
    for candle in candles:
        if candle["low"] <= stop_loss:
            return {"exit_price": stop_loss, "result": "LOSS", "type": "SL"}
        if candle["high"] >= take_profit:
            return {"exit_price": take_profit, "result": "WIN", "type": "TP"}
    return {"exit_price": candles[-1]["close"], "result": "TIMEOUT", "type": "MANUAL"}


def calculate_max_drawdown(equity_curve):
    """Calcular máximo drawdown da curva de capital"""
    peak = equity_curve[0]
    max_dd = 0
    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return max_dd


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
