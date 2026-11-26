"""Custo em R$ com tarifa e bandeira (dados/tarifas.json)."""
from __future__ import annotations
from .dados import tarifas


def preco_kwh(bandeira: str | None = None, cfg: dict | None = None) -> float:
    c = cfg or tarifas()
    b = bandeira or c.get("bandeira_atual", "verde")
    return float(c["tarifa_kwh_com_tributos"]) + float(c["bandeiras_adicional_por_kwh"].get(b, 0.0))


def custo(kwh: float, bandeira: str | None = None, cfg: dict | None = None) -> float:
    return round(kwh * preco_kwh(bandeira, cfg), 2)
