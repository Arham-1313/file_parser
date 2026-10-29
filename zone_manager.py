"""
SQLite Coordinate Zone Manager for Contract Note Templates.
Stores and retrieves spatial bounding boxes (x0, top, x1, bottom) for different
brokers and document fields (e.g. party_name, client_address, client_pan, etc.).
"""

import os
import sqlite3
from typing import Dict, Any, List, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template_zones.db")


class ZoneManager:
    @staticmethod
    def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def init_db(cls, db_path: str = DB_PATH):
        """Initialize SQLite table and insert default template coordinate zones."""
        with cls.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS template_coordinate_zones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_name TEXT NOT NULL COLLATE NOCASE,
                    field_name TEXT NOT NULL COLLATE NOCASE,
                    page_num INTEGER NOT NULL DEFAULT 1,
                    x0 REAL NOT NULL,
                    top REAL NOT NULL,
                    x1 REAL NOT NULL,
                    bottom REAL NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(template_name, field_name)
                )
            """)

            # Seed default zones if empty
            cursor.execute("SELECT COUNT(*) FROM template_coordinate_zones")
            count = cursor.fetchone()[0]
            if count == 0:
                default_zones = [
                    (
                        "systematix",
                        "party_name",
                        1,
                        19.0,
                        142.0,
                        398.0,
                        158.0,
                        "Extended company name zone up to settlement table boundary at x=400.0"
                    ),
                    (
                        "systematix",
                        "client_address",
                        1,
                        19.0,
                        158.0,
                        398.0,
                        198.0,
                        "Designated client address block below company name (before phone/tax details)"
                    ),
                    (
                        "zerodha",
                        "party_name",
                        1,
                        20.0,
                        110.0,
                        300.0,
                        130.0,
                        "Zerodha client name zone"
                    ),
                    (
                        "shoonya",
                        "party_name",
                        1,
                        30.0,
                        95.0,
                        280.0,
                        115.0,
                        "Shoonya client name zone"
                    ),
                ]
                cursor.executemany("""
                    INSERT INTO template_coordinate_zones 
                    (template_name, field_name, page_num, x0, top, x1, bottom, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, default_zones)
            conn.commit()

    @classmethod
    def list_zones(cls, template_name: Optional[str] = None, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
        """List all coordinate zones or filter by template_name."""
        cls.init_db(db_path)
        with cls.get_connection(db_path) as conn:
            cursor = conn.cursor()
            if template_name and template_name.lower() not in ("all", "auto", ""):
                cursor.execute("""
                    SELECT * FROM template_coordinate_zones 
                    WHERE template_name = ? COLLATE NOCASE 
                    ORDER BY template_name, field_name
                """, (template_name.strip(),))
            else:
                cursor.execute("SELECT * FROM template_coordinate_zones ORDER BY template_name, field_name")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    @classmethod
    def get_zone(cls, template_name: str, field_name: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
        """Retrieve coordinate zone for a specific template and field."""
        cls.init_db(db_path)
        with cls.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM template_coordinate_zones 
                WHERE template_name = ? COLLATE NOCASE AND field_name = ? COLLATE NOCASE
            """, (template_name.strip(), field_name.strip()))
            row = cursor.fetchone()
            return dict(row) if row else None

    @classmethod
    def save_zone(
        cls,
        template_name: str,
        field_name: str,
        page_num: int,
        x0: float,
        top: float,
        x1: float,
        bottom: float,
        description: str = "",
        db_path: str = DB_PATH
    ) -> Dict[str, Any]:
        """Insert or update a coordinate zone."""
        cls.init_db(db_path)
        template_name = template_name.strip().lower()
        field_name = field_name.strip().lower()

        with cls.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO template_coordinate_zones 
                (template_name, field_name, page_num, x0, top, x1, bottom, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(template_name, field_name) DO UPDATE SET
                    page_num = excluded.page_num,
                    x0 = excluded.x0,
                    top = excluded.top,
                    x1 = excluded.x1,
                    bottom = excluded.bottom,
                    description = excluded.description,
                    updated_at = CURRENT_TIMESTAMP
            """, (template_name, field_name, int(page_num), float(x0), float(top), float(x1), float(bottom), description))
            conn.commit()

        return cls.get_zone(template_name, field_name, db_path)

    @classmethod
    def delete_zone(cls, zone_id: int, db_path: str = DB_PATH) -> bool:
        """Delete a coordinate zone by ID."""
        cls.init_db(db_path)
        with cls.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM template_coordinate_zones WHERE id = ?", (zone_id,))
            conn.commit()
            return cursor.rowcount > 0

    @classmethod
    def extract_spatial_crops_for_pages(cls, pdf_pages: List[Any], db_path: str = DB_PATH) -> Dict[str, Dict[str, str]]:
        """
        Pre-crops all zones registered in SQLite for the provided open pdfplumber pages.
        Returns a dictionary: { template_name: { field_name: extracted_text } }
        """
        all_zones = cls.list_zones(db_path=db_path)
        extracted: Dict[str, Dict[str, str]] = {}

        if not pdf_pages:
            return extracted

        for z in all_zones:
            t_name = z["template_name"].lower()
            f_name = z["field_name"].lower()
            page_idx = z["page_num"] - 1

            if 0 <= page_idx < len(pdf_pages):
                page = pdf_pages[page_idx]
                bbox = (z["x0"], z["top"], z["x1"], z["bottom"])
                try:
                    cropped = page.crop(bbox)
                    text = cropped.extract_text() or ""
                    if t_name not in extracted:
                        extracted[t_name] = {}
                    extracted[t_name][f_name] = text.strip()
                except Exception:
                    pass

        return extracted


# Initialize on import
ZoneManager.init_db()
