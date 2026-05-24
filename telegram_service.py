"""
QuantBot AI — Telegram Service
Alertas de sinais, trades abertos/fechados e erros do sistema.
"""

import logging
import aiohttp
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot"

# Emojis para formatação das mensagens
EMOJI = {
    "FORTE COMPRA": "🚀",
    "COMPRA":       "📈",
    "NEUTRO":       "➖",
    "VENDA":        "📉",
    "FORTE VENDA":  "💥",
    "WIN":          "✅",
    "LOSS":         "❌",
    "INFO":         "ℹ️",
    "WARN":         "⚠️",
    "ERROR":        "🔴",
    "BOT_START":    "▶️",
    "BOT_STOP":     "⏹",
}


class TelegramService:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"{TELEGRAM_API}{token}"

    @classmethod
    def from_user(cls, user) -> Optional["TelegramService"]:
        token = user.telegram_token
        chat_id = user.telegram_chat_id
        if not token or not chat_id:
            return None
        return cls(token=token, chat_id=chat_id)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Enviar mensagem ao chat do usuário."""
        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True
                    logger.error(f"Telegram error {resp.status}: {await resp.text()}")
                    return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def send_signal(self, symbol: str, analysis: dict) -> bool:
        """Alerta de novo sinal gerado pela IA."""
        signal = analysis.get("signal", "NEUTRO")
        confidence = analysis.get("confidence", 0)
        reasoning = analysis.get("reasoning", "")
        entry = analysis.get("entry_price")
        sl = analysis.get("stop_loss")
        tp = analysis.get("take_profit")
        rr = analysis.get("risk_reward")

        emoji = EMOJI.get(signal, "📊")
        now = datetime.utcnow().strftime("%H:%M:%S UTC")

        lines = [
            f"{emoji} <b>SINAL IA — {symbol}</b>",
            f"⏰ {now}",
            f"",
            f"📊 <b>Classificação:</b> {signal}",
            f"🎯 <b>Confiança:</b> {confidence}%",
        ]

        if entry:
            lines.append(f"💰 <b>Entrada:</b> ${entry:.4f}")
        if tp:
            lines.append(f"✅ <b>Take Profit:</b> ${tp:.4f}")
        if sl:
            lines.append(f"🛑 <b>Stop Loss:</b> ${sl:.4f}")
        if rr:
            lines.append(f"⚖️ <b>Risco/Retorno:</b> {rr:.1f}x")

        if reasoning:
            lines.extend(["", f"💬 <i>{reasoning[:300]}</i>"])

        return await self.send_message("\n".join(lines))

    async def send_trade_opened(self, symbol: str, side: str, entry: float,
                                 tp: float, sl: float, quantity: float) -> bool:
        """Notificação de trade aberto."""
        side_label = "LONG 📈" if side == "LONG" else "SHORT 📉"
        now = datetime.utcnow().strftime("%H:%M:%S UTC")

        text = (
            f"🟢 <b>TRADE ABERTO — {symbol}</b>\n"
            f"⏰ {now}\n\n"
            f"📌 <b>Lado:</b> {side_label}\n"
            f"💰 <b>Entrada:</b> ${entry:.4f}\n"
            f"📦 <b>Quantidade:</b> {quantity}\n"
            f"✅ <b>Take Profit:</b> ${tp:.4f}\n"
            f"🛑 <b>Stop Loss:</b> ${sl:.4f}"
        )
        return await self.send_message(text)

    async def send_trade_closed(self, symbol: str, side: str, entry: float,
                                 exit_price: float, pnl: float, reason: str) -> bool:
        """Notificação de trade fechado."""
        result = "WIN" if pnl > 0 else "LOSS"
        emoji = EMOJI[result]
        pnl_sign = "+" if pnl >= 0 else ""
        now = datetime.utcnow().strftime("%H:%M:%S UTC")

        text = (
            f"{emoji} <b>TRADE FECHADO — {symbol}</b>\n"
            f"⏰ {now}\n\n"
            f"📌 <b>Lado:</b> {side}\n"
            f"🔵 <b>Entrada:</b> ${entry:.4f}\n"
            f"🔴 <b>Saída:</b> ${exit_price:.4f}\n"
            f"💵 <b>P&L:</b> <b>{pnl_sign}${pnl:.2f}</b>\n"
            f"📋 <b>Motivo:</b> {reason}"
        )
        return await self.send_message(text)

    async def send_daily_summary(self, metrics: dict) -> bool:
        """Resumo diário enviado às 23:59."""
        pnl = metrics.get("daily_pnl", 0)
        win_rate = metrics.get("win_rate", 0)
        trades = metrics.get("total_trades", 0)
        balance = metrics.get("balance", 0)

        pnl_sign = "+" if pnl >= 0 else ""
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        today = datetime.utcnow().strftime("%d/%m/%Y")

        text = (
            f"📊 <b>RESUMO DO DIA — {today}</b>\n\n"
            f"{pnl_emoji} <b>P&L:</b> {pnl_sign}${pnl:.2f}\n"
            f"🎯 <b>Win Rate:</b> {win_rate:.1f}%\n"
            f"📋 <b>Trades:</b> {trades}\n"
            f"💼 <b>Saldo:</b> ${balance:.2f}\n\n"
            f"Bom descanso! O bot continua monitorando. 🤖"
        )
        return await self.send_message(text)

    async def send_risk_alert(self, reason: str) -> bool:
        """Alerta de risco crítico."""
        text = (
            f"⚠️ <b>ALERTA DE RISCO</b>\n\n"
            f"🛑 {reason}\n\n"
            f"⏰ {datetime.utcnow().strftime('%H:%M:%S UTC')}"
        )
        return await self.send_message(text)

    async def send_error(self, error_msg: str) -> bool:
        """Notificação de erro do sistema."""
        text = (
            f"🔴 <b>ERRO DO SISTEMA</b>\n\n"
            f"<code>{error_msg[:500]}</code>\n\n"
            f"⏰ {datetime.utcnow().strftime('%H:%M:%S UTC')}"
        )
        return await self.send_message(text)

    async def send_bot_status(self, status: str, details: str = "") -> bool:
        """Mudança de status do bot (iniciado/parado)."""
        emoji = EMOJI.get(f"BOT_{status}", "🤖")
        text = (
            f"{emoji} <b>BOT {status}</b>\n"
            f"{details}\n"
            f"⏰ {datetime.utcnow().strftime('%H:%M:%S UTC')}"
        )
        return await self.send_message(text)
