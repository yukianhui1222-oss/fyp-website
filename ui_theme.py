"""Shared styles, including role-based result tabs across Streamlit versions."""
from pathlib import Path


def load_theme():
    return '<style>' + Path(__file__).with_name('ui_theme.css').read_text(encoding='utf-8') + '</style>'
