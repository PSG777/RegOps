from regops.models import (
    ActionType,
    DataClassification,
    DestinationType,
    Purpose,
    Regulation,
    Requirement,
)


SAMPLE_FINANCIAL_REGULATION = Regulation(
    regulation_id="FIN-REG-001",
    title="Financial Account Transmission Restriction",
    source_text=(
        "Financial account information may only be transmitted to approved payment "
        "processors for authorized financial transactions."
    ),
    version="1.0",
)


# Offline verified fixture; never used as a fallback for model extraction.
SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT = Requirement(
    requirement_id="FIN-REQ-001",
    regulation_id=SAMPLE_FINANCIAL_REGULATION.regulation_id,
    source_excerpt=SAMPLE_FINANCIAL_REGULATION.source_text,
    data_classification=DataClassification.BANK_ACCOUNT,
    governed_action=ActionType.TRANSMIT,
    allowed_destination=DestinationType.APPROVED_PAYMENT_PROCESSOR,
    required_purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
    confidence=1.0,
)
