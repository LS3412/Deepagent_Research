"""Streamlit entry. Run with:  streamlit run app.py"""
# Suppress noisy transformers lazy-loader messages before any lib imports.
import os
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import logging

# Root logging — INFO for our code, WARNING for noisy third-party libs.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("docling").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("weaviate").setLevel(logging.WARNING)
logging.getLogger("watchdog").setLevel(logging.WARNING)

from src.ui.streamlit_app import main

main()
