"""
Equity Contract Note Parser Library
====================================
An intelligent, broker-template-driven Python API library for Indian stock market Equity Contract Notes.
Extracts client details, broker details, regulatory IDs, and chronologically sorted share transactions.

Features:
- Strict spatial boundary isolation to prevent address confusion.
- Built-in templates for Zerodha, Shoonya (Finvasia), Systematix, and Generic SEBI brokers.
- Supports file paths, raw bytes, and file streams (io.BytesIO).
- Zero disk-write memory parsing for cloud/serverless environments.

Quick Example:
--------------
>>> from contract_note_parser import parse_contract_note
>>> result = parse_contract_note("sample.pdf", template="auto")
>>> print(result["client_details"]["name"])
>>> print(result["broker_details"]["name"])
>>> print(result["transactions"])
"""

from contract_note_parser import (
    ContractNoteParser,
    parse_contract_note,
    detect_broker_template,
    list_supported_templates
)

from broker_templates import (
    TemplateRegistry,
    BaseBrokerTemplate,
    ZerodhaTemplate,
    ShoonyaTemplate,
    SystematixTemplate,
    GenericTemplate
)

__version__ = "2.0.0"
__author__ = "Arihant Begani"

__all__ = [
    "ContractNoteParser",
    "parse_contract_note",
    "detect_broker_template",
    "list_supported_templates",
    "TemplateRegistry",
    "BaseBrokerTemplate",
    "ZerodhaTemplate",
    "ShoonyaTemplate",
    "SystematixTemplate",
    "GenericTemplate",
    "__version__",
]
