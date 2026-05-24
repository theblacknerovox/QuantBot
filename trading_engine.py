"""
QuantBot AI — Trading Engine
Loop principal do bot: analisa, decide, executa e monitora posições.
Suporta modos Manual, Semi-automático e 100% Automático.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from services.binance_service import BinanceService
from services.ai_service import AIService
from services.risk_manager import RiskManager
from indicators import TechnicalAnalysis

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 30  # Analisar mercado a cada 30s
MONITOR_INTERVAL_SECONDS = 5  # Monitorar posições abertas a cada 5s


class TradingEngine:
    """
    Motor de execução automática.
    Gerencia múltiplos usuários e múltiplos pares simultaneamente.
    """

    def __init__(self):
        self.active_users: Dict[str, dict] = {}   # user_id -> {task, config, positions}
        self.ai_service = AIService()
        self._running = False

    async def start(self, user, config):
        """Iniciar bot para um usuário."""
        user_id = str(user.id)
        if user_id in self.active_users:
            logger.info(f"Bot já rodando para {user_id}")
            return

        logger.info(f"▶ Iniciando bot para usuário {user_id} | Modo: {config.mode}")
        self.active_users[user_id] = {
            "user": user,
            "config": config,
            "positions": {},
            "running": True,
        }

        # Tarefas paralelas: scanner + monitor de posições
        task_scan = asyncio.create_task(self._scan_loop(user_id))
        task_monitor = asyncio.create_task(self._monitor_loop(user_id))
        self.active_users[user_id]["tasks"] = [task_scan, task_monitor]

    async def stop_for_user(self, user_id: str):
        """Parar bot para um usuário específico."""
        user_id = str(user_id)
        if user_id not in self.active_users:
            return
        self.active_users[user_id]["running"] = False
        for task in self.active_users[user_id].get("tasks", []):
            task.cancel()
        del self.active_users[user_id]
        logger.info(f"⏹ Bot parado para {user_id}")

    async def stop(self):
        """Parar todos os bots."""
        for user_id in list(self.active_users.keys()):
            await self.stop_for_user(user_id)

    # ─── SCAN LOOP ──────────────────────────────────────────────────────────

    async def _scan_loop(self, user_id: str):
        """Loop principal: escaneia mercado e abre posições."""
        state = self.active_users.get(user_id)
        if not state:
            return

        user = state["user"]
        config = state["config"]
        binance = BinanceService.from_user(user)
        risk_mgr = RiskManager(user)

        while state.get("running"):
            try:
                # Só operar em modo automático
                if config.mode not in ["auto", "semi"]:
                    await asyncio.sleep(SCAN_INTERVAL_SECONDS)
                    continue

                for symbol in config.pairs:
                    if not state.get("running"):
                        break

                    # Já tem posição aberta neste par?
                    if symbol in state["positions"]:
                        continue

                    await self._analyze_and_trade(
                        user_id=user_id,
                        symbol=symbol,
                        binance=binance,
                        risk_mgr=risk_mgr,
                        config=config,
                        mode=config.mode,
                    )
                    await asyncio.sleep(1)  # Pausa entre pares

                await asyncio.sleep(SCAN_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no scan loop ({user_id}): {e}")
                await asyncio.sleep(10)

    async def _analyze_and_trade(self, user_id, symbol, binance, risk_mgr, config, mode):
        """Analisar um par e executar se houver sinal."""
        try:
            # 1. Buscar candles
            candles = await binance.get_klines(symbol, "15m", limit=200)
            if len(candles) < 50:
                return

            # 2. Calcular indicadores
            ta = TechnicalAnalysis(candles)
            indicators = ta.full_analysis()

            # 3. IA decide
            analysis = await self.ai_service.analyze_market(
                symbol=symbol,
                indicators=indicators,
                candles=candles,
                user_id=user_id,
            )

            signal = analysis["signal"]
            confidence = analysis["confidence"]

            logger.info(f"[{symbol}] Sinal: {signal} | Confiança: {confidence}%")

            # 4. Filtro de qualidade
            min_confidence = 65
            if confidence < min_confidence:
                logger.debug(f"[{symbol}] Confiança insuficiente ({confidence}% < {min_confidence}%)")
                return

            # 5. Semi-auto: apenas gerar alerta, não executar
            if mode == "semi":
                await self._send_signal_alert(user_id, symbol, analysis)
                return

            # 6. Auto: executar ordem
            if signal in ["FORTE COMPRA", "COMPRA"]:
                await self._open_long(user_id, symbol, analysis, binance, risk_mgr, config)
            elif signal in ["FORTE VENDA", "VENDA"]:
                await self._open_short(user_id, symbol, analysis, binance, risk_mgr, config)

        except Exception as e:
            logger.error(f"Erro em analyze_and_trade ({symbol}): {e}")

    async def _open_long(self, user_id, symbol, analysis, binance, risk_mgr, config):
        """Abrir posição LONG com TP/SL."""
        # Validar risco
        is_allowed, reason = await risk_mgr.validate_order(symbol, "BUY", 0)
        if not is_allowed:
            logger.warning(f"[{symbol}] LONG bloqueado: {reason}")
            return

        try:
            balance = await binance.get_usdt_balance()
            entry = analysis["entry_price"] or (await binance.get_price(symbol))
            sl = analysis["stop_loss"] or entry * (1 - float(config.stop_loss) / 100)
            tp = analysis["take_profit"] or entry * (1 + float(config.take_profit) / 100)

            quantity = risk_mgr.get_position_size(balance, float(config.risk_pct), entry, sl)
            if quantity <= 0:
                logger.warning(f"[{symbol}] Quantidade calculada inválida")
                return

            # Executar ordem de mercado
            order = await binance.place_order(symbol, "BUY", quantity, "MARKET")
            order_id = order.get("orderId")

            # Registrar posição
            self.active_users[user_id]["positions"][symbol] = {
                "order_id": order_id,
                "side": "LONG",
                "entry": entry,
                "quantity": quantity,
                "stop_loss": sl,
                "take_profit": tp,
                "opened_at": datetime.utcnow().isoformat(),
                "analysis": analysis,
            }

            logger.info(f"✅ LONG aberto: {symbol} @ {entry:.4f} | TP: {tp:.4f} | SL: {sl:.4f}")
            await self._broadcast_trade_event(user_id, "OPENED", symbol, "LONG", entry, tp, sl)

        except Exception as e:
            logger.error(f"Erro ao abrir LONG {symbol}: {e}")

    async def _open_short(self, user_id, symbol, analysis, binance, risk_mgr, config):
        """Abrir posição SHORT (requer conta Futures)."""
        is_allowed, reason = await risk_mgr.validate_order(symbol, "SELL", 0)
        if not is_allowed:
            logger.warning(f"[{symbol}] SHORT bloqueado: {reason}")
            return
        # Implementação similar ao _open_long mas com side=SELL e Futures API
        logger.info(f"[{symbol}] SHORT signal detectado — implementar Futures")

    # ─── MONITOR LOOP ────────────────────────────────────────────────────────

    async def _monitor_loop(self, user_id: str):
        """Monitorar posições abertas: TP, SL, trailing stop."""
        state = self.active_users.get(user_id)
        if not state:
            return

        user = state["user"]
        binance = BinanceService.from_user(user)
        risk_mgr = RiskManager(user)

        while state.get("running"):
            try:
                positions = dict(state["positions"])  # Cópia para iterar
                for symbol, pos in positions.items():
                    current_price = await binance.get_price(symbol)
                    await self._check_exit_conditions(
                        user_id, symbol, pos, current_price, binance, risk_mgr
                    )
                    await asyncio.sleep(0.5)

                await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no monitor loop ({user_id}): {e}")
                await asyncio.sleep(5)

    async def _check_exit_conditions(self, user_id, symbol, pos, current_price, binance, risk_mgr):
        """Verificar se deve fechar posição (TP/SL atingido)."""
        entry = pos["entry"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        side = pos["side"]

        exit_reason = None
        exit_price = current_price

        if side == "LONG":
            if current_price >= tp:
                exit_reason = "TAKE_PROFIT"
            elif current_price <= sl:
                exit_reason = "STOP_LOSS"
        elif side == "SHORT":
            if current_price <= tp:
                exit_reason = "TAKE_PROFIT"
            elif current_price >= sl:
                exit_reason = "STOP_LOSS"

        if exit_reason:
            await self._close_position(user_id, symbol, pos, exit_price, exit_reason, binance, risk_mgr)

    async def _close_position(self, user_id, symbol, pos, exit_price, reason, binance, risk_mgr):
        """Fechar posição e registrar resultado."""
        try:
            close_side = "SELL" if pos["side"] == "LONG" else "BUY"
            await binance.place_order(symbol, close_side, pos["quantity"], "MARKET")

            # Calcular P&L
            if pos["side"] == "LONG":
                pnl = (exit_price - pos["entry"]) * pos["quantity"]
            else:
                pnl = (pos["entry"] - exit_price) * pos["quantity"]

            result = "WIN" if pnl > 0 else "LOSS"
            risk_mgr.record_trade_result(pnl)
            self.ai_service.record_outcome(user_id, pos["analysis"], result, pnl)

            # Remover posição
            if symbol in self.active_users[user_id]["positions"]:
                del self.active_users[user_id]["positions"][symbol]

            logger.info(
                f"{'✅' if result == 'WIN' else '❌'} {symbol} fechado [{reason}] "
                f"@ {exit_price:.4f} | PnL: ${pnl:.2f}"
            )
            await self._broadcast_trade_event(user_id, "CLOSED", symbol, pos["side"],
                                               exit_price, pnl=pnl, reason=reason)

        except Exception as e:
            logger.error(f"Erro ao fechar posição {symbol}: {e}")

    # ─── HELPERS ─────────────────────────────────────────────────────────────

    async def _send_signal_alert(self, user_id, symbol, analysis):
        """Enviar alerta via WebSocket e Telegram (modo semi-auto)."""
        logger.info(f"[SEMI-AUTO] Sinal {analysis['signal']} em {symbol} | "
                    f"Confiança: {analysis['confidence']}%")
        # await telegram_service.send_signal(user_id, symbol, analysis)
        # await websocket_broadcast(user_id, {"type": "signal", "data": analysis})

    async def _broadcast_trade_event(self, user_id, event_type, symbol, side,
                                      price, tp=None, sl=None, pnl=None, reason=None):
        """Transmitir evento de trade via WebSocket."""
        payload = {
            "type": "trade_event",
            "event": event_type,
            "symbol": symbol,
            "side": side,
            "price": price,
            "tp": tp,
            "sl": sl,
            "pnl": pnl,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        # await websocket_manager.broadcast_to_user(user_id, payload)
        # await telegram_service.send_trade_update(user_id, payload)
        logger.info(f"Trade event: {payload}")
