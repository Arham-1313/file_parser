"""
Broker-Specific Template System for Contract Note Parser.
Provides specialized spatial layout extraction, coordinate zone parsing,
and address segregation for:
1. Zerodha Broking Limited
2. Shoonya (Finvasia Securities Private Limited)
3. Systematix Shares and Stocks (India) Limited
4. Generic / Universal Fallback

Guarantees:
- Client address and Broker address are NEVER confused or swapped.
- If client address is missing from the designated client box, client address is set to null
  (it will NEVER fall back to the broker's registered office address).
- Broker PAN and Client PAN are isolated to their respective zones.
- Template detection scores confidence based on broker identity, regulatory IDs, and layout patterns.
"""

import re
from typing import Dict, Any, List, Optional, Tuple, Set


def clean_text(val: Optional[str]) -> str:
    if val is None:
        return ""
    return " ".join(str(val).replace("\n", " ").split()).strip()


def is_address_similar(addr1: Optional[str], addr2: Optional[str]) -> bool:
    """Check if two addresses refer to the same location or share substantial tokens."""
    if not addr1 or not addr2:
        return False
    a1 = re.sub(r'[^a-z0-9]', '', addr1.lower())
    a2 = re.sub(r'[^a-z0-9]', '', addr2.lower())
    if a1 in a2 or a2 in a1:
        return True

    # Word-level token overlap
    tokens1 = set(re.findall(r'\b[a-z0-9]{4,}\b', addr1.lower()))
    tokens2 = set(re.findall(r'\b[a-z0-9]{4,}\b', addr2.lower()))
    if not tokens1 or not tokens2:
        return False
    overlap = len(tokens1 & tokens2) / min(len(tokens1), len(tokens2))
    return overlap >= 0.5


