"""Quick test of the PyMuPDF fallback PDF parser."""
import sys, os
sys.path.insert(0, ".")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass

from src.ingestion.parsers.unstructured_parser import UnstructuredParser
from src.ingestion.interfaces import RawDocument

# Minimal valid PDF with text content
pdf_bytes = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type /Pages /Kids[3 0 R] /Count 1>>endobj\n"
    b"3 0 obj<</Type /Page /Parent 2 0 R /MediaBox[0 0 612 792]"
    b"/Contents 4 0 R /Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 50>>stream\n"
    b"BT /F1 12 Tf 100 700 Td (Battery Specification Rev01) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>endobj\n"
    b"xref\n0 6\n"
    b"0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n"
    b"0000000115 00000 n\n0000000266 00000 n\n0000000366 00000 n\n"
    b"trailer<</Size 6 /Root 1 0 R>>\nstartxref\n447\n%%EOF"
)

raw = RawDocument(
    source_uri="test://battery.pdf",
    file_name="battery.pdf",
    mime_type="application/pdf",
    content=pdf_bytes,
    tenant_id="t",
)

p = UnstructuredParser()
blocks = list(p.parse(raw))
print(f"PDF blocks: {len(blocks)}")
for b in blocks[:5]:
    etype = b.extra.get("element_type", "?")
    print(f"  [{etype}] page={b.page}  text={b.text[:70]!r}")

if blocks:
    print("\nPDF fallback parser: PASS")
else:
    print("\nPDF fallback parser: FAIL — no blocks produced")
    sys.exit(1)
