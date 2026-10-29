"""
Web Application Server for Contract Note Parser
Provides a web interface to upload Contract Note PDFs, inspect extracted
party details and transactions, view financial summaries, and download JSON files.
Uses standard Python libraries + pdfplumber.
"""

import os
import io
import json
import base64
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from contract_note_parser import parse_contract_note, ContractNoteParser

from broker_templates import TemplateRegistry
from zone_manager import ZoneManager

PORT = int(os.environ.get('PORT', 5000))
HOST = os.environ.get('HOST', '0.0.0.0')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class ContractNoteHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        url_parts = urlparse(self.path)
        path = url_parts.path

        if path in ("/", "/index.html"):
            self.serve_file(os.path.join(BASE_DIR, "templates", "index.html"), "text/html; charset=utf-8")
        elif path == "/api/docs":
            self.serve_file(os.path.join(BASE_DIR, "templates", "api_docs.html"), "text/html; charset=utf-8")
        elif path == "/api/health":
            self.send_json_response({
                "status": "ok",
                "healthy": True,
                "version": "2.0.0",
                "service": "Contract Note Parser Web Service"
            })
        elif path == "/api":
            self.send_json_response({
                "name": "Contract Note Parser API",
                "version": "2.0.0",
                "documentation": "http://localhost:5000/api/docs",
                "endpoints": {
                    "POST /api/parse": "Parse contract note PDF (Base64 payload)",
                    "GET /api/templates": "List supported broker templates",
                    "GET /api/docs": "Interactive documentation",
                    "GET /api/openapi.json": "OpenAPI specification"
                }
            })
        elif path == "/api/openapi.json":
            self.send_json_response({
                "openapi": "3.0.0",
                "info": {
                    "title": "Contract Note Parser API",
                    "version": "2.0.0",
                    "description": "API for parsing Indian stock market Equity Contract Notes with broker template system."
                },
                "paths": {
                    "/api/parse": {
                        "post": {
                            "summary": "Parse Contract Note PDF",
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "file_base64": { "type": "string" },
                                                "file_name": { "type": "string" },
                                                "password": { "type": "string" },
                                                "template": { "type": "string", "enum": ["auto", "zerodha", "shoonya", "systematix", "generic"] }
                                            },
                                            "required": ["file_base64"]
                                        }
                                    }
                                }
                            },
                            "responses": { "200": { "description": "Parsed contract note output" } }
                        }
                    },
                    "/api/templates": {
                        "get": {
                            "summary": "List Supported Templates",
                            "responses": { "200": { "description": "List of broker templates" } }
                        }
                    }
                }
            })
        elif path == "/api/templates":
            self.send_json_response(TemplateRegistry.list_templates())
        elif path == "/api/zones":
            query_params = parse_qs(url_parts.query)
            t_name = query_params.get("template", [None])[0]
            zones = ZoneManager.list_zones(template_name=t_name)
            self.send_json_response({"zones": zones, "total": len(zones)})
        elif path == "/sample_screenshot_output.json":
            self.serve_file(os.path.join(BASE_DIR, "sample_screenshot_output.json"), "application/json")
        elif path == "/sample_screenshot_output_2.json":
            self.serve_file(os.path.join(BASE_DIR, "sample_screenshot_output_2.json"), "application/json")
        elif path == "/sample_screenshot_output_3.json":
            self.serve_file(os.path.join(BASE_DIR, "sample_screenshot_output_3.json"), "application/json")
        elif path == "/sample_screenshot_output_shoonya.json":
            self.serve_file(os.path.join(BASE_DIR, "sample_screenshot_output_shoonya.json"), "application/json")
        elif path == "/parsed_output.json":
            self.serve_file(os.path.join(BASE_DIR, "parsed_output.json"), "application/json")
        elif path == "/sample_contract_note.pdf":
            self.serve_file(os.path.join(BASE_DIR, "sample_files", "sample_contract_note.pdf"), "application/pdf")
        elif path == "/sample_contract_note_2.pdf":
            self.serve_file(os.path.join(BASE_DIR, "sample_files", "contract_note_screenshot2.pdf"), "application/pdf")
        elif path == "/sample_contract_note_3.pdf":
            self.serve_file(os.path.join(BASE_DIR, "sample_files", "COMM_CONTRACT_15102026_HN410_0099074.PDF"), "application/pdf")
        elif path == "/sample_contract_note_shoonya.pdf":
            self.serve_file(os.path.join(BASE_DIR, "sample_files", "shoonya_sample_contract_note.pdf"), "application/pdf")
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        url_parts = urlparse(self.path)
        path = url_parts.path

        if path == "/api/parse":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)

                pdf_base64 = payload.get("file_base64")
                file_name = payload.get("file_name", "contract_note.pdf")
                password = payload.get("password") or None
                template = payload.get("template") or "auto"

                if not pdf_base64:
                    self.send_json_response({"error": "No file content provided"}, status=400)
                    return

                # Decode base64 and parse in-memory directly without disk writes
                pdf_bytes = base64.b64decode(pdf_base64)
                parser = ContractNoteParser(pdf_source=pdf_bytes, password=password, file_name=file_name, template=template)
                parsed_result = parser.parse(simplified=True, include_party=True, include_details=True)
                self.send_json_response(parsed_result)

            except Exception as e:
                self.send_json_response({"error": str(e)}, status=500)

        elif path == "/api/zones":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)

                t_name = payload.get("template_name")
                f_name = payload.get("field_name")
                if not t_name or not f_name:
                    self.send_json_response({"error": "template_name and field_name are required"}, status=400)
                    return

                page_num = int(payload.get("page_num", 1))
                x0 = float(payload.get("x0", 0.0))
                top = float(payload.get("top", 0.0))
                x1 = float(payload.get("x1", 0.0))
                bottom = float(payload.get("bottom", 0.0))
                desc = payload.get("description", "")

                saved = ZoneManager.save_zone(
                    template_name=t_name,
                    field_name=f_name,
                    page_num=page_num,
                    x0=x0,
                    top=top,
                    x1=x1,
                    bottom=bottom,
                    description=desc
                )
                self.send_json_response({"success": True, "zone": saved})
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=500)

        elif path == "/api/zones/delete":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                zone_id = payload.get("id")
                if not zone_id:
                    self.send_json_response({"error": "Zone id is required"}, status=400)
                    return
                ok = ZoneManager.delete_zone(int(zone_id))
                self.send_json_response({"success": ok})
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=500)
        else:
            self.send_error(404, "Not Found")

    def send_json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, filepath: str, content_type: str):
        if not os.path.exists(filepath):
            self.send_error(404, "File not found")
            return
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def run_server():
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, ContractNoteHandler)
    display_host = "localhost" if HOST in ("0.0.0.0", "127.0.0.1") else HOST
    print(f"Contract Note Parser Server running at http://{display_host}:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    run_server()
