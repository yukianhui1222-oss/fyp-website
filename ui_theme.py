"""Presentation-only styles shared by the DocuMind Streamlit views."""
from pathlib import Path


def load_theme():
    return '<style>' + Path(__file__).with_name('ui_theme.css').read_text(encoding='utf-8') + '</style>'