class BaseBrokerTemplate:
    """Base class for all broker contract note templates."""
    template_id: str = "base"
    display_name: str = "Base Template"
    description: str = "Base contract note template"

    default_broker_name: Optional[str] = None
    default_broker_address: Optional[str] = None
    default_sebi_reg: Optional[str] = None
    default_cin: Optional[str] = None
    default_pan: Optional[str] = None
    default_gstin: Optional[str] = None

    broker_keywords: List[str] = []
    known_broker_address_terms: List[str] = []

    PAN_REGEX = re.compile(r'\b([A-Z]{5}[0-9]{4}[A-Z])\b')
    SEBI_REGEX = re.compile(r'\b(INZ[0-9]{7,10})\b')
    CIN_REGEX = re.compile(r'\b([LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\b')
    GSTIN_REGEX = re.compile(r'\b(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d])\b')
    DATE_REGEX = re.compile(r'\b(?:\d{1,2}[-/\.](?:[A-Za-z]{3,9}|\d{1,2})[-/\.]\d{2,4}|\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})\b')

    def match_score(self, text: str, tables: List[List[List[Any]]]) -> float:
        """Calculate match score between 0.0 and 1.0 indicating confidence."""
        score = 0.0
        text_lower = text.lower()

        # Check broker keywords
        matches = sum(1 for kw in self.broker_keywords if kw in text_lower)
        if self.broker_keywords:
            score += 0.5 * (matches / len(self.broker_keywords))

        # Check regulatory IDs
        if self.default_sebi_reg and self.default_sebi_reg.lower() in text_lower:
            score += 0.3
        if self.default_cin and self.default_cin.lower() in text_lower:
            score += 0.2
        if self.default_pan and self.default_pan.lower() in text_lower:
            score += 0.2

        return min(round(score, 2), 1.0)

    def extract_broker_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        pdf_pages: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """Extract broker details from broker designated area / header."""
        header_text = pages_text[0] if pages_text else full_text
        header_lines = header_text.splitlines()[:15]
        header_zone = "\n".join(header_lines)

        # Broker Name
        broker_name = self.default_broker_name
        if not broker_name:
            for line in header_lines[:8]:
                l_str = line.strip()
                if any(k in l_str.lower() for k in ["limited", "ltd", "securities", "broking", "capital"]):
                    if not any(x in l_str.lower() for x in ["contract note", "trade date", "client", "to,"]):
                        broker_name = l_str
                        break

        # Broker Address
        broker_address = None
        b_addr_match = re.search(
            r'(?:Regd\.?\s*Office|Registered\s*Office|Corporate\s*Office|Dealing\s*Office)\s*[:\-]?\s*([^\n\r\|]+(?:\n[^\n\r\|]+)?)',
            header_zone,
            re.IGNORECASE
        )
        if b_addr_match:
            raw = b_addr_match.group(1).strip()
            broker_address = clean_text(re.split(r'\b(?:CIN|SEBI|GSTIN|PAN|Phone|Tel|Email|Fax)\b', raw, flags=re.IGNORECASE)[0])
        elif self.default_broker_address:
            broker_address = self.default_broker_address

        # SEBI Registration
        sebi_match = self.SEBI_REGEX.search(header_zone) or self.SEBI_REGEX.search(full_text)
        sebi_reg = sebi_match.group(1) if sebi_match else self.default_sebi_reg

        # CIN
        cin_match = self.CIN_REGEX.search(header_zone) or self.CIN_REGEX.search(full_text)
        cin = cin_match.group(1) if cin_match else self.default_cin

        # GSTIN
        gstin_match = self.GSTIN_REGEX.search(header_zone) or self.GSTIN_REGEX.search(full_text)
        gstin = gstin_match.group(1) if gstin_match else self.default_gstin

        # Broker PAN
        broker_pan = None
        bp_match = re.search(r'(?:Broker|Member|Company)\s*PAN\s*[:\-]?\s*([A-Z]{5}[0-9]{4}[A-Z])', header_zone, re.IGNORECASE)
        if bp_match:
            broker_pan = bp_match.group(1)
        elif self.default_pan:
            broker_pan = self.default_pan

        # Contract Note No
        cn_no = None
        cn_patterns = [
            r'Contract\s*Note\s*No\.?\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)',
            r'CN\s*(?:No\.?|Number)\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)',
            r'Invoice\s*Reference\s*Number\s*\([^\)]*\)\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)'
        ]
        for pat in cn_patterns:
            m = re.search(pat, header_text, re.IGNORECASE)
            if m:
                cn_no = m.group(1).strip()
                break

        # IRN
        irn = None
        irn_match = re.search(r'(?:Invoice\s*Reference\s*(?:No\.?|Number)|IRN)\s*(?:\([^\)]*\))?\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)', header_text, re.IGNORECASE)
        if irn_match:
            irn = irn_match.group(1).strip()

        # Clearing Corporation
        clearing_corp = None
        cc_match = re.search(r'(?:Name\s*of\s*Clearing\s*Corporation|Clearing\s*Corporation)\s*[:\-]?\s*([^\n\r\|]+)', full_text, re.IGNORECASE)
        if cc_match:
            clearing_corp = clean_text(cc_match.group(1))

        return {
            "name": broker_name,
            "address": broker_address,
            "sebi_registration_no": sebi_reg,
            "cin": cin,
            "gstin": gstin,
            "pan": broker_pan,
            "contract_note_no": cn_no,
            "irn": irn,
            "clearing_corporation": clearing_corp
        }

    def extract_client_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        broker_details: Dict[str, Any],
        pdf_pages: Optional[List[Any]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Extract client details strictly from designated client block/table.
        Guarantees that broker address is never copied as client address.
        """
        first_page = pages_text[0] if pages_text else full_text

        # 1. Client / Party Name
        party_name = None
        name_patterns = [
            r'(?:Party\s*/\s*Client|Client|Party)\s*Name\s*[:\-]\s*([^\n\r\|]+)',
            r'Name\s*of\s*Client\s*[:\-]\s*([^\n\r\|]+)',
            r'To\s*,\s*(?:Client\s*Name\s*[:\-])?\s*([^\n\r]+)',
            r'([A-Z][a-zA-Z\s]{2,35})\s*\([A-Za-z0-9]+\)\s+Dealing\s*Office'
        ]
        for pat in name_patterns:
            m = re.search(pat, first_page, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                cand = re.split(r'\b(?:Client\s*PAN|Client\s*Code|Client\s*ID|Client\s*UCC|PAN|UCC|Address|Exchange)\b', cand, flags=re.IGNORECASE)[0].strip()
                if cand and len(cand) > 2 and not any(k in cand.lower() for k in ["limited", "ltd", "securities"]):
                    party_name = cand
                    break

        # 2. Client ID / UCC
        client_id = None
        ucc_patterns = [
            r'(?:Client\s*(?:ID|Code)|UCC(?:\s*Code)?|Trading\s*Code|Backoffice\s*Code)\s*(?:/\s*UCC)?\s*[:\-]\s*([A-Za-z0-9]+)',
            r'UCC\s*[:\-]\s*([A-Za-z0-9]+)',
            r'UCC\s*of\s*Code\s*[:\-]?\s*([A-Za-z0-9]+)'
        ]
        for pat in ucc_patterns:
            m = re.search(pat, first_page, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val.lower() != "of":
                    client_id = val
                    break

        if not client_id:
            # Check standalone 6-character broker UCC formats (e.g. DA9605 or FA9921)
            for table in tables:
                for row in table:
                    for cell in row:
                        if cell:
                            cs = str(cell).strip()
                            if re.fullmatch(r'[A-Z]{2}[0-9]{4,6}', cs):
                                client_id = cs
                                break
                    if client_id:
                        break
                if client_id:
                    break

        # 3. Client PAN
        broker_pan = broker_details.get("pan")
        client_pan = None
        c_pan_match = re.search(r'(?:Client\s*)?PAN\s*(?:of\s*Client|No\.?|Number)?\s*[:\-]?\s*([A-Z]{5}[0-9]{4}[A-Z])', first_page, re.IGNORECASE)
        if c_pan_match:
            candidate_pan = c_pan_match.group(1).strip()
            if candidate_pan != broker_pan:
                client_pan = candidate_pan

        if not client_pan:
            # Find all PANs on page 1 and take the one that is NOT the broker's PAN
            pans = self.PAN_REGEX.findall(first_page)
            for p in pans:
                if p != broker_pan:
                    client_pan = p
                    break

        # 4. Client Address (STRICT ZONE EXTRACTION)
        client_address = None
        # Check inside client table cells first (most reliable)
        for table in tables:
            for row in table:
                for cell in row:
                    if not cell:
                        continue
                    cell_s = str(cell)
                    if any(term in cell_s for term in ["Party / Client Name", "Client Name", "To,"]):
                        addr_m = re.search(r'Address\s*[:\-]\s*([^\n\r]+(?:\n[^\n\r]+)?)', cell_s, re.IGNORECASE)
                        if addr_m:
                            cand_addr = clean_text(re.split(r'\b(?:PAN|Segment|Exchange|Client)\b', addr_m.group(1), flags=re.IGNORECASE)[0])
                            if cand_addr and not is_address_similar(cand_addr, broker_details.get("address")):
                                client_address = cand_addr
                                break

        # Text search inside client zone (delimited from To, or Client Name down to Transaction Table)
        if not client_address:
            c_start = re.search(r'\b(?:To\s*[,:]|Client\s*Name|Party\s*/\s*Client)\b', first_page, re.IGNORECASE)
            if c_start:
                client_zone = first_page[c_start.start():]
                c_end = re.search(r'\b(?:Order\s*No|Trade\s*No|Security\s*Description|ISIN|Sir/\s*Madam)\b', client_zone, re.IGNORECASE)
                if c_end:
                    client_zone = client_zone[:c_end.start()]

                addr_m = re.search(r'(?:Address|Client\s*Address)\s*[:\-]\s*([^\n\r]+)', client_zone, re.IGNORECASE)
                if addr_m:
                    cand_addr = clean_text(re.split(r'\b(?:Exchange|Segment|PAN|Trade|Client|UCC|Dealing)\b', addr_m.group(1), flags=re.IGNORECASE)[0])
                    if cand_addr and not is_address_similar(cand_addr, broker_details.get("address")):
                        client_address = cand_addr

        # ANTI-CONFUSION VALIDATION:
        # If client address is similar to broker address or contains known broker terms, discard it!
        if client_address:
            if is_address_similar(client_address, broker_details.get("address")):
                client_address = None
            elif any(term.lower() in client_address.lower() for term in self.known_broker_address_terms):
                client_address = None

        return {
            "name": party_name,
            "client_id": client_id,
            "pan": client_pan,
            "address": client_address
        }

    def format_output(
        self,
        client_details: Dict[str, Any],
        broker_details: Dict[str, Any],
        file_details: Dict[str, Any],
        transactions: List[Dict[str, Any]],
        confidence: float = 1.0,
        detection_mode: str = "manual"
    ) -> Dict[str, Any]:
        """Format the output dictionary according to template specification."""
        return {
            "template_info": {
                "template_id": self.template_id,
                "template_name": self.display_name,
                "description": self.description,
                "detection_mode": detection_mode,
                "confidence": confidence
            },
            "client_details": client_details,
            "broker_details": broker_details,
            "file_details": file_details,
            "party_details": {
                "name": client_details.get("name"),
                "party_name": client_details.get("name"),
                "client_id": client_details.get("client_id"),
                "pan": client_details.get("pan"),
                "pan_number": client_details.get("pan"),
                "address": client_details.get("address"),
                "contract_note_no": broker_details.get("contract_note_no")
            },
            "transactions": transactions
        }


class ZerodhaTemplate(BaseBrokerTemplate):
    """Template for Zerodha Broking Limited."""
    template_id = "zerodha"
    display_name = "Zerodha Broking Limited"
    description = "Optimized spatial parser for Zerodha contract notes (WAP, ISIN Net Obligation, DA UCC)"

    default_broker_name = "ZERODHA BROKING LTD."
    default_broker_address = "#153/154, 4th Cross, Dollars Colony, Opp. Clarence Public School, J.P Nagar 4th Phase, Bangalore - 560078"
    default_sebi_reg = "INZ000031633"
    default_cin = "U67120KA2010PLC055555"
    default_pan = "AABCZ2123C"
    default_gstin = "29AABCZ2123C1Z6"

    broker_keywords = [
        "zerodha", "inz000031633", "u67120ka2010plc055555",
        "net obligation for isin", "wap (across exchanges)", "ncl-cash", "ncl-f&o"
    ]
    known_broker_address_terms = [
        "dollars colony", "jp nagar", "j.p nagar", "clarence", "bangalore", "bengaluru", "560078"
    ]

    def extract_broker_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        pdf_pages: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        details = super().extract_broker_details(full_text, tables, pages_text, pdf_pages)
        if not details.get("name") or "zerodha" not in str(details.get("name", "")).lower():
            if "zerodha" in full_text.lower():
                details["name"] = self.default_broker_name
        if not details.get("address"):
            details["address"] = self.default_broker_address
        if not details.get("sebi_registration_no"):
            details["sebi_registration_no"] = self.default_sebi_reg
        if not details.get("cin"):
            details["cin"] = self.default_cin
        if not details.get("gstin"):
            details["gstin"] = self.default_gstin
        return details

    def extract_client_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        broker_details: Dict[str, Any],
        pdf_pages: Optional[List[Any]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        client = super().extract_client_details(full_text, tables, pages_text, broker_details, pdf_pages, **kwargs)

        # In Zerodha, client UCC format is often 6 alphanumeric chars like DA9605
        if not client.get("client_id"):
            m = re.search(r'\b([A-Z]{2}[0-9]{4})\b', full_text)
            if m:
                client["client_id"] = m.group(1)

        # In Zerodha, if address is not explicitly labeled for client, DO NOT take Bangalore address
        addr = client.get("address")
        if addr and any(term in addr.lower() for term in self.known_broker_address_terms):
            client["address"] = None

        return client


class ShoonyaTemplate(BaseBrokerTemplate):
    """Template for Shoonya / Finvasia Securities Private Limited."""
    template_id = "shoonya"
    display_name = "Shoonya (Finvasia Securities Pvt Ltd)"
    description = "Optimized for Finvasia / Shoonya contract notes with order/trade rows & Mohali/Chandigarh segregation"

    default_broker_name = "FINVASIA SECURITIES PRIVATE LIMITED (SHOONYA)"
    default_broker_address = "#1108, Sector 21-B, Chandigarh - 160022"
    default_sebi_reg = "INZ000176037"
    default_cin = "U74992CH2011PTC032718"
    default_pan = "AABCF6759K"
    default_gstin = "04AABCF6759K1Z5"

    broker_keywords = [
        "shoonya", "finvasia", "inz000176037", "u74992ch2011ptc032718", "aabcf6759k"
    ]
    known_broker_address_terms = [
        "sector 21-b", "chandigarh", "160022", "finvasia tower", "phase 8b", "mohali - 160055"
    ]

    def extract_broker_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        pdf_pages: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        details = super().extract_broker_details(full_text, tables, pages_text, pdf_pages)
        if not details.get("name") or not any(k in str(details.get("name", "")).lower() for k in ["finvasia", "shoonya"]):
            if any(k in full_text.lower() for k in ["finvasia", "shoonya"]):
                details["name"] = self.default_broker_name

        if not details.get("address"):
            details["address"] = self.default_broker_address
        if not details.get("pan"):
            details["pan"] = self.default_pan
        if not details.get("cin"):
            details["cin"] = self.default_cin
        if not details.get("sebi_registration_no"):
            details["sebi_registration_no"] = self.default_sebi_reg

        # Contract Note No for Shoonya
        if not details.get("contract_note_no"):
            m = re.search(r'(?:CN\s*No\.?|Contract\s*Note\s*No\.?)\s*[:\-]?\s*([A-Za-z0-9\-_/]+)', full_text, re.IGNORECASE)
            if m:
                details["contract_note_no"] = m.group(1).strip()

        return details

    def extract_client_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        broker_details: Dict[str, Any],
        pdf_pages: Optional[List[Any]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        client = super().extract_client_details(full_text, tables, pages_text, broker_details, pdf_pages, **kwargs)

        # Look specifically in "To," section for client details
        first_page = pages_text[0] if pages_text else full_text
        if not client.get("name") or "client" in str(client.get("name", "")).lower():
            m = re.search(r'To\s*,\s*(?:\n|\s+)(?:Client\s*Name\s*[:\-])?\s*([A-Za-z\s]{3,35})', first_page, re.IGNORECASE)
            if m:
                clean_n = clean_text(re.split(r'\b(?:Client|Address|UCC|PAN)\b', m.group(1), flags=re.IGNORECASE)[0])
                if clean_n:
                    client["name"] = clean_n

        # Strict check: Never allow Finvasia's Chandigarh / Mohali broker address
        addr = client.get("address")
        if addr and any(term in addr.lower() for term in self.known_broker_address_terms):
            client["address"] = None

        return client


class SystematixTemplate(BaseBrokerTemplate):
    """Template for Systematix Shares and Stocks (India) Limited."""
    template_id = "systematix"
    display_name = "Systematix Shares and Stocks (India) Limited"
    description = "Optimized for Systematix layout (Settlement Detail & Clearing Corp banner, Scrip Totals)"

    default_broker_name = "SYSTEMATIX SHARES AND STOCKS (INDIA) LIMITED"
    default_broker_address = "The Capital, A-Wing, No. 603-606, 6th Floor, Plot No. C-70, G-Block, Bandra Kurla Complex, Bandra (East), Mumbai - 400 051"
    default_sebi_reg = "INZ000171134"
    default_cin = "U65993MH1995PLC268414"
    default_pan = "AAACS1392A"
    default_gstin = "27AAACS1392A1ZN"

    broker_keywords = [
        "systematix", "inz000171134", "u65993mh1995plc268414", "aaacs1392a",
        "name of clearing corporation & segment", "settlement detail"
    ]
    known_broker_address_terms = [
        "the capital", "bandra kurla complex", "bandra (east)", "mumbai - 400 051", "bkc"
    ]

    def extract_broker_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        pdf_pages: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        details = super().extract_broker_details(full_text, tables, pages_text, pdf_pages)
        if not details.get("name") or "systematix" not in str(details.get("name", "")).lower():
            if "systematix" in full_text.lower():
                details["name"] = self.default_broker_name

        if not details.get("address"):
            details["address"] = self.default_broker_address
        if not details.get("sebi_registration_no"):
            details["sebi_registration_no"] = self.default_sebi_reg
        if not details.get("cin"):
            details["cin"] = self.default_cin
        if not details.get("pan"):
            details["pan"] = self.default_pan
        # Guard: Never assign client's state GSTIN to Systematix broker details
        if details.get("gstin") and self.default_pan not in str(details.get("gstin")):
            details["gstin"] = self.default_gstin
        if not details.get("gstin"):
            details["gstin"] = self.default_gstin

        # Guard: Invalid IRN
        if details.get("irn") and any(k in str(details.get("irn")).lower() for k in ["settlement", "normal", "ncl"]):
            details["irn"] = None

        # Clearing Corporation
        if not details.get("clearing_corporation") or details.get("clearing_corporation") == "&":
            if "clearing corporation" in full_text.lower():
                details["clearing_corporation"] = "Cash Seg. NCL / F & O Seg. NCL"

        return details

    def extract_client_details(
        self,
        full_text: str,
        tables: List[List[List[Any]]],
        pages_text: List[str],
        broker_details: Dict[str, Any],
        pdf_pages: Optional[List[Any]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        client = super().extract_client_details(full_text, tables, pages_text, broker_details, pdf_pages, **kwargs)

        first_p = pages_text[0] if pages_text else full_text
        spatial_data = kwargs.get("spatial_data") or {}

        # 1. Spatial Party Name & Address extraction from SQLite Table
        party_name_val = None
        addr_val = None

        if spatial_data.get("party_name"):
            cand = spatial_data["party_name"].strip()
            if cand:
                party_name_val = cand
        elif spatial_data.get("systematix_party_name"):
            cand = spatial_data["systematix_party_name"].strip()
            if cand:
                party_name_val = cand

        if spatial_data.get("client_address"):
            addr_val = spatial_data["client_address"].strip()
        elif spatial_data.get("systematix_address"):
            addr_val = spatial_data["systematix_address"].strip()

        elif pdf_pages and len(pdf_pages) > 0:
            try:
                p0 = pdf_pages[0]
                # Party Name: x0=19.0 to x1=398.0 (stops right before the settlement table at x=400.0)
                crop_party = p0.crop((19.0, 142.0, 398.0, 158.0)).extract_text() or ""
                if crop_party.strip():
                    party_name_val = crop_party.strip()

                # Client Address: x0=19.0 to x1=398.0, y=158.0 to 198.0
                crop_addr = p0.crop((19.0, 158.0, 398.0, 198.0)).extract_text() or ""
                lines = [l.strip() for l in crop_addr.split("\n") if l.strip()]
                if lines:
                    addr_val = ", ".join(lines)
            except Exception:
                pass

        # 2. Text-based fallback for Party Name
        if not party_name_val and first_p:
            m_td = re.search(r'TRADE\s*DATE[^\n]*\n([A-Za-z0-9\s\.\-&/]+(?:\([A-Za-z0-9]+\))?)', first_p, re.IGNORECASE)
            if m_td:
                cand = m_td.group(1).strip()
                if len(cand) > 3 and not any(k in cand.lower() for k in ["settlement", "systematix", "contract note"]):
                    party_name_val = cand

        if party_name_val:
            client["name"] = party_name_val
            # Extract client UCC code if attached in parentheses, e.g. KLJ PLASTICIZERS LIMITED(HN410)
            m_ucc = re.search(r'\(([A-Za-z0-9]+)\)$', party_name_val)
            if m_ucc and not client.get("client_id"):
                client["client_id"] = m_ucc.group(1)

        if addr_val and not client.get("address"):
            client["address"] = addr_val

        # 3. Client PAN: Check for 'PAN of Client.: XXXXX0000X' or 'PAN of Client'
        if not client.get("pan") and first_p:
            m_pan = re.search(r'PAN\s*of\s*Client\.?\s*[:\-]?\s*([A-Z]{5}[0-9]{4}[A-Z])', first_p, re.IGNORECASE)
            if m_pan:
                client["pan"] = m_pan.group(1)

        # 4. Trading Back Office Code (UCC)
        if not client.get("client_id") and first_p:
            m_code = re.search(r'(?:Trading\s*Back\s*office\s*code|UCC\s*of\s*Client)\s*[:\-]?\s*([A-Za-z0-9]+)', first_p, re.IGNORECASE)
            if m_code:
                client["client_id"] = m_code.group(1)

        # 5. Client GSTIN
        if not client.get("gstin") and first_p:
            m_cgst = re.search(r'GSTIN\s*of\s*Client\.?\s*[:\-]?\s*(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d])', first_p, re.IGNORECASE)
            if m_cgst:
                client["gstin"] = m_cgst.group(1)

        # Guard: In Systematix notes where client PAN is missing, never assign Systematix's PAN (AAACS1392A) to client!
        if client.get("pan") == self.default_pan:
            client["pan"] = None

        # Guard: Never assign BKC Mumbai broker address to client!
        addr = client.get("address")
        if addr and any(term in addr.lower() for term in self.known_broker_address_terms):
            client["address"] = None

        return client


class GenericTemplate(BaseBrokerTemplate):
    """Universal template for other SEBI registered brokers."""
    template_id = "generic"
    display_name = "Standard / Generic SEBI Broker"
    description = "Universal extractor with strict boundary segregation between broker and client zones"

    def match_score(self, text: str, tables: List[List[List[Any]]]) -> float:
        # Generic has baseline 0.1 score
        return 0.1


class TemplateRegistry:
    """Registry and factory for broker templates."""

    TEMPLATES: Dict[str, BaseBrokerTemplate] = {
        "zerodha": ZerodhaTemplate(),
        "shoonya": ShoonyaTemplate(),
        "systematix": SystematixTemplate(),
        "generic": GenericTemplate()
    }

    @classmethod
    def get_template(cls, template_id: Optional[str]) -> BaseBrokerTemplate:
        if not template_id or template_id.lower() in ("auto", "none", "default"):
            return cls.TEMPLATES["generic"]
        return cls.TEMPLATES.get(template_id.lower(), cls.TEMPLATES["generic"])

    @classmethod
    def detect_template(cls, text: str, tables: List[List[List[Any]]]) -> Tuple[BaseBrokerTemplate, float]:
        """Automatically detect the best matching template from document contents."""
        best_template = cls.TEMPLATES["generic"]
        highest_score = 0.0

        for tid in ["zerodha", "shoonya", "systematix"]:
            tmpl = cls.TEMPLATES[tid]
            score = tmpl.match_score(text, tables)
            if score > highest_score and score >= 0.35:
                highest_score = score
                best_template = tmpl

        if highest_score < 0.35:
            return cls.TEMPLATES["generic"], 0.5
        return best_template, highest_score

    @classmethod
    def list_templates(cls) -> List[Dict[str, str]]:
        return [
            {
                "id": "auto",
                "name": "Auto-Detect Broker (Smart)",
                "description": "Automatically inspects document header, regulatory IDs, and layout patterns"
            },
            {
                "id": "zerodha",
                "name": "Zerodha Broking Ltd.",
                "description": "Optimized for Zerodha contract notes (WAP, ISIN Net Obligation, DA UCC)"
            },
            {
                "id": "shoonya",
                "name": "Shoonya (Finvasia)",
                "description": "Optimized for Finvasia / Shoonya contract notes with order rows & distinct addresses"
            },
            {
                "id": "systematix",
                "name": "Systematix Shares & Stocks",
                "description": "Optimized for Systematix layout (Settlement Detail, Scrip Totals, Clearing Corp)"
            },
            {
                "id": "generic",
                "name": "Standard / Generic SEBI Broker",
                "description": "Universal layout parser for all other brokers"
            }
        ]
