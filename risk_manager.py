"""
QuantBot AI — Gerenciador de Risco
Proteção contra overtrade, sequência de perdas e volatilidade extrema.
"""

import logging
from datetime import datetime, date
from typing import Tuple, Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    daily_loss: float = 0.0
    daily_trades: int = 0
    consecutive_losses: int = 0
    last_reset: str = ""
    paused_until: Optional[str] = None


class RiskManager:
    """
    Gerenciamento de risco em tempo real.
    Validado antes de TODA execução de ordem.
    """

    def __init__(self, user):
        self.user = user
        self.state = RiskState(last_reset=str(date.today()))

    def _reset_daily_if_needed(self):
        today = str(date.today())
        if self.state.last_reset != today:
            self.state.daily_loss = 0.0
            self.state.daily_trades = 0
            self.state.consecutive_losses = 0
            self.state.last_reset = today
            logger.info(f"Risk state resetado para {self.user.id}")

    async def validate_order(self, symbol: str, side: str, quantity: float) -> Tuple[bool, str]:
        """
        Validar se a ordem pode ser executada.
        Retorna (permitido, motivo).
        """
        self._reset_daily_if_needed()
        config = await self.user.get_bot_config()

        # 1. Bot pausado manualmente
        if self.state.paused_until:
            paused_dt = datetime.fromisoformat(self.state.paused_until)
            if datetime.utcnow() < paused_dt:
                return False, f"Bot pausado até {self.state.paused_until}"
            else:
                self.state.paused_until = None

        # 2. Limite diário de perda atingido
        if self.state.daily_loss >= float(config.daily_limit):
            return False, f"Limite diário de perda atingido (${self.state.daily_loss:.2f} / ${config.daily_limit})"

        # 3. Máximo de trades por dia
        if self.state.daily_trades >= int(config.max_trades):
            return False, f"Máximo de trades diários atingido ({self.state.daily_trades}/{config.max_trades})"

        # 4. Sequência de perdas — pausa automática após 3 consecutivas
        if self.state.consecutive_losses >= 3:
            pause_minutes = self.state.consecutive_losses * 30  # 90min após 3 perdas
            self.pause(minutes=pause_minutes)
            return False, f"Pausa automática após {self.state.consecutive_losses} perdas consecutivas ({pause_minutes}min)"

        # 5. Volatilidade extrema (placeholder — integrar com ATR real)
        # if await self._is_extreme_volatility(symbol):
        #     return False, "Volatilidade extrema detectada — operação bloqueada"

        return True, "OK"

    def record_trade_result(self, pnl: float):
        """Registrar resultado de um trade e atualizar estado de risco."""
        self._reset_daily_if_needed()
        self.state.daily_trades += 1

        if pnl < 0:
            self.state.daily_loss += abs(pnl)
            self.state.consecutive_losses += 1
            logger.warning(
                f"Trade perdedor registrado: ${pnl:.2f} | "
                f"Perdas consecutivas: {self.state.consecutive_losses} | "
                f"Perda diária: ${self.state.daily_loss:.2f}"
            )
        else:
            self.state.consecutive_losses = 0  # Reset em vitória
            logger.info(f"Trade vencedor registrado: ${pnl:.2f}")

    def pause(self, minutes: int = 60):
        """Pausar bot por N minutos."""
        from datetime import timedelta
        until = datetime.utcnow() + timedelta(minutes=minutes)
        self.state.paused_until = until.isoformat()
        logger.warning(f"Bot pausado por {minutes} minutos até {self.state.paused_until}")

    def get_position_size(self, balance: float, risk_pct: float, entry: float, stop_loss: float) -> float:
        """
        Calcular tamanho de posição baseado no risco percentual.
        Formula: quantidade = (balance * risk_pct/100) / (entry - stop_loss)
        """
        if entry <= stop_loss or stop_loss <= 0:
            return 0.0
        risk_amount = balance * (risk_pct / 100)
        risk_per_unit = abs(entry - stop_loss)
        quantity = risk_amount / risk_per_unit
        return round(quantity, 6)

    def get_risk_summary(self) -> Dict:
        self._reset_daily_if_needed()
        return {
            "daily_loss": round(self.state.daily_loss, 2),
            "daily_trades": self.state.daily_trades,
            "consecutive_losses": self.state.consecutive_losses,
            "paused_until": self.state.paused_until,
            "last_reset": self.state.last_reset,
        }
