"""
period_utils.py
───────────────
Utilitários para cálculo do período de análise.

Lógica (baseada na última data dos dados, não na data de upload):
  - Período actual   = [last_date - 27 dias, last_date]  (4 semanas até ao fim dos dados)
  - Período anterior = [last_date - 55 dias, last_date - 28 dias]  (4 semanas antes)

Usado para garantir que:
  - Métricas e sinalizações = as 4 semanas mais recentes dos dados
  - Tendência               = 4 semanas actuais vs 4 semanas anteriores
"""

from datetime import date, timedelta
from typing import Optional, Tuple
import pandas as pd


def get_last_date(df: pd.DataFrame, date_col: str = "test_date") -> Optional[date]:
    """
    Extrai a data mais recente do dataset (máximo da coluna de data).
    Devolve None se a coluna não existir ou não tiver datas válidas.
    """
    if date_col not in df.columns:
        return None
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date()


def get_analysis_window(last_date: Optional[date] = None) -> Tuple[date, date]:
    """
    Calcula o período de análise de 4 semanas com base na última data dos dados.

    Parâmetros
    ----------
    last_date : última data presente no dataset (por defeito: hoje)

    Devolve
    -------
    (period_start, period_end) — ambos inclusive
    """
    ref = last_date or date.today()
    period_end   = ref                           # última data dos dados
    period_start = ref - timedelta(days=27)      # 4 semanas (28 dias) antes
    return period_start, period_end


def get_trend_window(last_date: Optional[date] = None) -> Tuple[date, date]:
    """
    Calcula o período de comparação para tendência (4 semanas anteriores ao período actual).

    Devolve
    -------
    (trend_start, trend_end) — as 4 semanas antes do período actual
    """
    period_start, _ = get_analysis_window(last_date)
    trend_end   = period_start - timedelta(days=1)
    trend_start = trend_end - timedelta(days=27)  # 4 semanas antes do período actual
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
