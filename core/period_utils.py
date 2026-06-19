"""
period_utils.py
───────────────
Utilitários para cálculo do período de análise bissemanal.

Lógica:
  - Período actual   = [upload_date - 14 dias, upload_date - 1 dia]
  - Período anterior = [upload_date - 42 dias, upload_date - 15 dias]  (4 semanas antes)

Usado para garantir que:
  - Métricas e sinalizações = apenas as 2 semanas actuais
  - Tendência               = 2 semanas actuais vs 4 semanas anteriores
"""

from datetime import date, timedelta
from typing import Optional, Tuple
import pandas as pd


def get_analysis_window(upload_date: Optional[date] = None) -> Tuple[date, date]:
    """
    Calcula o período de análise de 2 semanas.

    Parâmetros
    ----------
    upload_date : data de upload do CSV (por defeito: hoje)

    Devolve
    -------
    (period_start, period_end) — ambos inclusive
    """
    ref = upload_date or date.today()
    period_end   = ref - timedelta(days=1)       # dia anterior ao upload
    period_start = ref - timedelta(days=14)      # 14 dias antes (2 semanas)
    return period_start, period_end


def get_trend_window(upload_date: Optional[date] = None) -> Tuple[date, date]:
    """
    Calcula o período de comparação para tendência (4 semanas anteriores ao período actual).

    Devolve
    -------
    (trend_start, trend_end) — as 4 semanas antes do período actual
    """
    ref = upload_date or date.today()
    period_start, _ = get_analysis_window(upload_date)
    trend_end   = period_start - timedelta(days=1)
    trend_start = ref - timedelta(days=14 + 28)  # 6 semanas antes do upload
    return trend_start, trend_end


def filter_to_period(
    df: pd.DataFrame,
    period_start: date,
    period_end: date,
    date_col: str = "test_date",
) -> pd.DataFrame:
    """
    Filtra o DataFrame para o período [period_start, period_end].

    Usa a coluna de data especificada. Registos sem data são excluídos.

    Parâmetros
    ----------
    df           : DataFrame completo (normalizado)
    period_start : data de início (inclusive)
    period_end   : data de fim (inclusive)
    date_col     : coluna de data a usar (por defeito: test_date)

    Devolve
    -------
    DataFrame filtrado
    """
    if date_col not in df.columns:
        return df  # sem coluna de data, devolve tudo

    col = pd.to_datetime(df[date_col], errors="coerce")
    start = pd.Timestamp(period_start)
    end   = pd.Timestamp(period_end) + pd.Timedelta(hours=23, minutes=59)

    mask = col.notna() & (col >= start) & (col <= end)
    filtered = df[mask].copy()
    return filtered


def period_label(period_start: date, period_end: date) -> str:
    """Texto legível para o período de análise."""
    return f"{period_start.strftime('%d/%m/%Y')} a {period_end.strftime('%d/%m/%Y')}"


def period_label_long(period_start: date, period_end: date) -> str:
    """Texto legível longo para o período de análise."""
    meses = {
        1:"Janeiro", 2:"Fevereiro", 3:"Marco", 4:"Abril", 5:"Maio", 6:"Junho",
        7:"Julho", 8:"Agosto", 9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"
    }
    if period_start.month == period_end.month:
        return f"{period_start.day} a {period_end.day} de {meses[period_end.month]} de {period_end.year}"
    else:
        return (
            f"{period_start.day} de {meses[period_start.month]} "
            f"a {period_end.day} de {meses[period_end.month]} de {period_end.year}"
        )
