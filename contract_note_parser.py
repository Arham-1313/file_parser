"""
Contract Note Parser for Indian Equity Segment (Shares Only)
Extracts equity share transactions:
- quantity of the share
- purchase price per share
- trade date
- settlement date
- brokerage (calculated as brokerage per share * quantity)
- security name and ISIN
- transaction type (BUY / SELL)
- transaction time (sorted chronologically)

Also extracts:
- client details (Name, Client ID/UCC, PAN, Address)
- broker details (Name, SEBI Reg, PAN, CIN, GSTIN, Address, Contract Note No, IRN)
- file details (File name, Size, Total pages, Total transactions, Total Buy, Total Sell)

Strictly excludes derivatives, options, futures, and non-equity segments.
"""

import os
import io
import re
import json
import argparse
from typing import Dict, Any, List, Optional, Union
import pdfplumber

from broker_templates import TemplateRegistry, BaseBrokerTemplate
from zone_manager import ZoneManager


__version__ = "2.0.0"
__author__ = "Arihant Begani"

class ContractNoteParser:
    """
    Parser for Equity Segment (Shares) Contract Notes with Broker Template System.
    Can be used as a Python API library with file paths, raw bytes, or file streams.
    """

    ISIN_REGEX = re.compile(r'\b(IN[EF9][A-Z0-9]{8}[0-9])\b')
    PAN_REGEX = re.compile(r'\b([A-Z]{5}[0-9]{4}[A-Z])\b')
    NUM_REGEX = re.compile(r'[-+]?\d+(?:,\d+)*(?:\.\d+)?')
    DATE_REGEX = re.compile(r'\b(?:\d{1,2}[-/\.](?:[A-Za-z]{3,9}|\d{1,2})[-/\.]\d{2,4}|\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})\b')
    DERIVATIVE_EXCLUDE_REGEX = re.compile(
        r'\b(?:[A-Z0-9]{2,15}\d{2}[A-Z]{3}(?:\d+[CP]E|FUT)|\d+[CP]E\b|CALL|PUT|FUTURES?|OPTIONS?)\b',
        re.IGNORECASE
    )
    TRADE_ORDER_REGEX = re.compile(
        r'(?:(\d{8,25})\s+)?(?:(\d{1,2}:\d{2}:\d{2})\s+)?(?:(\d+)\s+)?(?:(\d{1,2}:\d{2}:\d{2})\s+)?([A-Za-z0-9\s\.\-&/]+?)\s+([BS])\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)(?:\s+([-+]?\d+(?:\.\d+)?))?'
    )

    def __init__(
        self,
        pdf_source: Union[str, bytes, io.BytesIO, io.BufferedIOBase],
        password: Optional[str] = None,
        file_name: Optional[str] = None,
        template: str = "auto"
    ):
        """
        Initialize the Contract Note Parser.

        :param pdf_source: Path to PDF (str), raw PDF bytes, or file-like stream (io.BytesIO).
        :param password: Password string if the PDF is encrypted (e.g. PAN or DOB).
        :param file_name: Optional human-readable file name for reference.
        :param template: Broker template ('auto', 'zerodha', 'shoonya', 'systematix', 'generic').
        """
        self.pdf_source = pdf_source
        self.password = password
        self.template = template or "auto"
        self.active_template: Optional[BaseBrokerTemplate] = None
        self.template_confidence: float = 1.0
        self.detection_mode: str = "manual"

        # Determine file source type and metadata
        self.file_size_bytes: int = 0
        if isinstance(pdf_source, (str, os.PathLike)):
            self.pdf_path = str(pdf_source)
            self.file_name = file_name or os.path.basename(self.pdf_path)
            self._is_stream = False
        elif isinstance(pdf_source, bytes):
            self.pdf_path = None
            self.file_name = file_name or "contract_note.pdf"
            self._is_stream = True
            self.file_size_bytes = len(pdf_source)
        else:
            self.pdf_path = None
            self.file_name = file_name or getattr(pdf_source, "name", "contract_note.pdf")
            self._is_stream = True
            if hasattr(pdf_source, "getvalue"):
                self.file_size_bytes = len(pdf_source.getvalue())
            else:
                self.file_size_bytes = 0

        self.full_text = ""
        self.pages_text: List[str] = []
        self.tables: List[List[List[str]]] = []
        self.trade_date: Optional[str] = None
        self.settlement_date: Optional[str] = None

        self.file_size_formatted: str = "0 B"
        self.total_pages: int = 0

        self.client_details: Dict[str, Any] = {}
        self.broker_details: Dict[str, Any] = {}
        self.file_details: Dict[str, Any] = {}
        self.party_details: Dict[str, Any] = {}
        self.spatial_crops: Dict[str, Any] = {}

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """Format byte size into readable string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    @staticmethod
    def _normalize_time(time_str: Optional[str]) -> str:
        """Normalize time string to HH:MM:SS format."""
        if not time_str:
            return ""
        s = str(time_str).strip()
        m = re.search(r'\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b', s)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2))
            ss = int(m.group(3)) if m.group(3) else 0
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        return ""

    @staticmethod
    def _sort_transactions_by_time(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort transactions chronologically by transaction_time."""
        def _get_time_key(tx: Dict[str, Any]):
            t = tx.get("transaction_time") or tx.get("trade_time") or ""
            return (0, t) if t else (1, "")
        return sorted(transactions, key=_get_time_key)

    def parse(
        self,
        simplified: bool = True,
        include_party: bool = True,
        include_details: bool = True,
        as_dict: bool = False
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Execute parsing using broker template architecture.
        Guarantees that broker address and client address are never confused.
        """
        self._load_and_extract_pdf()
        self._extract_dates()

        # Resolve broker template
        if not self.template or self.template.lower() in ("auto", "detect", "default"):
            template_obj, conf = TemplateRegistry.detect_template(self.full_text, self.tables)
            self.active_template = template_obj
            self.template_confidence = conf
            self.detection_mode = "auto"
        else:
            template_obj = TemplateRegistry.get_template(self.template)
            self.active_template = template_obj
            self.template_confidence = 1.0
            self.detection_mode = "manual"

        # Template-based extraction of broker and client details
        broker_extracted = template_obj.extract_broker_details(
            self.full_text, self.tables, self.pages_text
        )
        broker_extracted["trade_date"] = self.trade_date
        broker_extracted["settlement_date"] = self.settlement_date
        self.broker_details = broker_extracted

        # Extract template-specific spatial crops from SQLite
        template_id = getattr(template_obj, "template_id", "generic").lower()
        active_spatial = dict(self.spatial_crops.get(template_id, {}))
        # Also copy into top-level for backward compatibility
        for f_name, f_val in active_spatial.items():
            self.spatial_crops[f"{template_id}_{f_name}"] = f_val

        try:
            client_extracted = template_obj.extract_client_details(
                self.full_text, self.tables, self.pages_text, self.broker_details,
                spatial_data=active_spatial
            )
        except TypeError:
            client_extracted = template_obj.extract_client_details(
                self.full_text, self.tables, self.pages_text, self.broker_details
            )
        self.client_details = client_extracted

        self.party_details = {
            "name": self.client_details.get("name"),
            "party_name": self.client_details.get("name"),
            "client_id": self.client_details.get("client_id"),
            "pan": self.client_details.get("pan"),
            "pan_number": self.client_details.get("pan"),
            "address": self.client_details.get("address"),
            "contract_note_no": self.broker_details.get("contract_note_no")
        }

        transactions = self._extract_transactions(simplified=simplified)

        # Compute summary metrics for file_details
        total_buys = sum(1 for tx in transactions if str(tx.get("transaction_type") or tx.get("action") or "").upper() == "BUY")
        total_sells = sum(1 for tx in transactions if str(tx.get("transaction_type") or tx.get("action") or "").upper() == "SELL")

        self.file_details = {
            "file_name": self.file_name,
            "file_size": self.file_size_formatted,
            "file_size_bytes": self.file_size_bytes,
            "total_pages": self.total_pages,
            "total_transactions": len(transactions),
            "total_buy_transactions": total_buys,
            "total_sell_transactions": total_sells
        }

        output_data = template_obj.format_output(
            client_details=self.client_details,
            broker_details=self.broker_details,
            file_details=self.file_details,
            transactions=transactions,
            confidence=self.template_confidence,
            detection_mode=self.detection_mode
        )

        if as_dict:
            tx_dict = {(tx.get("isin") or tx.get("security_name") or str(idx)): tx for idx, tx in enumerate(transactions)}
            output_data["transactions"] = tx_dict
            if include_party or include_details:
                return output_data
            return tx_dict

        if include_party or include_details:
            return output_data

        return transactions

    def _load_and_extract_pdf(self):
        """Open PDF with pdfplumber and collect texts and tables from file path or byte stream."""
        open_kwargs = {}
        if self.password:
            open_kwargs["password"] = self.password

        if not self._is_stream:
            if not os.path.exists(self.pdf_path):
                raise FileNotFoundError(f"PDF file not found: {self.pdf_path}")
            self.file_size_bytes = os.path.getsize(self.pdf_path)
            target = self.pdf_path
        else:
            if isinstance(self.pdf_source, bytes):
                target = io.BytesIO(self.pdf_source)
            else:
                target = self.pdf_source
                if hasattr(target, "seek"):
                    target.seek(0)

        self.file_size_formatted = self._format_file_size(self.file_size_bytes)

        with pdfplumber.open(target, **open_kwargs) as pdf:
            self.total_pages = len(pdf.pages)
            if self.total_pages > 0:
                # Query SQLite table for all registered template coordinate zones
                try:
                    self.spatial_crops = ZoneManager.extract_spatial_crops_for_pages(pdf.pages)
                except Exception:
                    self.spatial_crops = {}

            for page in pdf.pages:
                text = page.extract_text() or ""
                self.pages_text.append(text)

                page_tables = page.extract_tables(table_settings={
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                })
                if not page_tables:
                    page_tables = page.extract_tables()

                if page_tables:
                    self.tables.extend(page_tables)

        self.full_text = "\n".join(self.pages_text)

    def _clean_str(self, val: Optional[str]) -> str:
        if val is None:
            return ""
        return " ".join(str(val).replace("\n", " ").split()).strip()

    def _parse_float(self, val: Any) -> float:
        if val is None:
            return 0.0
        val_str = str(val).strip().replace(",", "")
        if val_str.startswith("(") and val_str.endswith(")"):
            val_str = "-" + val_str[1:-1]
        try:
            return float(val_str)
        except ValueError:
            return 0.0

    def _parse_date_obj(self, date_str: Optional[str]):
        if not date_str:
            return None
        from datetime import datetime
        for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d-%b-%Y', '%d-%B-%Y', '%Y-%m-%d', '%d-%m-%y', '%d/%m/%y'):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                pass
        return None

    def _extract_dates(self):
        """
        Extract trade_date and settlement_date with comprehensive multi-strategy parsing:
        1. From tables (cell label + adjacent cell or stacked cell below)
        2. From text using regex with flexible labels and date formats
        3. From stacked headers in text (Trade Date and Settlement Date side-by-side)
        4. Validate that Trade Date <= Settlement Date (auto-swap if reversed)
        """
        td_val = None
        sd_val = None

        # 1. Search in tables
        for table in self.tables:
            if not table:
                continue
            for r_idx, row in enumerate(table):
                for c_idx, cell in enumerate(row):
                    if not cell:
                        continue
                    cell_text = str(cell).strip()
                    # Check for Trade Date label
                    if re.search(r'\b(?:Trade\s*Date|Date\s*of\s*Trade|Trading\s*Date|Trade\s*Dt)\b', cell_text, re.IGNORECASE):
                        dm = self.DATE_REGEX.search(cell_text)
                        if dm:
                            td_val = dm.group(0)
                        elif c_idx + 1 < len(row) and row[c_idx + 1]:
                            dm = self.DATE_REGEX.search(str(row[c_idx + 1]))
                            if dm:
                                td_val = dm.group(0)
                        elif r_idx + 1 < len(table) and c_idx < len(table[r_idx + 1]) and table[r_idx + 1][c_idx]:
                            dm = self.DATE_REGEX.search(str(table[r_idx + 1][c_idx]))
                            if dm:
                                td_val = dm.group(0)

                    # Check for Settlement Date label
                    if re.search(r'\b(?:Settlement\s*Date|Date\s*of\s*Settlement|Sett\.?\s*Date|Settlement\s*Dt)\b', cell_text, re.IGNORECASE):
                        dm = self.DATE_REGEX.search(cell_text)
                        if dm:
                            sd_val = dm.group(0)
                        elif c_idx + 1 < len(row) and row[c_idx + 1]:
                            dm = self.DATE_REGEX.search(str(row[c_idx + 1]))
                            if dm:
                                sd_val = dm.group(0)
                        elif r_idx + 1 < len(table) and c_idx < len(table[r_idx + 1]) and table[r_idx + 1][c_idx]:
                            dm = self.DATE_REGEX.search(str(table[r_idx + 1][c_idx]))
                            if dm:
                                sd_val = dm.group(0)

        # 2. Text line-by-line / stacked search
        text = self.full_text
        if not td_val:
            td_match = re.search(
                r'(?:Trade\s*Date|Date\s*of\s*Trade|Trading\s*Date|Trade\s*Dt)\s*[:\-]?\s*([0-9]{1,2}[-/\.](?:[A-Za-z]{3,9}|\d{1,2})[-/\.][0-9]{2,4}|[0-9]{4}[-/\.][0-9]{1,2}[-/\.][0-9]{1,2})',
                text,
                re.IGNORECASE
            )
            if td_match:
                td_val = td_match.group(1).strip()

        if not sd_val:
            sd_match = re.search(
                r'(?:Settlement\s*Date|Date\s*of\s*Settlement|Sett\.?\s*Date|Settlement\s*Dt)\s*[:\-]?\s*([0-9]{1,2}[-/\.](?:[A-Za-z]{3,9}|\d{1,2})[-/\.][0-9]{2,4}|[0-9]{4}[-/\.][0-9]{1,2}[-/\.][0-9]{1,2})',
                text,
                re.IGNORECASE
            )
            if sd_match:
                sd_val = sd_match.group(1).strip()

        if not sd_val:
            sd_match = re.search(
                r'(?:Sett\.?\s*Date|Date\s*of\s*Settlement|Settlement\s*Date|Settlement\s*Dt)[\s\S]{1,150}?(\d{1,2}[-/\.](?:[A-Za-z]{3,9}|\d{1,2})[-/\.]\d{2,4})',
                text,
                re.IGNORECASE
            )
            if sd_match:
                sd_val = sd_match.group(1).strip()

        # 3. Stacked lines in text (e.g. "Trade Date Settlement Date" followed by dates)
        if not td_val or not sd_val:
            lines = text.splitlines()
            for i, line in enumerate(lines[:-1]):
                if re.search(r'Trade\s*Date', line, re.IGNORECASE) and re.search(r'Settlement\s*Date', line, re.IGNORECASE):
                    current_dates = self.DATE_REGEX.findall(line)
                    if len(current_dates) >= 2:
                        if not td_val: td_val = current_dates[0]
                        if not sd_val: sd_val = current_dates[1]
                        break
                    next_dates = self.DATE_REGEX.findall(lines[i + 1])
                    if len(next_dates) >= 2:
                        if not td_val: td_val = next_dates[0]
                        if not sd_val: sd_val = next_dates[1]
                        break

        # 4. Validation: Ensure Trade Date <= Settlement Date (swap if reversed)
        if td_val and sd_val:
            d1 = self._parse_date_obj(td_val)
            d2 = self._parse_date_obj(sd_val)
            if d1 and d2 and d1 > d2:
                td_val, sd_val = sd_val, td_val

        self.trade_date = td_val
        self.settlement_date = sd_val

    def _extract_party_and_file_details(self) -> Dict[str, Any]:
        """Extract trade date, settlement date, client details, and contract note info."""
        text = self.full_text

        # Extract dates using multi-strategy logic
        self._extract_dates()

        # Party / Client Name
        party_name = None
        name_patterns = [
            r'([A-Z][a-zA-Z\s]{2,35})\s*\([A-Za-z0-9]+\)\s+Dealing\s*Office',
            r'(?:Party\s*/\s*Client|Client|Party)\s*Name\s*[:\-]\s*([^\n\r\|]+)',
            r'Name\s*of\s*Client\s*[:\-]\s*([^\n\r\|]+)',
            r'To\s*,\s*\n\s*([^\n\r]+)',
            r'Client\s*Name\s*([A-Z\s]{4,35})'
        ]
        for pat in name_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                extracted = m.group(1).strip()
                extracted = re.split(r'\b(?:PAN|Client ID|UCC|Address)\b', extracted, flags=re.IGNORECASE)[0].strip()
                if extracted and len(extracted) > 2:
                    party_name = extracted
                    break

        if not party_name and self.spatial_crops.get("systematix_party_name"):
            party_name = self.spatial_crops["systematix_party_name"].strip()

        # Contract Note Number
        contract_note_no = None
        cn_patterns = [
            r'Contract\s*Note\s*No\.?\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)',
            r'Invoice\s*Reference\s*Number\s*\([^\)]*\)\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)'
        ]
        for pat in cn_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                contract_note_no = m.group(1).strip()
                break

        # Client ID / UCC
        client_id = None
        ucc_patterns = [
            r'(?:UCC\s*of\s*Code|Trading\s*Backoffice\s*Code)\s*[:\-]?\s*([A-Za-z0-9]+)',
            r'(?:Client\s*(?:ID|Code)|UCC(?:\s*Code)?|Trading\s*Code)\s*(?:/\s*UCC)?\s*[:\-]\s*([A-Za-z0-9]+)',
            r'UCC\s*[:\-]\s*([A-Za-z0-9]+)'
        ]
        for pat in ucc_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val.lower() != "of":
                    client_id = val
                    break

        # Check for standalone broker UCC format like DA9605 (2 uppercase letters + 4 digits)
        if not client_id:
            for table in self.tables:
                for row in table:
                    for cell in row:
                        if cell:
                            cell_s = str(cell).strip()
                            if re.fullmatch(r'[A-Z]{2}[0-9]{4,6}', cell_s):
                                client_id = cell_s
                                break
                    if client_id:
                        break
                if client_id:
                    break

        if not client_id:
            ucc_match = re.search(r'\b([A-Z]{2}[0-9]{4,6})\b', text)
            if ucc_match:
                client_id = ucc_match.group(1)

        # PAN Number (prioritize Client PAN over broker company PAN)
        pan_number = None
        pan_patterns = [
            r'(?:PAN\s*of\s*Client|Client\s*PAN(?:\s*No\.?|\s*Number)?)\s*[:\-]?\s*([A-Z]{5}[0-9]{4}[A-Z])',
            r'(?:Client\s*)?PAN(?:\s*No\.?|\s*Number)?\s*[:\-]?\s*([A-Z]{5}[0-9]{4}[A-Z])',
            r'PAN\s*[:\-]\s*([A-Z]{5}[0-9]{4}[A-Z])'
        ]
        for pat in pan_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                pan_number = m.group(1).strip()
                break

        # Address
        address = None
        addr_match = re.search(r'Address\s*[:\-]\s*([^\n\r]+(?:\n[^\n\r]+)?)', text, re.IGNORECASE)
        if addr_match:
            addr_raw = addr_match.group(1)
            addr_clean = re.split(r'\b(?:Segment|Exchange|PAN|Client|Trade)\b', addr_raw, flags=re.IGNORECASE)[0]
            address = self._clean_str(addr_clean)

        self.client_details = {
            "name": party_name,
            "client_id": client_id,
            "pan": pan_number,
            "address": address
        }

        self.party_details = {
            "name": party_name,
            "party_name": party_name,
            "client_id": client_id,
            "pan": pan_number,
            "pan_number": pan_number,
            "address": address,
            "contract_note_no": contract_note_no
        }
        return self.party_details

    def _extract_broker_details(self) -> Dict[str, Any]:
        """Extract broker details including name, SEBI registration, PAN, CIN, GSTIN, IRN."""
        text = self.full_text

        # 1. Broker Name
        broker_name = None
        broker_keywords = re.compile(
            r'\b(?:LIMITED|LTD|SECURITIES|BROKING|BROKERS|CAPITAL|EQUITIES|FINANCIAL SERVICES)\b',
            re.IGNORECASE
        )
        exclude_terms = re.compile(
            r'\b(?:Contract Note|Trade Date|Client|Party|Dealing Office|Annexure|PAN|GSTIN|SEBI|IRN|Settlement|Sir/ Madam|Equity Segment|Invoice|Order|Scrip)\b',
            re.IGNORECASE
        )

        for line in text.splitlines()[:10]:
            line_str = line.strip()
            if broker_keywords.search(line_str) and not exclude_terms.search(line_str) and 4 < len(line_str) < 80:
                broker_name = line_str
                break

        if not broker_name:
            bm = re.search(
                r'(?:Trading\s*Member|Member\s*Name|Stock\s*Broker|Member)\s*[:\-]?\s*([A-Za-z0-9\s\.\-&/]+?(?:LIMITED|LTD|PVT|PRIVATE|SERVICES|SECURITIES|CAPITAL))',
                text,
                re.IGNORECASE
            )
            if bm:
                broker_name = bm.group(1).strip()

        # Check Clearing Corporation name
        clearing_corp = None
        cc_match = re.search(r'(?:Name\s*of\s*Clearing\s*Corporation|Clearing\s*Corporation)\s*[:\-]?\s*([^\n\r\|]+)', text, re.IGNORECASE)
        if cc_match:
            clearing_corp = self._clean_str(cc_match.group(1))

        # 2. SEBI Registration No
        sebi_reg = None
        sebi_match = re.search(r'\b(INZ[0-9]{7,10})\b', text)
        if sebi_match:
            sebi_reg = sebi_match.group(1)
        else:
            sebi_match2 = re.search(r'SEBI\s*(?:Regn?\.?|Registration)?\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Z0-9\/]+)', text, re.IGNORECASE)
            if sebi_match2:
                sebi_reg = sebi_match2.group(1).strip()

        # 3. CIN
        cin = None
        cin_match = re.search(r'\b([LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\b', text)
        if cin_match:
            cin = cin_match.group(1)

        # 4. GSTIN
        gstin = None
        gstin_match = re.search(r'\b(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d])\b', text)
        if gstin_match:
            gstin = gstin_match.group(1)

        # 5. Broker PAN
        broker_pan = None
        b_pan_match = re.search(r'(?:Broker|Member|Company)\s*PAN\s*[:\-]?\s*([A-Z]{5}[0-9]{4}[A-Z])', text, re.IGNORECASE)
        if b_pan_match:
            broker_pan = b_pan_match.group(1)
        else:
            all_pans = self.PAN_REGEX.findall(text)
            client_pan = self.client_details.get("pan")
            for p in all_pans:
                if p != client_pan:
                    broker_pan = p
                    break

        # 6. IRN (Invoice Reference Number)
        irn = None
        irn_match = re.search(r'(?:Invoice\s*Reference\s*(?:No\.?|Number)|IRN)\s*(?:\([^\)]*\))?\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)', text, re.IGNORECASE)
        if irn_match:
            irn = irn_match.group(1).strip()

        # 7. Broker Address / Dealing Office
        broker_address = None
        b_addr_match = re.search(r'(?:Regd\.?\s*Office|Registered\s*Office|Dealing\s*Office)\s*[:\-]?\s*([^\n\r\|]+(?:\n[^\n\r\|]+)?)', text, re.IGNORECASE)
        if b_addr_match:
            broker_address = self._clean_str(b_addr_match.group(1))

        self.broker_details = {
            "name": broker_name,
            "sebi_registration_no": sebi_reg,
            "pan": broker_pan,
            "cin": cin,
            "gstin": gstin,
            "contract_note_no": self.party_details.get("contract_note_no"),
            "irn": irn,
            "trade_date": self.trade_date,
            "settlement_date": self.settlement_date,
            "address": broker_address,
            "clearing_corporation": clearing_corp
        }
        return self.broker_details

    def _is_derivative_table(self, table: List[List[Any]]) -> bool:
        """Check if table belongs to Derivatives / F&O segment rather than Equity."""
        if not table:
            return False
        header_text = " ".join([str(c or "").lower() for row in table[:3] for c in row if c is not None])
        if any(term in header_text for term in ["capital market", "cash segment", "cash seg", "equity segment", "equity"]):
            return False

        derivative_indicators = [
            "f & o segment", "f&o segment", "derivatives segment",
            "futures & options", "futures and options", "equity derivatives segment"
        ]
        if any(indicator in header_text for indicator in derivative_indicators):
            return True

        has_isin = any(self.ISIN_REGEX.search(str(c or "")) for row in table for c in row if c is not None)
        if has_isin:
            return False

        has_derivative_row = any(self.DERIVATIVE_EXCLUDE_REGEX.search(str(c or "")) for row in table for c in row if c is not None)
        if has_derivative_row and not has_isin:
            return True

        return False

    def _parse_trade_lines_with_scrip_totals(self, lines: List[str]) -> List[Dict[str, Any]]:
        """
        Parse lines of text or single-column table rows where trades are listed as:
        Order No, Order Time, Trade No, Trade Time, Security Name, Buy/Sell (B/S), Qty, Gross Rate, Brokerage Unit, Net Rate, Net Total
        followed by:
        Scrip Total / Sub Total containing the ISIN.
        """
        results = []
        current_trades: List[Dict[str, Any]] = []
        current_scrip_isin: Optional[str] = None

        for line in lines:
            line_str = self._clean_str(line)
            if not line_str:
                continue
            line_lower = line_str.lower()

            isin_match = self.ISIN_REGEX.search(line_str)

            # Check if this line is Scrip Total or Sub Total
            if "scrip total" in line_lower or "sub total" in line_lower:
                found_isin = isin_match.group(1) if isin_match else current_scrip_isin
                if found_isin and current_trades:
                    for t in current_trades:
                        t["isin"] = found_isin
                        results.append(t)
                    current_trades = []
                    current_scrip_isin = None
                continue

            # Skip summary lines that are not scrip totals
            if any(term in line_lower for term in ["exchange total", "turnover total", "grand total", "net value/mtm"]):
                continue

            # Check if this is a Scrip Header line
            if isin_match and not any(k in line_str for k in [" 7", " 0", " 1", " 2", " 3", " 4", " 5", " 6", " 8", " 9"]):
                current_scrip_isin = isin_match.group(1)
                continue

            # Match trade order line
            tm = self.TRADE_ORDER_REGEX.search(line_str)
            if tm:
                sec_name = tm.group(5).strip()
                if self.DERIVATIVE_EXCLUDE_REGEX.search(sec_name):
                    continue

                order_time = tm.group(2)
                trade_time = tm.group(4) or order_time
                action = tm.group(6).upper()  # B or S
                qty = self._parse_float(tm.group(7))
                gross_rate = self._parse_float(tm.group(8))
                brok_unit = self._parse_float(tm.group(9))
                net_rate = self._parse_float(tm.group(10))

                if qty == 0:
                    continue

                price = gross_rate if gross_rate > 0 else net_rate
                total_brok = round(brok_unit * abs(qty), 2)

                qty_val = int(qty) if isinstance(qty, float) and qty.is_integer() else abs(qty)
                price_val = int(price) if isinstance(price, float) and price.is_integer() else price

                trade_isin = isin_match.group(1) if isin_match else current_scrip_isin
                tx_type = "BUY" if action == "B" else "SELL"
                tx_time = self._normalize_time(trade_time)

                trade = {
                    "security_name": sec_name,
                    "isin": trade_isin,
                    "transaction_type": tx_type,
                    "action": tx_type,
                    "transaction_time": tx_time,
                    "trade_time": tx_time,
                    "trade_date": self.trade_date,
                    "settlement_date": self.settlement_date,
                    "quantity": qty_val,
                    "purchase_price_per_share": price_val,
                    "brokerage": total_brok
                }

                if trade_isin:
                    results.append(trade)
                else:
                    current_trades.append(trade)

        # Post-loop resolution: if any trades are waiting for an ISIN
        if current_trades:
            full_isin = None
            im = self.ISIN_REGEX.search(self.full_text)
            if im:
                full_isin = im.group(1)
            for t in current_trades:
                if full_isin:
                    t["isin"] = full_isin
                    results.append(t)

        return results

    def _parse_trade_list_table(self, table: List[List[Any]], simplified: bool = True) -> List[Dict[str, Any]]:
        """
        Parse transaction-by-transaction equity tables where individual trades are listed
        and followed or preceded by a Scrip Total / Scrip Header containing the ISIN.
        """
        results = []
        if not table or len(table) < 2:
            return results

        non_empty_rows = [r for r in table if r and any(r)]
        if non_empty_rows and all(len(r) == 1 for r in non_empty_rows):
            flat_lines = [str(r[0]) for r in non_empty_rows]
            return self._parse_trade_lines_with_scrip_totals(flat_lines)

        # Find header row
        header_idx = -1
        col_map = {}
        for r_idx, row in enumerate(table):
            row_str = " ".join([str(c or "").lower() for c in row])
            if ("order no" in row_str or "trade no" in row_str) and ("security" in row_str or "contract description" in row_str or "scrip" in row_str):
                header_idx = r_idx
                for c_idx, cell in enumerate(row):
                    txt = " ".join(str(cell or "").lower().split())
                    if "security" in txt or "contract description" in txt or "scrip" in txt:
                        col_map["desc"] = c_idx
                    elif "buy" in txt and "sell" in txt:
                        col_map["action"] = c_idx
                    elif any(q in txt for q in ["qty", "quantity"]) and "buy" not in txt and "sell" not in txt:
                        col_map["qty"] = c_idx
                    elif "trade time" in txt or "trd time" in txt:
                        col_map["trade_time"] = c_idx
                    elif "order time" in txt or "ord time" in txt:
                        col_map["order_time"] = c_idx
                    elif "time" in txt and "trade_time" not in col_map:
                        col_map["trade_time"] = c_idx
                    elif ("gross rate" in txt or "trade price" in txt or "wap" in txt or "rate" in txt) and "(foreign" not in txt and "net" not in txt and "closing" not in txt:
                        col_map["gross_price"] = c_idx
                    elif "net rate" in txt:
                        col_map["net_price"] = c_idx
                    elif "brokerage" in txt:
                        col_map["brokerage"] = c_idx
                    elif "net total" in txt:
                        col_map["net_total"] = c_idx
                break

        if header_idx == -1 or "desc" not in col_map or "qty" not in col_map:
            return results

        col_map["price"] = col_map.get("gross_price", col_map.get("net_price"))

        current_trades: List[Dict[str, Any]] = []
        current_scrip_isin: Optional[str] = None

        for row in table[header_idx + 1:]:
            if not row or not any(row):
                continue

            cleaned = [self._clean_str(c) for c in row]
            row_str = " ".join(cleaned)
            row_str_lower = row_str.lower()

            is_scrip_total = "scrip total" in row_str_lower or "sub total" in row_str_lower
            is_summary = any(term in row_str_lower for term in ["exchange total", "turnover total", "grand total"])
            isin_match = self.ISIN_REGEX.search(row_str)

            if is_scrip_total:
                found_isin = isin_match.group(1) if isin_match else current_scrip_isin
                if found_isin:
                    for t in current_trades:
                        t["isin"] = found_isin
                        results.append(t)
                    current_trades = []
                    current_scrip_isin = None
                continue

            if is_summary:
                continue

            qty_val_raw = cleaned[col_map["qty"]] if col_map["qty"] < len(cleaned) else ""
            if isin_match and (not qty_val_raw or self._parse_float(qty_val_raw) == 0):
                current_scrip_isin = isin_match.group(1)
                continue

            desc_idx = col_map["desc"]
            if desc_idx >= len(cleaned):
                continue
            desc = cleaned[desc_idx]
            if not desc or "total" in desc.lower():
                continue

            if self.DERIVATIVE_EXCLUDE_REGEX.search(desc):
                continue

            qty_idx = col_map["qty"]
            qty = self._parse_float(cleaned[qty_idx]) if qty_idx < len(cleaned) else 0.0
            if qty == 0:
                continue

            price_idx = col_map.get("price")
            price = self._parse_float(cleaned[price_idx]) if price_idx is not None and price_idx < len(cleaned) else 0.0

            brok_idx = col_map.get("brokerage")
            brok_unit = self._parse_float(cleaned[brok_idx]) if brok_idx is not None and brok_idx < len(cleaned) else 0.0
            total_brok = round(brok_unit * abs(qty), 2)

            qty_val = int(qty) if isinstance(qty, float) and qty.is_integer() else abs(qty)
            price_val = int(price) if isinstance(price, float) and price.is_integer() else price

            trade_isin = isin_match.group(1) if isin_match else current_scrip_isin

            # Determine Action (BUY or SELL)
            action_val = "BUY"
            if "action" in col_map and col_map["action"] < len(cleaned):
                act_str = cleaned[col_map["action"]].strip().upper()
                if "S" in act_str:
                    action_val = "SELL"
                elif "B" in act_str:
                    action_val = "BUY"

            # Determine Transaction Time
            tx_time_str = ""
            if "trade_time" in col_map and col_map["trade_time"] < len(cleaned):
                tx_time_str = cleaned[col_map["trade_time"]].strip()
            elif "order_time" in col_map and col_map["order_time"] < len(cleaned):
                tx_time_str = cleaned[col_map["order_time"]].strip()

            if not tx_time_str:
                tm_match = re.search(r'\b\d{1,2}:\d{2}(?::\d{2})?\b', row_str)
                if tm_match:
                    tx_time_str = tm_match.group(0)

            tx_time = self._normalize_time(tx_time_str)

            trade = {
                "security_name": desc,
                "isin": trade_isin,
                "transaction_type": action_val,
                "action": action_val,
                "transaction_time": tx_time,
                "trade_time": tx_time,
                "trade_date": self.trade_date,
                "settlement_date": self.settlement_date,
                "quantity": qty_val,
                "purchase_price_per_share": price_val,
                "brokerage": total_brok
            }

            if trade_isin:
                results.append(trade)
            else:
                current_trades.append(trade)

        if current_trades:
            table_isin = None
            for r in table:
                m = self.ISIN_REGEX.search(" ".join([str(c or "") for c in r]))
                if m:
                    table_isin = m.group(1)
                    break
            if not table_isin:
                m = self.ISIN_REGEX.search(self.full_text)
                if m:
                    table_isin = m.group(1)

            for t in current_trades:
                if table_isin:
                    t["isin"] = table_isin
                    results.append(t)

        return results

    def _extract_transactions(self, simplified: bool = True) -> List[Dict[str, Any]]:
        """
        Extract transactions for Equity segment (shares) only.
        Options, futures, and other derivatives are strictly excluded.
        Sorted chronologically by transaction_time.
        """
        transactions: List[Dict[str, Any]] = []
        seen = set()

        # 1. Search extracted tables
        for table in self.tables:
            if not table or self._is_derivative_table(table):
                continue

            list_txs = self._parse_trade_list_table(table, simplified=simplified)
            for tx in list_txs:
                sec_name = tx.get("security_name") or ""
                if not tx.get("isin") or self.DERIVATIVE_EXCLUDE_REGEX.search(sec_name):
                    continue
                key = (
                    tx.get("isin"),
                    tx.get("security_name"),
                    tx.get("transaction_type"),
                    tx.get("transaction_time"),
                    tx.get("quantity"),
                    tx.get("purchase_price_per_share"),
                    tx.get("brokerage")
                )
                if key not in seen:
                    seen.add(key)
                    transactions.append(tx)

            if not list_txs:
                for row in table:
                    if not row or not any(row):
                        continue

                    row_str = " ".join([str(c) for c in row if c is not None])
                    isin_match = self.ISIN_REGEX.search(row_str)
                    if not isin_match:
                        continue

                    tx_items = self._parse_transaction_row(row, isin_match.group(1), simplified=simplified)
                    for tx in tx_items:
                        sec_name = tx.get("security_name") or ""
                        if not tx.get("isin") or self.DERIVATIVE_EXCLUDE_REGEX.search(sec_name):
                            continue
                        key = (
                            tx.get("isin"),
                            tx.get("security_name"),
                            tx.get("transaction_type"),
                            tx.get("transaction_time"),
                            tx.get("quantity"),
                            tx.get("purchase_price_per_share"),
                            tx.get("brokerage")
                        )
                        if key not in seen:
                            seen.add(key)
                            transactions.append(tx)

        # 2. Text fallback
        if not transactions:
            text_txs = self._parse_trade_lines_with_scrip_totals(self.full_text.splitlines())
            for tx in text_txs:
                sec_name = tx.get("security_name") or ""
                if not tx.get("isin") or self.DERIVATIVE_EXCLUDE_REGEX.search(sec_name):
                    continue
                key = (
                    tx.get("isin"),
                    tx.get("security_name"),
                    tx.get("transaction_type"),
                    tx.get("transaction_time"),
                    tx.get("quantity"),
                    tx.get("purchase_price_per_share"),
                    tx.get("brokerage")
                )
                if key not in seen:
                    seen.add(key)
                    transactions.append(tx)

        if not transactions:
            for line in self.full_text.splitlines():
                if self.DERIVATIVE_EXCLUDE_REGEX.search(line):
                    continue

                isin_match = self.ISIN_REGEX.search(line)
                if isin_match:
                    tx_items = self._parse_text_transaction_line(line, isin_match.group(1), simplified=simplified)
                    for tx in tx_items:
                        sec_name = tx.get("security_name") or ""
                        if not tx.get("isin") or self.DERIVATIVE_EXCLUDE_REGEX.search(sec_name):
                            continue
                        key = (
                            tx.get("isin"),
                            tx.get("security_name"),
                            tx.get("transaction_type"),
                            tx.get("transaction_time"),
                            tx.get("quantity"),
                            tx.get("purchase_price_per_share"),
                            tx.get("brokerage")
                        )
                        if key not in seen:
                            seen.add(key)
                            transactions.append(tx)

        # Sort transactions chronologically by transaction_time
        transactions = self._sort_transactions_by_time(transactions)
        return transactions

    def _parse_transaction_row(self, row: List[Any], isin: str, simplified: bool = True) -> List[Dict[str, Any]]:
        """Parse a table row containing an ISIN and numeric metrics."""
        cleaned_cells = [self._clean_str(c) for c in row if c is not None and self._clean_str(c) != ""]
        full_line = " ".join(cleaned_cells)
        return self._parse_text_transaction_line(full_line, isin, simplified=simplified)

    def _parse_text_transaction_line(self, line: str, isin: str, simplified: bool = True) -> List[Dict[str, Any]]:
        """
        Parse transaction line.
        Calculates:
        brokerage = round(brokerage_per_share * quantity, 2)
        Extracts:
        - security_name
        - isin
        - transaction_type ("BUY" or "SELL")
        - transaction_time
        - trade_date
        - settlement_date
        - quantity
        - purchase_price_per_share
        - brokerage
        """
        isin_idx = line.find(isin)
        if isin_idx == -1:
            return []

        post_isin = line[isin_idx + len(isin):].strip()
        num_matches = list(self.NUM_REGEX.finditer(post_isin))

        if len(num_matches) < 12:
            return []

        last_12_matches = num_matches[-12:]
        first_num_start = last_12_matches[0].start()

        security_name = post_isin[:first_num_start].strip()
        if not security_name:
            pre_isin = line[:isin_idx].strip()
            security_name = re.sub(r'^[0-9\.\s\-]+', '', pre_isin).strip()

        security_name = re.sub(r'\s*/\s*$', '', security_name).strip()
        security_name = re.sub(r'\bL\s+TD\b', 'LTD', security_name)

        if self.DERIVATIVE_EXCLUDE_REGEX.search(security_name):
            return []

        nums = [self._parse_float(m.group(0)) for m in last_12_matches]

        buy_qty = nums[0]
        buy_wap = nums[1]
        buy_brokerage_per_share = nums[2]

        sell_qty = nums[5]
        sell_wap = nums[6]
        sell_brokerage_per_share = nums[7]

        buy_qty_val = int(buy_qty) if isinstance(buy_qty, float) and buy_qty.is_integer() else buy_qty
        sell_qty_val = int(sell_qty) if isinstance(sell_qty, float) and sell_qty.is_integer() else sell_qty

        time_match = re.search(r'\b\d{1,2}:\d{2}(?::\d{2})?\b', line)
        tx_time = self._normalize_time(time_match.group(0)) if time_match else ""

        results = []

        # If there is a BUY transaction
        if buy_qty > 0:
            total_buy_brokerage = round(buy_brokerage_per_share * buy_qty, 2)
            results.append({
                "security_name": security_name,
                "isin": isin,
                "transaction_type": "BUY",
                "action": "BUY",
                "transaction_time": tx_time,
                "trade_time": tx_time,
                "trade_date": self.trade_date,
                "settlement_date": self.settlement_date,
                "quantity": buy_qty_val,
                "purchase_price_per_share": buy_wap,
                "brokerage": total_buy_brokerage
            })

        # If there is a SELL transaction
        if sell_qty > 0:
            total_sell_brokerage = round(sell_brokerage_per_share * sell_qty, 2)
            results.append({
                "security_name": security_name,
                "isin": isin,
                "transaction_type": "SELL",
                "action": "SELL",
                "transaction_time": tx_time,
                "trade_time": tx_time,
                "trade_date": self.trade_date,
                "settlement_date": self.settlement_date,
                "quantity": sell_qty_val,
                "purchase_price_per_share": sell_wap,
                "brokerage": total_sell_brokerage
            })

        # Fallback if both quantities are 0 (e.g., cancelled order row)
        if not results:
            results.append({
                "security_name": security_name,
                "isin": isin,
                "transaction_type": "BUY",
                "action": "BUY",
                "transaction_time": tx_time,
                "trade_time": tx_time,
                "trade_date": self.trade_date,
                "settlement_date": self.settlement_date,
                "quantity": 0,
                "purchase_price_per_share": buy_wap or sell_wap,
                "brokerage": 0.0
            })

        return results


def parse_contract_note(
    pdf_source: Union[str, bytes, io.BytesIO, io.BufferedIOBase],
    password: Optional[str] = None,
    simplified: bool = True,
    include_party: bool = True,
    include_details: bool = True,
    as_dict: bool = False,
    file_name: Optional[str] = None,
    template: str = "auto"
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Public library function to parse an Indian Equity Contract Note PDF.

    :param pdf_source: File path (str), raw PDF bytes, or file stream (io.BytesIO).
    :param password: Password string if the PDF is password-protected.
    :param simplified: Standardize transactions to core fields.
    :param include_party: Include client and broker party details.
    :param include_details: Include complete template_info and file_details.
    :param as_dict: Return transactions keyed by ISIN instead of list.
    :param file_name: Optional filename for reference.
    :param template: Broker template to apply ('auto', 'zerodha', 'shoonya', 'systematix', 'generic').
    :return: Parsed contract note dictionary or transaction list.
    """
    parser = ContractNoteParser(pdf_source=pdf_source, password=password, file_name=file_name, template=template)
    return parser.parse(simplified=simplified, include_party=include_party, include_details=include_details, as_dict=as_dict)


def detect_broker_template(
    pdf_source: Union[str, bytes, io.BytesIO, io.BufferedIOBase],
    password: Optional[str] = None
) -> Tuple[str, float]:
    """
    Auto-detect the broker template for the given PDF source.
    Returns a tuple of (template_id, confidence_score).
    """
    parser = ContractNoteParser(pdf_source=pdf_source, password=password)
    parser._load_and_extract_pdf()
    tmpl, conf = TemplateRegistry.detect_template(parser.full_text, parser.tables)
    return tmpl.template_id, conf


def list_supported_templates() -> List[Dict[str, str]]:
    """Return a list of all registered broker templates and metadata."""
    return TemplateRegistry.list_templates()


def main():
    parser = argparse.ArgumentParser(description="Parse Indian Equity Segment Contract Note PDF to JSON with Broker Template System.")
    parser.add_argument("pdf_path", help="Path to the contract note PDF file.")
    parser.add_argument("-t", "--template", help="Broker template to use: auto, zerodha, shoonya, systematix, generic (default: auto)", default="auto")
    parser.add_argument("-o", "--output", help="Path to write the output JSON file.", default=None)
    parser.add_argument("-p", "--password", help="PDF password if encrypted (e.g. PAN or DOB).", default=None)
    parser.add_argument("--exclude-details", action="store_true", help="Output only transactions list without client/broker/file details.")
    parser.add_argument("--as-dict", action="store_true", help="Output transactions as a dictionary keyed by ISIN.")

    args = parser.parse_args()

    try:
        data = parse_contract_note(
            args.pdf_path,
            password=args.password,
            simplified=True,
            include_party=not args.exclude_details,
            include_details=not args.exclude_details,
            as_dict=args.as_dict,
            template=args.template
        )
        json_output = json.dumps(data, indent=2, ensure_ascii=False)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_output)
            print(f"Successfully parsed contract note! Output written to: {args.output}")
        else:
            print(json_output)

    except Exception as e:
        print(f"Error parsing contract note: {e}")
        raise


if __name__ == "__main__":
    main()
