"""Trade signals: typed shapes per source, a symbol map, one decision engine, one dispatcher.

    incoming signal  ->  SignalEngine.decide()  ->  OrderPlan  ->  BrokerDispatcher.send()

The engine owns every validation. The dispatcher owns the broker call. Nothing else decides.
"""

from .dispatch import BrokerDispatcher, Outcome
from .engine import Context, OrderPlan, Refusal, SignalEngine
from .shapes import BaseSignal, ChainSignal, P01Signal, R01Signal, parse_signal
from .symbols import SymbolMap, SymbolMapping

__all__ = [
    "BaseSignal", "BrokerDispatcher", "ChainSignal", "Context", "OrderPlan", "Outcome", "P01Signal",
    "R01Signal", "Refusal", "SignalEngine", "SymbolMap", "SymbolMapping", "parse_signal",
]
