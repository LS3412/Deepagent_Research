"""
indexer/build_real_catalog.py  (v2)
------------------------------------------------------
Three production-grade capabilities added to ingestion:

1. IDEMPOTENCY
   Every product_id maps to a deterministic UUID via uuid5(namespace, product_id).
   Pre-fetches existing UUIDs+content-hashes from Weaviate each run.
   Classifies each record as NEW (insert) / CHANGED (upsert) / DUPLICATE (skip).
   Running N times on the same file produces zero duplicates.

2. SCHEMA EVOLUTION  (indexer/schema_registry.json)
   Versioned JSON registry declares every field: type, default, version_added.
   On ingestion:
     missing fields -> filled from registry defaults (downstream never crashes)
     unknown fields -> auto-registered as TEXT + logged as schema drift
   Registry saved back to disk after every run.
   --rebuild flag recreates Weaviate collection when schema changes.

3. MONITORING & OBSERVABILITY
   Every run appends one JSON line to metrics/ingestion_runs.jsonl:
     run_id, started_at, finished_at, total_duration_s
     inserted, updated, skipped_duplicate, skipped_sparse, errors
     throughput_rps, avg_embed_ms, avg_insert_ms
     min_lag_ms, max_lag_ms, avg_lag_ms   (source-read -> DB-commit per record)

Usage:
    python indexer/build_real_catalog.py            # incremental (idempotent)
    python indexer/build_real_catalog.py --rebuild  # drop + recreate collection
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import re
import sys
import time
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import weaviate
import weaviate.classes as wvc
from weaviate.classes.config import Configure, DataType, Property

# ---------- Constants ---------------------------------------------------------
EMBED_MODEL    = "bge-m3"
EMBED_FALLBACK = "nomic-embed-text"
BATCH_SIZE     = 50
COLLECTION     = "RealProductCatalog"
SCHEMA_FILE    = Path(__file__).parent / "schema_registry.json"
METRICS_DIR    = ROOT / "metrics"

# Fixed UUID namespace -- NEVER change after first run.
# Changing it would give all existing products different Weaviate UUIDs,
# breaking idempotency and creating duplicates.
_UUID_NS = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
_SPARSE_THRESHOLD = 3   # min non-null fields before a record is indexable


# =============================================================================
# FEATURE 1 -- IDEMPOTENCY
# =============================================================================

def _product_uuid(product_id: str) -> str:
    """Deterministic Weaviate UUID for a product_id.
    uuid5 is a pure function: same input always -> same UUID.
    """
    return str(_uuid.uuid5(_UUID_NS, f"{COLLECTION}:{product_id}"))


def _content_hash(record: dict) -> str:
    """16-char SHA256 fingerprint of a sanitised record (excl. content_hash itself).
    Used to detect whether a record changed since the last ingestion run.
    """
    stable = {k: v for k, v in sorted(record.items()) if k != "content_hash"}
    raw = json.dumps(stable, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _fetch_existing(coll) -> dict[str, dict]:
    """Return {product_id: {uuid, content_hash}} for every object in Weaviate.
    Uses cursor-based pagination -- works for any collection size.
    """
    result: dict[str, dict] = {}
    after_uuid = None
    while True:
        resp = coll.query.fetch_objects(
            limit=200,
            after=after_uuid,
            return_properties=["product_id", "content_hash"],
        )
        if not resp.objects:
            break
        for obj in resp.objects:
            pid = obj.properties.get("product_id", "")
            if pid:
                result[pid] = {
                    "uuid":         str(obj.uuid),
                    "content_hash": obj.properties.get("content_hash", ""),
                }
        after_uuid = resp.objects[-1].uuid
        if len(resp.objects) < 200:
            break
    return result


# =============================================================================
# FEATURE 2 -- SCHEMA REGISTRY
# =============================================================================

def _load_registry() -> dict:
    if SCHEMA_FILE.exists():
        with SCHEMA_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    return {"schema_version": 0, "collection": COLLECTION,
            "fields": {}, "changelog": [], "discovered_fields": []}


def _save_registry(registry: dict) -> None:
    registry["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    with SCHEMA_FILE.open("w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    print(f"  [registry] Saved -> {SCHEMA_FILE.name}")


def _check_schema_drift(record: dict, registry: dict) -> list[str]:
    """Return field names in record that are not declared in the registry."""
    known = set(registry.get("fields", {}).keys())
    return [k for k in record if k not in known]


def _auto_register_fields(new_fields: list[str], registry: dict) -> None:
    """Add undeclared fields to registry as auto-discovered TEXT fields.
    Downstream pipelines that read the registry will see the new field
    and use the TEXT default -- they never crash on unknown columns.
    """
    added = []
    current_version = registry.get("schema_version", 1)
    for fname in new_fields:
        if fname not in registry["fields"]:
            registry["fields"][fname] = {
                "weaviate_type":   "TEXT",
                "required":        False,
                "default":         "",
                "version_added":   current_version,
                "auto_discovered": True,
            }
            registry.setdefault("discovered_fields", [])
            if fname not in registry["discovered_fields"]:
                registry["discovered_fields"].append(fname)
            added.append(fname)
    if added:
        print(f"  [SCHEMA DRIFT] New fields auto-registered: {added}")


def _apply_defaults(record: dict, registry: dict) -> dict:
    """Fill missing/null fields using registry defaults.
    Guarantees downstream code never receives None for a declared field.
    """
    for fname, cfg in registry.get("fields", {}).items():
        if fname not in record or record.get(fname) is None:
            record[fname] = cfg.get("default", "")
    return record


# =============================================================================
# FEATURE 3 -- MONITORING & OBSERVABILITY
# =============================================================================

@dataclass
class RunMetrics:
    run_id:            str   = field(default_factory=lambda: str(_uuid.uuid4()))
    started_at:        str   = ""
    finished_at:       str   = ""
    total_duration_s:  float = 0.0
    schema_version:    int   = 0
    records_read:      int   = 0
    records_valid:     int   = 0
    inserted:          int   = 0
    updated:           int   = 0
    skipped_duplicate: int   = 0
    skipped_sparse:    int   = 0
    errors:            int   = 0
    throughput_rps:    float = 0.0
    avg_embed_ms:      float = 0.0
    avg_insert_ms:     float = 0.0
    # Lag = time from source file read to DB commit for each record
    min_lag_ms:        float = 0.0
    max_lag_ms:        float = 0.0
    avg_lag_ms:        float = 0.0


def _save_metrics(m: RunMetrics) -> None:
    """Append one JSON line per run to metrics/ingestion_runs.jsonl."""
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    path = METRICS_DIR / "ingestion_runs.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(m)) + "\n")
    print(f"  [metrics]  Appended -> metrics/ingestion_runs.jsonl")


def _print_summary(m: RunMetrics) -> None:
    print("\n" + "=" * 64)
    print("  RUN SUMMARY")
    print("=" * 64)
    print(f"  Run ID          : {m.run_id[:8]}...")
    print(f"  Schema version  : v{m.schema_version}")
    print(f"  Records read    : {m.records_read}")
    print(f"  +-- Inserted    : {m.inserted:4d}  (new records)")
    print(f"  +-- Updated     : {m.updated:4d}  (changed, upserted)")
    print(f"  +-- Skipped     : {m.skipped_duplicate:4d}  (unchanged duplicate)")
    print(f"  +-- Too sparse  : {m.skipped_sparse:4d}  (< {_SPARSE_THRESHOLD} non-null fields)")
    print(f"  +-- Errors      : {m.errors:4d}")
    print(f"  Throughput      : {m.throughput_rps:.1f} records/s")
    print(f"  Avg embed       : {m.avg_embed_ms:.0f} ms/record")
    print(f"  Avg insert      : {m.avg_insert_ms:.0f} ms/record")
    print(f"  Lag (read->DB)  : avg {m.avg_lag_ms:.0f} ms  [min {m.min_lag_ms:.0f} / max {m.max_lag_ms:.0f}]")
    print(f"  Total duration  : {m.total_duration_s:.1f} s")
    print("=" * 64)


# =============================================================================
# EMBEDDING
# =============================================================================

def _embed(text: str) -> list[float]:
    import ollama
    for model in (EMBED_MODEL, EMBED_FALLBACK):
        try:
            return ollama.embed(model=model, input=text).embeddings[0]
        except Exception:
            continue
    raise RuntimeError(f"Embedding failed for both {EMBED_MODEL} and {EMBED_FALLBACK}")


# =============================================================================
# NULL / NaN HELPERS
# =============================================================================

def _is_missing(v: Any) -> bool:
    if v is None: return True
    if isinstance(v, float) and math.isnan(v): return True
    if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "nan", "n/a", "unknown"): return True
    return False

def _safe_str(v: Any, fallback: str = "") -> str:
    return fallback if _is_missing(v) else str(v).strip()

def _safe_float(v: Any, fallback: float = 0.0) -> float:
    if _is_missing(v): return fallback
    try: return float(v)
    except (TypeError, ValueError): return fallback

def _safe_int(v: Any, fallback: int = 0) -> int:
    if _is_missing(v): return fallback
    try: return int(float(v))
    except (TypeError, ValueError): return fallback

def _safe_bool(v: Any, fallback: bool = False) -> bool:
    if _is_missing(v): return fallback
    if isinstance(v, bool): return v
    return str(v).lower() in ("true", "1", "yes")


# =============================================================================
# RECORD SANITISATION
# =============================================================================

def _count_non_null(raw: dict) -> int:
    return sum(1 for v in raw.values() if not _is_missing(v))


def _sanitise(raw: dict) -> dict | None:
    pid = raw.get("product_id")
    if _is_missing(pid): return None
    pid = str(pid).strip()
    non_null = _count_non_null(raw)
    if non_null < _SPARSE_THRESHOLD:
        print(f"  [SKIP] {pid}: only {non_null} non-null fields")
        return None

    name           = _safe_str(raw.get("name"),              "")
    category       = _safe_str(raw.get("category"),          "Uncategorized")
    brand          = _safe_str(raw.get("brand"),             "Unknown Brand")
    description    = _safe_str(raw.get("description"),       "")
    short_desc     = _safe_str(raw.get("short_desc"),        "")
    tags           = _safe_str(raw.get("tags"),              "")
    supplier_id    = _safe_str(raw.get("supplier_id"),       "Unknown")
    supplier_name  = _safe_str(raw.get("supplier_name"),     "Unknown Supplier")
    sku            = _safe_str(raw.get("sku"),               "")
    color          = _safe_str(raw.get("color"),             "")
    dimensions     = _safe_str(raw.get("dimensions_cm"),     "")
    certifications = _safe_str(raw.get("certifications"),    "")
    country        = _safe_str(raw.get("country_of_origin"), "")
    unit_price     = _safe_float(raw.get("unit_price"))
    sale_price     = _safe_float(raw.get("sale_price"))
    weight_kg      = _safe_float(raw.get("weight_kg"))
    rating         = _safe_float(raw.get("rating"))
    stock_qty      = _safe_int(raw.get("stock_qty"))
    reorder_point  = _safe_int(raw.get("reorder_point"))
    review_count   = _safe_int(raw.get("review_count"))
    warranty_years = _safe_int(raw.get("warranty_years"))
    release_year   = _safe_int(raw.get("release_year"))
    in_stock       = _safe_bool(raw.get("in_stock"), fallback=stock_qty > 0)
    discontinued   = _safe_bool(raw.get("discontinued"), False)
    completeness   = round(non_null / len(raw), 2) if raw else 0.0

    if not description and not short_desc:
        parts = []
        if name: parts.append(name)
        if brand != "Unknown Brand": parts.append(f"by {brand}")
        if category != "Uncategorized": parts.append(f"in {category}")
        if unit_price: parts.append(f"priced at ${unit_price:.2f}")
        description = " ".join(parts) if parts else pid
        print(f"  [SYNTH] {pid}: description synthesised")

    return {
        "product_id": pid, "sku": sku, "name": name, "category": category,
        "brand": brand, "unit_price": unit_price, "sale_price": sale_price,
        "weight_kg": weight_kg, "stock_qty": stock_qty, "supplier_id": supplier_id,
        "supplier_name": supplier_name, "reorder_point": reorder_point,
        "rating": rating, "review_count": review_count,
        "description": description or short_desc,
        "tags": tags, "color": color, "dimensions_cm": dimensions,
        "warranty_years": warranty_years, "release_year": release_year,
        "in_stock": in_stock, "discontinued": discontinued,
        "country_of_origin": country, "certifications": certifications,
        "completeness": completeness,
    }


# =============================================================================
# SPEC EXTRACTION & EMBED TEXT
# =============================================================================

_SPEC_PATTERNS: list[tuple[str, str]] = [
    (r"(\d+)\s*GB\s*RAM",                      "RAM: {}GB."),
    (r"(\d+)\s*GB\s*(?:unified\s*)?memory",    "Memory: {}GB."),
    (r"(\d+)\s*TB\s*SSD",                      "Storage: {}TB SSD."),
    (r"(\d+)\s*GB\s*SSD",                      "Storage: {}GB SSD."),
    (r"(\d+)\s*TB\s*(?:storage|HDD|portable)", "Storage: {}TB."),
    (r"(\d+)\s*Hz",                             "Refresh: {}Hz."),
    (r"(\d+)\s*MP",                             "Camera: {}MP."),
    (r"RTX\s*(\d+\s*\w*)",                     "GPU: NVIDIA RTX {}."),
    (r"GTX\s*(\d+\s*\w*)",                     "GPU: NVIDIA GTX {}."),
    (r"Core\s*(i\d+)",                          "CPU: Intel Core {}."),
    (r"Ryzen\s*(\d+)",                          "CPU: AMD Ryzen {}."),
    (r"Snapdragon\s*(\w+)",                     "Chip: Snapdragon {}."),
    (r"(M[1-9]\s*(?:Pro|Max|Ultra)?)\s*chip",  "Chip: Apple {}."),
    (r"(\d+)\s*-?\s*hour\s*battery",            "Battery: {}h."),
    (r"(\d+)\s*mAh",                            "Battery: {}mAh."),
    (r"(\d+)\s*W\s*(?:charging|charger|PD|GaN)", "Charging: {}W."),
    (r"(\d+)\s*DPI",                             "DPI: {}."),
    (r"DDR(\d)",                                 "RAM type: DDR{}."),
    (r"(\d+)\s*MHz",                             "Speed: {}MHz."),
    (r"USB[-\s]?C",                              "Connectivity: USB-C."),
    (r"Thunderbolt\s*(\d+)",                     "Connectivity: Thunderbolt {}."),
    (r"WiFi\s*(\d+)",                            "WiFi: {}."),
    (r"5G",                                      "Connectivity: 5G."),
    (r"Bluetooth\s*(\d+(?:\.\d+)?)",             "Bluetooth: {}."),
]


def _extract_specs(text: str) -> list[str]:
    found, seen = [], set()
    for pattern, template in _SPEC_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            groups = m.groups()
            tag = template.format(*groups) if groups else template
            if tag not in seen:
                found.append(tag); seen.add(tag)
    return found


def _build_embed_text(r: dict) -> str:
    parts: list[str] = []
    if r["name"]: parts.append(f"Product: {r['name']}.")
    if r["brand"] and r["brand"] != "Unknown Brand": parts.append(f"Brand: {r['brand']}.")
    if r["category"] and r["category"] != "Uncategorized": parts.append(f"Category: {r['category']}.")
    if r["unit_price"]: parts.append(f"Price: ${r['unit_price']:.2f}.")
    if r["sale_price"]: parts.append(f"Sale: ${r['sale_price']:.2f}.")
    if r["rating"]: parts.append(f"Rating: {r['rating']}/5.")
    if not r["in_stock"]: parts.append("Out of stock.")
    if r["discontinued"]: parts.append("Discontinued product.")
    if r["tags"]: parts.append(f"Keywords: {r['tags'].replace(',', ' ')}.")
    if r["description"]:
        parts.append(r["description"])
        specs = _extract_specs(r["description"] + " " + r.get("tags", ""))
        if specs: parts.append(" ".join(specs))
    if r["certifications"]: parts.append(f"Certifications: {r['certifications']}.")
    if r["country_of_origin"]: parts.append(f"Made in: {r['country_of_origin']}.")
    if r["warranty_years"]: parts.append(f"Warranty: {r['warranty_years']} year(s).")
    return " ".join(parts) if parts else r["product_id"]


def _build_product_metadata(r: dict) -> str:
    """Pre-compute a compact structured metadata string for fast agent/LLM reading.

    Problem: A product description can be 200-500 words. Reading it per-query
    wastes time. Solution: build this once at ingestion and store it alongside
    the product. Agents read the metadata (1-2 lines) instead of the full
    description, cutting per-query processing time significantly.

    Example output:
      "Category:Laptops | Brand:HP | Price:$1899.99 | Rating:4.5/5(312) |
       Stock:In-Stock | Qty:45 | Specs:[GPU: NVIDIA RTX 4080; RAM: 16GB] |
       Tags:gaming,professional | Warranty:2yr | Year:2023"
    """
    parts = []

    # Identity
    if r.get("category") and r["category"] != "Uncategorized":
        parts.append(f"Category:{r['category']}")
    if r.get("brand") and r["brand"] != "Unknown Brand":
        parts.append(f"Brand:{r['brand']}")

    # Pricing
    if r.get("unit_price"):
        parts.append(f"Price:${r['unit_price']:.2f}")
    if r.get("sale_price") and r["sale_price"] and r["sale_price"] != r.get("unit_price"):
        parts.append(f"Sale:${r['sale_price']:.2f}")

    # Quality
    if r.get("rating"):
        rev = f"({int(r['review_count'])})" if r.get("review_count") else ""
        parts.append(f"Rating:{r['rating']}/5{rev}")

    # Availability
    stock_label = (
        "Discontinued" if r.get("discontinued")
        else ("In-Stock" if r.get("in_stock") else "Out-of-Stock")
    )
    parts.append(f"Stock:{stock_label}")
    if r.get("stock_qty"):
        parts.append(f"Qty:{r['stock_qty']}")

    # Extracted specs (hardware keywords from description + tags)
    desc_text = (r.get("description") or "") + " " + (r.get("tags") or "")
    specs = _extract_specs(desc_text)
    if specs:
        specs_str = "; ".join(s.rstrip(".") for s in specs[:8])
        parts.append(f"Specs:[{specs_str}]")

    # Tags (truncated)
    if r.get("tags"):
        parts.append(f"Tags:{r['tags'][:80]}")

    # Additional attributes
    if r.get("warranty_years"):
        parts.append(f"Warranty:{r['warranty_years']}yr")
    if r.get("release_year"):
        parts.append(f"Year:{r['release_year']}")
    if r.get("weight_kg"):
        parts.append(f"Weight:{r['weight_kg']}kg")

    return " | ".join(parts)


# =============================================================================
# WEAVIATE COLLECTION SETUP
# =============================================================================

def _create_collection(client: weaviate.WeaviateClient, rebuild: bool = False) -> None:
    existing_raw = client.collections.list_all()
    existing = (
        set(existing_raw.keys()) if isinstance(existing_raw, dict)
        else {c if isinstance(c, str) else c.name for c in existing_raw}
    )
    if COLLECTION in existing:
        if rebuild:
            client.collections.delete(COLLECTION)
            print(f"  [cleared] {COLLECTION}  (--rebuild)")
        else:
            print(f"  [exists]  {COLLECTION}  -- keeping. Use --rebuild to reset.")
            return
    client.collections.create(
        name=COLLECTION,
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(name="product_id",        data_type=DataType.TEXT),
            Property(name="content_hash",      data_type=DataType.TEXT),
            Property(name="sku",               data_type=DataType.TEXT),
            Property(name="name",              data_type=DataType.TEXT),
            Property(name="category",          data_type=DataType.TEXT,
                     tokenization=wvc.config.Tokenization.FIELD),
            Property(name="brand",             data_type=DataType.TEXT,
                     tokenization=wvc.config.Tokenization.FIELD),
            Property(name="unit_price",        data_type=DataType.NUMBER),
            Property(name="sale_price",        data_type=DataType.NUMBER),
            Property(name="weight_kg",         data_type=DataType.NUMBER),
            Property(name="stock_qty",         data_type=DataType.INT),
            Property(name="supplier_id",       data_type=DataType.TEXT),
            Property(name="supplier_name",     data_type=DataType.TEXT),
            Property(name="reorder_point",     data_type=DataType.INT),
            Property(name="rating",            data_type=DataType.NUMBER),
            Property(name="review_count",      data_type=DataType.INT),
            Property(name="description",       data_type=DataType.TEXT),
            Property(name="tags",              data_type=DataType.TEXT),
            Property(name="color",             data_type=DataType.TEXT),
            Property(name="dimensions_cm",     data_type=DataType.TEXT),
            Property(name="warranty_years",    data_type=DataType.INT),
            Property(name="release_year",      data_type=DataType.INT),
            Property(name="in_stock",          data_type=DataType.BOOL),
            Property(name="discontinued",      data_type=DataType.BOOL),
            Property(name="country_of_origin", data_type=DataType.TEXT),
            Property(name="certifications",    data_type=DataType.TEXT),
            Property(name="completeness",      data_type=DataType.NUMBER),
            Property(name="search_metadata",   data_type=DataType.TEXT),
        ],
    )
    print(f"  [created] {COLLECTION}")


# =============================================================================
# MAIN INGESTION
# =============================================================================

def _ingest(
    client: weaviate.WeaviateClient,
    jsonl_path: Path,
    registry: dict,
    rebuild: bool,
) -> RunMetrics:
    metrics = RunMetrics(
        started_at=datetime.datetime.now().isoformat(timespec="seconds"),
        schema_version=registry.get("schema_version", 1),
    )
    t_run = time.monotonic()
    coll  = client.collections.get(COLLECTION)

    # Pre-fetch for idempotency
    print("  Pre-fetching existing records ...")
    existing = {} if rebuild else _fetch_existing(coll)
    print(f"  Existing in Weaviate: {len(existing)} records\n")

    to_insert: list[tuple[dict, str, float]] = []
    to_upsert: list[tuple[dict, str, float]] = []
    embed_times: list[float] = []
    lag_times:   list[float] = []
    batch_ms    = 0.0

    # -- Pass 1: Parse / sanitise / classify ----------------------------------
    with jsonl_path.open(encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            raw_line = raw_line.strip()
            if not raw_line: continue
            t_read = time.monotonic()
            metrics.records_read += 1
            try:
                raw = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                print(f"  [SKIP] line {line_no}: invalid JSON -- {exc}")
                metrics.errors += 1; continue

            new_fields = _check_schema_drift(raw, registry)
            if new_fields:
                _auto_register_fields(new_fields, registry)

            record = _sanitise(raw)
            if record is None:
                metrics.skipped_sparse += 1; continue
            metrics.records_valid += 1

            record = _apply_defaults(record, registry)
            record["search_metadata"] = _build_product_metadata(record)  # pre-computed for fast agent reads
            record["content_hash"] = _content_hash(record)
            obj_uuid = _product_uuid(record["product_id"])
            pid      = record["product_id"]

            if pid in existing:
                if existing[pid]["content_hash"] == record["content_hash"]:
                    metrics.skipped_duplicate += 1
                    print(f"  [SKIP dup] {pid}  hash={record['content_hash']}")
                else:
                    to_upsert.append((record, obj_uuid, t_read))
            else:
                to_insert.append((record, obj_uuid, t_read))

    print(
        f"\n  Classified: {len(to_insert)} new | {len(to_upsert)} changed | "
        f"{metrics.skipped_duplicate} unchanged | {metrics.skipped_sparse} sparse\n"
    )

    # -- Pass 2: Embed + batch-insert new records ------------------------------
    if to_insert:
        print(f"  Embedding {len(to_insert)} new records ...")
        embedded_new = []
        for record, obj_uuid, t_read in to_insert:
            t0 = time.monotonic()
            vector = _embed(_build_embed_text(record))
            embed_times.append((time.monotonic() - t0) * 1000)
            embedded_new.append((record, vector, obj_uuid, t_read))

        print(f"  Batch-inserting (batch_size={BATCH_SIZE}) ...")
        t_batch = time.monotonic()
        with coll.batch.fixed_size(batch_size=BATCH_SIZE) as batch:
            for record, vector, obj_uuid, t_read in embedded_new:
                batch.add_object(properties=record, vector=vector, uuid=obj_uuid)
                lag_ms = (time.monotonic() - t_read) * 1000
                lag_times.append(lag_ms)
                stock = "ok" if record["in_stock"] else "OOS"
                disc  = " DISC" if record["discontinued"] else ""
                print(
                    f"  [INSERT] {record['product_id']:6s}  "
                    f"{record['name'][:42]:42s}  "
                    f"{stock}  lag={lag_ms:.0f}ms  q={record['completeness']:.0%}{disc}"
                )
        batch_ms = (time.monotonic() - t_batch) * 1000
        failed = coll.batch.failed_objects
        metrics.inserted = len(to_insert) - len(failed)
        metrics.errors  += len(failed)
        if failed:
            print(f"\n  [BATCH ERRORS] {len(failed)} failed:")
            for err in failed: print(f"    {err}")

    # -- Pass 3: Embed + upsert changed records --------------------------------
    if to_upsert:
        print(f"\n  Upserting {len(to_upsert)} changed records ...")
        for record, obj_uuid, t_read in to_upsert:
            t0 = time.monotonic()
            vector = _embed(_build_embed_text(record))
            embed_times.append((time.monotonic() - t0) * 1000)
            try:
                coll.data.replace(uuid=obj_uuid, properties=record, vector=vector)
                lag_ms = (time.monotonic() - t_read) * 1000
                lag_times.append(lag_ms)
                metrics.updated += 1
                print(
                    f"  [UPSERT] {record['product_id']:6s}  "
                    f"{record['name'][:42]:42s}  lag={lag_ms:.0f}ms"
                )
            except Exception as exc:
                metrics.errors += 1
                print(f"  [ERROR ] {record['product_id']}: {exc}")

    # -- Finalise metrics ------------------------------------------------------
    total_s   = time.monotonic() - t_run
    processed = metrics.inserted + metrics.updated
    metrics.finished_at      = datetime.datetime.now().isoformat(timespec="seconds")
    metrics.total_duration_s = round(total_s, 2)
    metrics.throughput_rps   = round(processed / total_s, 2) if total_s > 0 else 0.0
    metrics.avg_embed_ms     = round(sum(embed_times) / len(embed_times), 1) if embed_times else 0.0
    metrics.avg_insert_ms    = round(batch_ms / max(len(to_insert), 1), 1) if to_insert else 0.0
    if lag_times:
        metrics.min_lag_ms = round(min(lag_times), 1)
        metrics.max_lag_ms = round(max(lag_times), 1)
        metrics.avg_lag_ms = round(sum(lag_times) / len(lag_times), 1)
    return metrics


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest real_products.jsonl into Weaviate")
    parser.add_argument("--rebuild", action="store_true",
                        help="Delete and recreate collection. Use after schema changes.")
    args = parser.parse_args()

    print("=" * 65)
    print("REAL CATALOG INGESTION  v2")
    print("Features: idempotency | schema evolution | observability")
    print("=" * 65)

    jsonl_path = ROOT / "data" / "real_products.jsonl"
    if not jsonl_path.exists():
        print(f"ERROR: {jsonl_path} not found."); sys.exit(1)

    print("\n[0/4] Loading schema registry ...")
    registry = _load_registry()
    print(f"      v{registry.get('schema_version', '?')} | {len(registry.get('fields', {}))} fields declared")

    print("\n[1/4] Connecting to Weaviate ...")
    try:
        client = weaviate.connect_to_local(port=8080, grpc_port=50051)
        print("      Connected.")
    except Exception as exc:
        print(f"      ERROR: {exc}"); sys.exit(1)

    print(f"\n[2/4] Collection setup (rebuild={args.rebuild}) ...")
    _create_collection(client, rebuild=args.rebuild)

    print(f"\n[3/4] Ingesting {jsonl_path.name} ...\n")
    metrics = _ingest(client, jsonl_path, registry, rebuild=args.rebuild)
    client.close()

    print("\n[4/4] Persisting metrics & registry ...")
    _save_metrics(metrics)
    _save_registry(registry)
    _print_summary(metrics)
    print("\n  Done.")


if __name__ == "__main__":
    main()
