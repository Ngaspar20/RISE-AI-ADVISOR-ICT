"""
base_agent.py
─────────────
Shared interface that all three agents inherit from.
Enforces consistent structure: run() → AgentResult.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)

RISE_CONTEXT = """
Es um Consultor Tecnico de IA para o Programa RISE ICT (Testagem de Casos Indice),
implementado pelo JHPIEGO em Mocambique (provincias: Zambezia e Manica).

O programa treina conselheiros de unidades sanitarias para:
  1. Inscrever doentes indice HIV+
  2. Elicitar e contactar os seus contactos de estatuto desconhecido ou HIV- (parceiros, filhos, familiares)
  3. Testar os contactos para o HIV
  4. Ligar os contactos HIV+ aos cuidados de saude nas unidades sanitarias

Indicadores prioritarios (por ordem de importancia):
  - Volume de testagem (testing_completion): % de contactos consentidos efectivamente testados (alvo >=95%)
  - Positividade (test_positivity): % de contactos testados que resultam HIV+ (varia por tipo de contacto)
  - Rendimento de contactos (contact_yield): media de contactos por caso indice
  - Taxa de consentimento (consent_rate): % de contactos elegiveis que consentiram ao teste (alvo >=90%)
  - Linkagem (linkage_rate): % de contactos HIV+ ligados aos cuidados - MONITORAR mas NAO e prioridade de sinaliz.

Benchmarking usa hierarquia de dois niveis:
  - Nivel 1: Comparar cada CONSELHEIRO com a MEDIANA da sua UNIDADE SANITARIA
  - Nivel 2: Comparar cada UNIDADE com a MEDIANA do seu DISTRITO
  - Sinalizar conselheiros/unidades >=10% abaixo da mediana como precisando de apoio

Principios de comunicacao:
  - Comecar pelo problema e recomendacao, nao pela metodologia
  - Linguagem simples para supervisores de campo; detalhe tecnico para equipa central
  - Ser especifico: nomear o conselheiro, a unidade, o indicador, a lacuna
  - Recomendar accoes concretas (visita de coaching, aprendizagem entre pares, revisao de unidade)
  - Usar semaforos: 🔴 critico | 🟡 atencao | 🟢 em dia
  - Responder SEMPRE em Portugues
"""


@dataclass
class AgentResult:
    agent_name: str
    success: bool
    narrative: str          # Human-readable text output from Claude
    data: Dict[str, Any] = field(default_factory=dict)   # Structured data for outputs
    error: Optional[str] = None
    tokens_used: int = 0

    def to_dict(self) -> Dict:
        return {
            "agent": self.agent_name,
            "success": self.success,
            "narrative": self.narrative,
            "error": self.error,
        }


class BaseAgent(ABC):
    """Abstract base class for all RISE AI agents."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"agents.{name}")

    @abstractmethod
    def run(self, df: pd.DataFrame, **kwargs) -> AgentResult:
        """
        Execute the agent's workflow on the provided DataFrame.

        Parameters
        ----------
        df      : Normalised ICT line-list DataFrame from data_loader
        kwargs  : Agent-specific parameters (province filter, date range, etc.)

        Returns
        -------
        AgentResult with narrative text and structured data
        """
        raise NotImplementedError

    def _filter_df(
        self,
        df: pd.DataFrame,
        province: Optional[str] = None,
        district: Optional[str] = None,
        facility: Optional[str] = None,
    ) -> pd.DataFrame:
        """Apply optional geographic filters."""
        if province:
            df = df[df["province"] == province]
        if district:
            df = df[df["district"] == district]
        if facility:
            df = df[df["facility"] == facility]
        return df

    def _safe_run(self, df: pd.DataFrame, **kwargs) -> AgentResult:
        """Wrap run() with error handling."""
        try:
            return self.run(df, **kwargs)
        except Exception as e:
            self.logger.error(f"Agent {self.name} failed: {e}", exc_info=True)
            return AgentResult(
                agent_name=self.name,
                success=False,
                narrative="",
                error=str(e),
            )
