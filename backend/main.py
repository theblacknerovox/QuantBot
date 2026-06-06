from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="SMC Quant Bot - Quotex Connector")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, restrinja às URLs da Vercel
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ ENUMS E MODELOS ============
class TradingMode(str, Enum):
    DEMO = "demo"
    REAL = "real"

class TradeRequest(BaseModel):
    asset: str
    amount: float
    direction: str  # "call" ou "put"
    duration: int   # segundos: 60, 120, 300, 600
    mode: TradingMode  # 👈 NOVO: escolhe demo ou real

class OrderResult(BaseModel):
    success: bool
    order_id: Optional[str]
    message: str
    mode_used: str
    balance_after: Optional[float]
    timestamp: str

# ============ GERENCIADOR DA QUOTEX ============
class QuotexManager:
    def __init__(self):
        self.demo_client = None
        self.real_client = None
        self.demo_connected = False
        self.real_connected = False
        self.active_mode = TradingMode.DEMO
        self.daily_loss_demo = 0.0
        self.daily_loss_real = 0.0
        self.streak_losses = 0
        self.daily_loss_limit_percent = 2.0
        self.max_streak_losses = 3
        self.is_killed = False  # Kill Switch ativado?
    
    async def connect_demo(self, email: str, password: str):
        """Conecta à conta DEMO da Quotex"""
        try:
            from quotexpy.stable_api import Quotex
            self.demo_client = Quotex(email=email, password=password, lang="pt")
            await self.demo_client.connect()
            self.demo_client.change_account("PRACTICE")  # FORÇA DEMO
            self.demo_connected = True
            balance = await self.demo_client.get_balance()
            return {"success": True, "balance": balance, "mode": "DEMO"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def connect_real(self, email: str, password: str):
        """Conecta à conta REAL da Quotex (use com cuidado!)"""
        try:
            from quotexpy.stable_api import Quotex
            self.real_client = Quotex(email=email, password=password, lang="pt")
            await self.real_client.connect()
            # NÃO chama change_account para REAL
            self.real_connected = True
            balance = await self.real_client.get_balance()
            
            # LOG de SEGURANÇA - registra ativação do modo real
            self._log_security_event("MODO REAL ATIVADO", f"Saldo: {balance}")
            
            return {"success": True, "balance": balance, "mode": "REAL", "warning": "VOCÊ ESTÁ OPERANDO COM DINHEIRO REAL"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def execute_trade(self, asset: str, amount: float, direction: str, duration: int, mode: TradingMode):
        """Executa trade no modo selecionado"""
        
        # Verifica Kill Switch
        if self.is_killed:
            return {"success": False, "error": "KILL SWITCH ATIVADO - Nenhuma ordem é permitida"}
        
        # Verifica qual cliente usar
        if mode == TradingMode.DEMO:
            if not self.demo_connected:
                return {"success": False, "error": "Modo DEMO não conectado"}
            client = self.demo_client
            current_loss = self.daily_loss_demo
        else:  # REAL
            if not self.real_connected:
                return {"success": False, "error": "Modo REAL não conectado"}
            client = self.real_client
            current_loss = self.daily_loss_real
            
            # ⚠️ AVISO EXTRA PARA MODO REAL
            self._log_security_event("⚠️ ORDEM REAL SENDO EXECUTADA", f"Ativo: {asset}, Valor: ${amount}")
        
        # Verifica Daily Loss Limit
        if current_loss >= self.daily_loss_limit_percent:
            return {"success": False, "error": f"Daily Loss Limit atingido: {current_loss}% > {self.daily_loss_limit_percent}%"}
        
        # Executa a ordem
        try:
            result = await client.buy(
                amount=amount,
                asset=asset,
                direction=direction,
                duration=duration
            )
            
            if result[0]:
                # Atualiza saldo
                new_balance = await client.get_balance()
                
                # Log do trade
                self._log_trade({
                    "mode": mode.value,
                    "asset": asset,
                    "amount": amount,
                    "direction": direction,
                    "duration": duration,
                    "result": "WIN" if result[1].get("win") else "LOSS",
                    "profit": result[1].get("profit", 0),
                    "balance": new_balance
                })
                
                return {
                    "success": True,
                    "order_id": result[1].get("id"),
                    "balance_after": new_balance
                }
            else:
                # Atualiza streak de perdas
                self.streak_losses += 1
                if self.streak_losses >= self.max_streak_losses:
                    self.is_killed = True  # Ativa Kill Switch automático
                
                return {"success": False, "error": result[1]}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_balance(self, mode: TradingMode):
        if mode == TradingMode.DEMO and self.demo_connected:
            return await self.demo_client.get_balance()
        elif mode == TradingMode.REAL and self.real_connected:
            return await self.real_client.get_balance()
        return 0.0
    
    def switch_mode(self, mode: TradingMode):
        """Alterna o modo ativo do bot"""
        self.active_mode = mode
        self._log_security_event(f"Modo alterado para: {mode.value.upper()}", "")
        return {"active_mode": mode.value, "message": f"Bot agora opera em modo {mode.value.upper()}"}
    
    def kill_switch(self):
        """Desativa todas as operações imediatamente"""
        self.is_killed = True
        self._log_security_event("🔴 KILL SWITCH ATIVADO", "Todas as operações foram suspensas")
        return {"status": "killed", "message": "Bot desativado. Nenhuma nova ordem será executada."}
    
    def reset_daily_loss(self):
        """Reseta o contador diário de perdas (usar a cada novo dia)"""
        self.daily_loss_demo = 0.0
        self.daily_loss_real = 0.0
        self.streak_losses = 0
        self.is_killed = False
        return {"status": "reset", "message": "Daily loss counters resetados"}
    
    def _log_trade(self, trade_data):
        """Registra trade em arquivo de log"""
        import json
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            **trade_data
        }
        # Append ao arquivo de log
        with open("trades.log", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    
    def _log_security_event(self, event: str, details: str):
        """Registra eventos de segurança (mudança de modo, kill switch, etc)"""
        import json
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "details": details
        }
        with open("security.log", "a") as f:
            f.write(json.dumps(log_entry) + "\n")

# Instância global
manager = QuotexManager()

# ============ ENDPOINTS ============

@app.get("/")
async def root():
    return {
        "bot": "SMC Institutional Quant Bot",
        "status": "online",
        "active_mode": manager.active_mode.value,
        "demo_connected": manager.demo_connected,
        "real_connected": manager.real_connected,
        "kill_switch_active": manager.is_killed,
        "endpoints": ["/connect-demo", "/connect-real", "/trade", "/balance", "/switch-mode", "/kill-switch", "/reset"]
    }

@app.post("/connect-demo")
async def connect_demo(credentials: dict):
    """Conecta à conta DEMO da Quotex"""
    email = credentials.get("email")
    password = credentials.get("password")
    if not email or not password:
        raise HTTPException(400, "Email e senha obrigatórios")
    result = await manager.connect_demo(email, password)
    if result["success"]:
        return result
    raise HTTPException(401, result["error"])

@app.post("/connect-real")
async def connect_real(credentials: dict):
    """⚠️ Conecta à conta REAL da Quotex - CUIDADO! ⚠️"""
    email = credentials.get("email")
    password = credentials.get("password")
    if not email or not password:
        raise HTTPException(400, "Email e senha obrigatórios")
    
    # CONFIRMAÇÃO OBRIGATÓRIA
    confirm = credentials.get("confirm", False)
    if not confirm:
        raise HTTPException(400, "Para ativar o modo REAL, envie \'confirm\': true no body")
    
    result = await manager.connect_real(email, password)
    if result["success"]:
        return result
    raise HTTPException(401, result["error"])

@app.post("/trade")
async def execute_trade(trade: TradeRequest):
    """Executa uma ordem no modo ativo ou modo especificado"""
    
    # Verifica se o Kill Switch está ativo
    if manager.is_killed:
        raise HTTPException(503, "Kill Switch ativado. Reinicie o bot para operar novamente.")
    
    # Validação de valores
    if trade.amount < 1:
        raise HTTPException(400, "Valor mínimo: $1")
    
    if trade.mode == TradingMode.DEMO and trade.amount > 100:
        raise HTTPException(400, "No modo DEMO, valor máximo é $100")
    
    if trade.mode == TradingMode.REAL and trade.amount > 1000:
        raise HTTPException(400, "No modo REAL, valor máximo é $1000 (configure no arquivo .env se quiser aumentar)")
    
    result = await manager.execute_trade(
        asset=trade.asset,
        amount=trade.amount,
        direction=trade.direction,
        duration=trade.duration,
        mode=trade.mode
    )
    
    return OrderResult(
        success=result["success"],
        order_id=result.get("order_id"),
        message="Ordem executada" if result["success"] else result.get("error", "Falha"),
        mode_used=trade.mode.value,
        balance_after=result.get("balance_after"),
        timestamp=datetime.now().isoformat()
    )

@app.get("/balance")
async def get_balance(mode: Optional[TradingMode] = None):
    """Retorna saldo do modo especificado ou do modo ativo"""
    target_mode = mode or manager.active_mode
    balance = await manager.get_balance(target_mode)
    return {
        "mode": target_mode.value,
        "balance": balance,
        "connected": manager.demo_connected if target_mode == TradingMode.DEMO else manager.real_connected
    }

@app.post("/switch-mode")
async def switch_mode(mode: TradingMode):
    """Alterna entre DEMO e REAL"""
    # Se for mudar para REAL, verifica se está conectado
    if mode == TradingMode.REAL and not manager.real_connected:
        raise HTTPException(400, "Modo REAL não está conectado. Use /connect-real primeiro")
    
    if mode == TradingMode.DEMO and not manager.demo_connected:
        raise HTTPException(400, "Modo DEMO não está conectado. Use /connect-demo primeiro")
    
    result = manager.switch_mode(mode)
    return result

@app.post("/kill-switch")
async def kill_switch():
    """DESATIVA IMEDIATAMENTE todas as operações"""
    return manager.kill_switch()

@app.post("/reset")
async def reset():
    """Reseta Daily Loss e Kill Switch (útil para novo dia de trading)"""
    return manager.reset_daily_loss()

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "active_mode": manager.active_mode.value,
        "kill_switch": manager.is_killed,
        "demo_connected": manager.demo_connected,
        "real_connected": manager.real_connected,
        "daily_loss_demo": manager.daily_loss_demo,
        "daily_loss_real": manager.daily_loss_real,
        "streak_losses": manager.streak_losses
    }
