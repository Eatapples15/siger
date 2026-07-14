"""Avvio robusto del browser Chromium per Playwright, condiviso da siger_scraper.py
(automazione portale) e siger_report.py (rendering PDF).

'pip install playwright' installa solo la libreria Python, non i binari del browser: su
Streamlit Community Cloud (che non esegue 'playwright install' in automatico) il lancio
altrimenti fallisce con 'Executable doesn't exist'. Qui si prova, in ordine: il Chromium di
sistema installato via apt (packages.txt), poi quello gestito da Playwright se già presente,
e solo come ultima risorsa si scarica al volo (lento, ~1-2 minuti, solo la prima volta).
"""
import subprocess
import sys

from playwright.sync_api import Error as PlaywrightError


def lancia_chromium(p, **kwargs):
    try:
        return p.chromium.launch(headless=True, channel="chromium", **kwargs)
    except PlaywrightError:
        pass
    try:
        return p.chromium.launch(headless=True, **kwargs)
    except PlaywrightError:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return p.chromium.launch(headless=True, **kwargs)
