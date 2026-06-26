"""
parser_main.py
──────────────
DocumentParser — 核心引擎统一入口。

职责：
  1. 校验文件路径是否存在。
  2. 根据文件扩展名路由到对应的 Handler。
  3. 汇总各 Handler 返回的页面列表，组装为标准化 JSON 结构。
  4. （可选）将结果持久化到 result_output.json。

支持格式：.pdf | .docx | .doc | .pptx | .ppt
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .handlers.pdf_handler import PDFHandler
from .handlers.ppt_handler import PPTHandler
from .handlers.word_handler import WordHandler
from .ocr_module import OCRProcessor

# ── 日志配置 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 扩展名 → Handler 映射 ────────────────────────────────────────────────────
_FORMAT_MAP: Dict[str, str] = {
    ".pdf":  "pdf",
    ".docx": "word",
    ".doc":  "word",
    ".pptx": "ppt",
    ".ppt":  "ppt",
}


class DocumentParser:
    """
    Core entry point for document analysis engine.

    Parameters
    ----------
    use_gpu : bool
        Whether to let PaddleOCR use GPU inference (default False, i.e., CPU mode)
    max_workers : int | None
        Number of concurrent OCR processes. If None, automatically set to cpu_count - 1
    preprocess : bool
        Whether to perform OpenCV image preprocessing before OCR (default True)

    Example
    -------
    >>> parser = DocumentParser(use_gpu=False)
    >>> result = parser.process_file(r"C:\\path\\to\\file.pdf")
    >>> print(result["metadata"]["total_pages"])
    """

    def __init__(
        self,
        use_gpu: bool = False,
        max_workers: Optional[int] = None,
        preprocess: bool = True,
        fast_mode: bool = False,
    ) -> None:
        self.use_gpu = use_gpu
        self.fast_mode = fast_mode

        # 初始化共享的 OCR 处理器（各 Handler 均使用同一实例）
        self.ocr_processor = OCRProcessor(
            use_gpu=use_gpu,
            max_workers=max_workers,
            preprocess=preprocess,
        )

        # 初始化各 Handler
        self._handlers = {
            "pdf":  PDFHandler(self.ocr_processor, fast_mode=self.fast_mode),
            "word": WordHandler(self.ocr_processor),
            "ppt":  PPTHandler(self.ocr_processor),
        }

        logger.info(
            "DocumentParser initialized | use_gpu=%s | max_workers=%s",
            use_gpu, max_workers or "auto",
        )

    # ─────────────────────────────────────────────────────────────────────────
    def process_file(
        self,
        file_path: str,
        output_json_path: Optional[str] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Parses a single document file.

        Parameters
        ----------
        file_path : str
            Absolute path to the file (supports .pdf / .docx / .doc / .pptx / .ppt)
        output_json_path : str | None
            If provided, writes the result to this JSON file path

        Returns
        -------
        dict
            Standardized structure:
            {
              "metadata": {file_name, file_type, total_pages,
                           processing_time_sec, ocr_engine, use_gpu},
              "pages":    [{page_num, page_type, text_blocks, table_html}]
            }

        Raises
        ------
        FileNotFoundError
            File path does not exist
        ValueError
            Unsupported file format
        """
        # ── 1. 基础校验 ───────────────────────────────────────────────────────
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        ext = path.suffix.lower()
        format_key = _FORMAT_MAP.get(ext)
        if not format_key:
            raise ValueError(
                f"Unsupported file format: '{ext}'. "
                f"Currently supported: {', '.join(_FORMAT_MAP.keys())}"
            )

        logger.info("Starting to process file: %s (format: %s)", file_path, format_key)
        start_time = time.perf_counter()

        # ── 2. 路由到对应 Handler ──────────────────────────────────────────────
        handler = self._handlers[format_key]
        pages = handler.process(file_path, progress_callback=progress_callback)

        # ── 3. 组装标准化输出 ─────────────────────────────────────────────────
        elapsed = round(time.perf_counter() - start_time, 3)

        result: Dict[str, Any] = {
            "metadata": {
                "file_name":          path.name,
                "file_path":          str(path.resolve()),
                "file_type":          format_key,
                "total_pages":        len(pages),
                "processing_time_sec": elapsed,
                "ocr_engine":         "PaddleOCR",
                "use_gpu":            self.use_gpu,
            },
            "pages": pages,
        }

        logger.info(
            "Analysis complete | File: %s | Pages: %d | Time: %.3f sec",
            path.name, len(pages), elapsed,
        )

        # ── 4. 可选：写入 JSON 文件 ────────────────────────────────────────────
        if output_json_path:
            self._save_json(result, output_json_path)

        return result

    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _save_json(data: Dict[str, Any], output_path: str) -> None:
        """Writes analysis result to a JSON file (automatically creates parent directories)."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info("Result written to: %s", out)
        except OSError as exc:
            logger.error("Failed to write JSON file: %s", exc)
            raise
