import asyncio
import os

import pytest

from regops.config import load_local_environment
from regops.models import (
    ActionType,
    DataClassification,
    DestinationType,
    Purpose,
)
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.regulations import SAMPLE_FINANCIAL_REGULATION


load_local_environment()
RUN_LIVE_TEST = os.getenv("RUN_GEMINI_INTEGRATION_TESTS") == "1" and bool(
    os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
)


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_LIVE_TEST,
    reason="Set RUN_GEMINI_INTEGRATION_TESTS=1 and a Gemini API key to run",
)
def test_sample_regulation_extracts_expected_requirement_with_gemini():
    requirement = asyncio.run(
        RegulationAnalysisAgent().analyze(SAMPLE_FINANCIAL_REGULATION)
    )

    assert requirement.data_classification == DataClassification.BANK_ACCOUNT
    assert requirement.governed_action == ActionType.TRANSMIT
    assert requirement.allowed_destination == DestinationType.APPROVED_PAYMENT_PROCESSOR
    assert requirement.required_purpose == Purpose.AUTHORIZED_FINANCIAL_TRANSACTION
