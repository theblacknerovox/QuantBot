"""
QuantBot AI — Motor de Inteligência Artificial
Integração com OpenAI / Gemini para análise e decisão de mercado.
Inclui memória operacional que aprende com o histórico de trades.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class AIMemory:
    """Memória operacional — registra e aprende com trades passados"""
    winning_conditions: List[Dict]    # Condições que geraram trades vencedores
    losing_conditions: List[Dict]     # Condições que geraram trades perdedores
    filter_adjustments: Dict          # Ajustes aprendidos nos filtros
    total_analyses: int
    last_updated: str


# ─── PROMPTS ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Você é um analista quantitativo expert em day trading de criptomoedas.
Sua função é analisar indicadores técnicos e decidir se é momento de entrar ou sair de uma operação.

PRINCÍPIOS FUNDAMENTAIS:
1. Preservação de capital é sempre prioritária
2. Só confirme entradas com alta probabilidade de sucesso
3. Evite mercados laterais sem tendência clara
4. Volume precisa confirmar o movimento
5. Múltiplos indicadores devem convergir para o mesmo sinal

CLASSIFICAÇÕES:
- FORTE COMPRA: 4-5 indicadores bullish convergindo, volume alto, tendência clara de alta
- COMPRA: 3 indicadores bullish, setup razoável, risco controlado
- NEUTRO: mercado lateral, indicadores mistos, sem entrada justificada
- VENDA: 3+ indicadores bearish, sobrecompra, tendência de baixa
- FORTE VENDA: RSI sobrecomprado, bearish engulfing, volume de venda alto

SEMPRE responda em JSON válido com os campos:
{
  "signal": "FORTE COMPRA|COMPRA|NEUTRO|VENDA|FORTE VENDA",
  "confidence": 0-100,
  "reasoning": "explicação detalhada em português",
  "entry_price": número ou null,
  "stop_loss": número ou null,  
  "take_profit": número ou null,
  "risk_reward": número ou null,
  "avoid_reasons": ["razão1", "razão2"] ou [],
  "key_levels": {"support": número, "resistance": número}
}"""


def build_analysis_prompt(symbol: str, indicators: Dict, memory: Optional[AIMemory] = None) -> str:
    """Construir prompt de análise com indicadores e memória operacional"""
    
    rsi = indicators.get("rsi", 50)
    macd = indicators.get("macd", {})
    trend = indicators.get("trend", "UNKNOWN")
    vol_ratio = indicators.get("volume_ratio", 1.0)
    support = indicators.get("support", 0)
    resistance = indicators.get("resistance", 0)
    price_action = indicators.get("price_action", {})
    current_price = indicators.get("current_price", 0)
    ema_9 = indicators.get("ema_9", 0)
    ema_21 = indicators.get("ema_21", 0)
    bb = indicators.get("bollinger", {})
    
    prompt = f"""
## Análise de Mercado — {symbol}
**Preço Atual:** ${current_price:.4f}

### Indicadores Técnicos

**Trend (EMA 9/21):**
- EMA 9: ${ema_9:.4f}
- EMA 21: ${ema_21:.4f}
- Estado: {trend}

**RSI (14):** {rsi}
- Interpretação: {"SOBRECOMPRA ⚠️" if rsi > 70 else "SOBREVENDA 🟢" if rsi < 30 else "NEUTRO"}

**MACD:**
- Linha MACD: {macd.get('macd', 0):.6f}
- Linha Sinal: {macd.get('signal', 0):.6f}
- Histograma: {macd.get('histogram', 0):.6f}
- Tendência: {macd.get('trend', 'N/A')}
- Cruzamento Bullish: {macd.get('bullish_cross', False)}
- Cruzamento Bearish: {macd.get('bearish_cross', False)}

**Volume:**
- Ratio vs Média 20: {vol_ratio}x
- Classificação: {"ALTO ✅" if vol_ratio > 1.5 else "NORMAL" if vol_ratio > 0.8 else "BAIXO ⚠️"}

**Price Action:**
- Padrão: {price_action.get('pattern', 'NONE')}
- Viés: {price_action.get('bias', 'NEUTRAL')}

**Bollinger Bands:**
- Superior: ${bb.get('upper', 0):.4f}
- Médio: ${bb.get('middle', 0):.4f}
- Inferior: ${bb.get('lower', 0):.4f}
- Posição: {bb.get('position', 'INSIDE')}

**Suporte e Resistência:**
- Suporte: ${support:.4f}
- Resistência: ${resistance:.4f}
- Distância ao suporte: {abs(current_price - support) / current_price * 100:.2f}%
- Distância à resistência: {abs(resistance - current_price) / current_price * 100:.2f}%
"""

    if memory and memory.total_analyses > 10:
        prompt += f"""
### Memória Operacional (últimas {memory.total_analyses} análises)
**Filtros aprendidos:**
{json.dumps(memory.filter_adjustments, indent=2)}

**Padrão de trades vencedores recentes:**
{json.dumps(memory.winning_conditions[-3:] if memory.winning_conditions else [], indent=2)}

Considere esses padrões ao fazer sua análise.
"""

    prompt += "\n\nAnalise todos os indicadores e retorne sua decisão em JSON."
    return prompt


