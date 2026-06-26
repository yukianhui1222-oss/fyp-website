"""
handlers — 各文档格式的专用处理器
"""

from .pdf_handler import PDFHandler
from .word_handler import WordHandler
from .ppt_handler import PPTHandler

__all__ = ["PDFHandler", "WordHandler", "PPTHandler"]
