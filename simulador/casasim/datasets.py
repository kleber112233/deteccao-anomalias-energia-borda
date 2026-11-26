"""Leitura dos datasets congelados (ferramentas/gerar_datasets.py)."""
from __future__ import annotations
from pathlib import Path

ROTULOS = ["anomalia", "falha_id", "falha_tipo", "canal_direto"]


def carregar(pasta: str | Path, particao: str = "treino", com_rotulos: bool = False, colunas: list[str] | None = None):
    """Lê uma partição ('treino', 'calibracao' ou 'teste'). Por padrão SEM as colunas de gabarito."""
    import pandas as pd
    import pyarrow.parquet as pq
    f = Path(pasta) / f"{particao}.parquet"
    nomes = pq.read_schema(f).names
    cols = colunas or [c for c in nomes if com_rotulos or c not in ROTULOS]
    if not com_rotulos and set(cols) & set(ROTULOS):
        raise ValueError("colunas de gabarito pedidas com com_rotulos=False")
    return pd.read_parquet(f, columns=cols)


def gabarito(pasta: str | Path):
    import pandas as pd
    return pd.read_csv(Path(pasta) / "gabarito_falhas.csv")