# ─── AI SERVICE ─────────────────────────────────────────────────────────────────

class AIService:
    """
    Serviço de IA — suporta OpenAI e Google Gemini.
    Inclui fallback local baseado em regras para modo offline.
    """
    
    def __init__(self):
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.provider = os.getenv("AI_PROVIDER", "openai")  # openai | gemini | rules
        self.memory_store: Dict[str, AIMemory] = {}  # user_id -> memory
    
    async def analyze_market(
        self,
        symbol: str,
        indicators: Dict,
        candles: list,
        user_id: Optional[str] = None,
    ) -> Dict:
        """
        Análise principal de mercado.
        Usa IA se disponível, fallback para motor de regras.
        """
        memory = self.memory_store.get(user_id) if user_id else None
        
        try:
            if self.provider == "openai" and self.openai_key:
                return await self._analyze_openai(symbol, indicators, memory)
            elif self.provider == "gemini" and self.gemini_key:
                return await self._analyze_gemini(symbol, indicators, memory)
            else:
                return self._analyze_rules(symbol, indicators)
        except Exception as e:
            logger.error(f"Erro na análise IA: {e}")
            return self._analyze_rules(symbol, indicators)  # Fallback seguro
    
    async def _analyze_openai(self, symbol: str, indicators: Dict, memory: Optional[AIMemory]) -> Dict:
        """Análise via OpenAI GPT-4"""
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self.openai_key)
            
            prompt = build_analysis_prompt(symbol, indicators, memory)
            
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,  # Baixa temperatura = mais determinístico
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            
            result = json.loads(response.choices[0].message.content)
            return self._normalize_result(result, symbol)
            
        except Exception as e:
            logger.error(f"Erro OpenAI: {e}")
            raise
    
    async def _analyze_gemini(self, symbol: str, indicators: Dict, memory: Optional[AIMemory]) -> Dict:
        """Análise via Google Gemini"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.gemini_key)
            model = genai.GenerativeModel("gemini-1.5-pro")
            
            prompt = f"{SYSTEM_PROMPT}\n\n{build_analysis_prompt(symbol, indicators, memory)}"
            
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=800,
                ),
            )
            
            # Extrair JSON da resposta
            text = response.text
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            result = json.loads(text[json_start:json_end])
            return self._normalize_result(result, symbol)
            
        except Exception as e:
            logger.error(f"Erro Gemini: {e}")
            raise
    
    def _analyze_rules(self, symbol: str, indicators: Dict) -> Dict:
        """
        Motor de regras local — fallback sem API.
        Implementa a estratégia base do sistema.
        """
        rsi = indicators.get("rsi", 50)
        macd = indicators.get("macd", {})
        trend = indicators.get("trend", "SIDEWAYS")
        vol_ratio = indicators.get("volume_ratio", 1.0)
        price_action = indicators.get("price_action", {})
        current = indicators.get("current_price", 0)
        support = indicators.get("support", current * 0.98)
        resistance = indicators.get("resistance", current * 1.02)
        
        score = 0
        reasons = []
        avoid_reasons = []
        
        # ─── SCORING BULLISH ──────────────────────────────────────────────────
        if trend in ["CROSSOVER_BULLISH"]:
            score += 30
            reasons.append("EMA 9 cruzou EMA 21 para cima — sinal bullish primário")
        elif trend == "BULLISH":
            score += 15
            reasons.append("EMAs em configuração bullish")
        
        if rsi < 30:
            score += 25
            reasons.append(f"RSI em sobrevenda ({rsi:.1f}) — potencial reversão de alta")
        elif 30 <= rsi <= 55:
            score += 15
            reasons.append(f"RSI em zona neutra-favorável ({rsi:.1f})")
        elif rsi > 70:
            score -= 30
            avoid_reasons.append(f"RSI sobrecomprado ({rsi:.1f}) — risco de reversão")
        
        if macd.get("bullish_cross"):
            score += 25
            reasons.append("Cruzamento bullish no MACD")
        elif macd.get("trend") == "BULLISH":
            score += 10
            reasons.append("MACD acima da linha de sinal")
        elif macd.get("bearish_cross"):
            score -= 25
            avoid_reasons.append("Cruzamento bearish no MACD")
        
        if vol_ratio > 1.5:
            score += 20
            reasons.append(f"Volume {vol_ratio:.1f}x acima da média — confirmação de movimento")
        elif vol_ratio < 0.7:
            score -= 10
            avoid_reasons.append("Volume baixo — sem confirmação")
        
        if price_action.get("bias") == "BULLISH":
            score += 15
            reasons.append(f"Padrão bullish: {price_action.get('pattern')}")
        elif price_action.get("bias") == "BEARISH":
            score -= 15
            avoid_reasons.append(f"Padrão baixista: {price_action.get('pattern')}")
        
        # Distância ao suporte
        dist_support = abs(current - support) / current
        if dist_support < 0.005:  # Próximo ao suporte (<0.5%)
            score += 10
            reasons.append("Preço próximo ao suporte — bom ponto de entrada")
        
        # ─── CLASSIFICAÇÃO FINAL ──────────────────────────────────────────────
        if score >= 70:
            signal = "FORTE COMPRA"
            confidence = min(score, 92)
        elif score >= 40:
            signal = "COMPRA"
            confidence = min(score, 75)
        elif score <= -50:
            signal = "FORTE VENDA"
            confidence = min(abs(score), 88)
        elif score <= -25:
            signal = "VENDA"
            confidence = min(abs(score), 72)
        else:
            signal = "NEUTRO"
            confidence = max(30, 60 - abs(score))
            avoid_reasons.append("Indicadores não convergem para entrada clara")
        
        # Calcular níveis de TP/SL
        atr = indicators.get("atr", current * 0.01)
        if "COMPRA" in signal:
            sl = max(support, current - atr * 1.5)
            tp = min(resistance, current + atr * 3.0)
        elif "VENDA" in signal:
            sl = min(resistance, current + atr * 1.5)
            tp = max(support, current - atr * 3.0)
        else:
            sl = tp = None
        
        rr = abs(tp - current) / abs(current - sl) if sl and tp and abs(current - sl) > 0 else None
        
        reasoning = " | ".join(reasons) if reasons else "Mercado lateral sem setup claro."
        if avoid_reasons:
            reasoning += f" ⚠️ Atenção: {'; '.join(avoid_reasons)}."
        
        return {
            "signal": signal,
            "confidence": int(confidence),
            "reasoning": reasoning,
            "entry_price": current,
            "stop_loss": round(sl, 8) if sl else None,
            "take_profit": round(tp, 8) if tp else None,
            "risk_reward": round(rr, 2) if rr else None,
            "avoid_reasons": avoid_reasons,
            "key_levels": {"support": support, "resistance": resistance},
            "provider": "rules_engine",
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    def _normalize_result(self, raw: Dict, symbol: str) -> Dict:
        """Normalizar e validar resultado da IA"""
        valid_signals = {"FORTE COMPRA", "COMPRA", "NEUTRO", "VENDA", "FORTE VENDA"}
        signal = raw.get("signal", "NEUTRO").upper()
        if signal not in valid_signals:
            signal = "NEUTRO"
        
        return {
            "signal": signal,
            "confidence": max(0, min(100, int(raw.get("confidence", 50)))),
            "reasoning": str(raw.get("reasoning", "")),
            "entry_price": raw.get("entry_price"),
            "stop_loss": raw.get("stop_loss"),
            "take_profit": raw.get("take_profit"),
            "risk_reward": raw.get("risk_reward"),
            "avoid_reasons": raw.get("avoid_reasons", []),
            "key_levels": raw.get("key_levels", {}),
            "provider": "ai",
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    # ─── MEMÓRIA OPERACIONAL ──────────────────────────────────────────────────
    
    def record_outcome(self, user_id: str, analysis: Dict, outcome: str, pnl: float):
        """
        Registrar resultado de um trade para aprendizado.
        outcome: 'WIN' | 'LOSS' | 'BREAKEVEN'
        """
        if user_id not in self.memory_store:
            self.memory_store[user_id] = AIMemory(
                winning_conditions=[],
                losing_conditions=[],
                filter_adjustments={},
                total_analyses=0,
                last_updated=datetime.utcnow().isoformat(),
            )
        
        memory = self.memory_store[user_id]
        memory.total_analyses += 1
        
        condition_snapshot = {
            "signal": analysis.get("signal"),
            "confidence": analysis.get("confidence"),
            "symbol": analysis.get("symbol"),
            "pnl": pnl,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if outcome == "WIN":
            memory.winning_conditions.append(condition_snapshot)
            memory.winning_conditions = memory.winning_conditions[-20:]  # Manter últimas 20
        else:
            memory.losing_conditions.append(condition_snapshot)
            memory.losing_conditions = memory.losing_conditions[-20:]
        
        # Ajustar filtros baseado no histórico
        self._update_filters(memory)
        memory.last_updated = datetime.utcnow().isoformat()
        
        logger.info(f"Memória atualizada para {user_id}: {outcome} | PnL: {pnl:.2f}")
    
    def _update_filters(self, memory: AIMemory):
        """Atualizar filtros de entrada baseado no histórico"""
        if len(memory.winning_conditions) < 5:
            return
        
        wins = memory.winning_conditions
        losses = memory.losing_conditions
        
        # Calcular win rate por sinal
        win_signals = [w["signal"] for w in wins]
        loss_signals = [l["signal"] for l in losses]
        
        all_signals = set(win_signals + loss_signals)
        signal_stats = {}
        
        for sig in all_signals:
            sig_wins = win_signals.count(sig)
            sig_losses = loss_signals.count(sig)
            total = sig_wins + sig_losses
            if total > 0:
                signal_stats[sig] = {
                    "win_rate": sig_wins / total,
                    "total": total,
                }
        
        # Ajuste de confiança mínima baseado no histórico
        avg_win_confidence = sum(w["confidence"] for w in wins) / max(len(wins), 1)
        avg_loss_confidence = sum(l["confidence"] for l in losses) / max(len(losses), 1)
        
        memory.filter_adjustments = {
            "min_confidence": max(50, avg_win_confidence - 10),
            "signal_win_rates": signal_stats,
            "avg_win_confidence": round(avg_win_confidence, 1),
            "avg_loss_confidence": round(avg_loss_confidence, 1),
        }
