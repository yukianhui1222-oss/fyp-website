"""
pdf_handler.py
──────────────
PDF 文档处理器，基于 PyMuPDF (fitz)。

核心策略（原生解析 + 局部 OCR）：
  - 尝试直接提取当前页文本（原生 PDF）。
  - 若文本量 < SCAN_TEXT_THRESHOLD 字符 且 页面含图，则判定为扫描版，
    将整页渲染为图片送 OCR。
  - 原生页：保存文本，并将页面内嵌的图片单独送 OCR。
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# 扫描版判定阈值（提取字符数低于此值时启用全页 OCR）
SCAN_TEXT_THRESHOLD: int = 50

# 扫描版渲染 DPI（越高越清晰，但内存消耗越大）
RENDER_DPI: int = 150


class PDFHandler:
    """
    PDF 文档处理器。

    Parameters
    ----------
    ocr_processor : OCRProcessor
        已初始化的 OCR 处理器实例（由 DocumentParser 传入）
    """

    def __init__(self, ocr_processor: Any, fast_mode: bool = False) -> None:
        self.ocr = ocr_processor
        self.fast_mode = fast_mode

    # ------------------------------------------------------------------
    def process(self, file_path: str, progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """
        PDF analysis logic:
        1. Attempt to extract native text and tables.
        2. Extract page images (if any) and process with OCRProcessor, passing progress callback.

        Parameters
        ----------
        file_path : str
            Absolute path to the PDF file
        progress_callback : Optional[callable]
            Progress callback function, accepts (current, total) parameters.

        Returns
        -------
        list[dict]
            [
              {
                "page_num":   int,
                "page_type":  "native" | "scanned",
                "text_blocks": [{text, bbox, source, confidence}],
                "table_html": str | None,
              },
              ...
            ]
        """
        doc = fitz.open(file_path)
        pages_result: List[Dict[str, Any]] = []

        # ── 收集需要 OCR 的页面/图片 ──────────────────────────────────────
        ocr_tasks: List[Dict[str, Any]] = []  # {page_num, task_type, image}
        page_data: List[Dict[str, Any]] = []   # 每页的初步解析结果

        logger.info("PDF has %d pages, starting analysis: %s", len(doc), file_path)

        for page_num, page in enumerate(doc, start=1):
            native_text = page.get_text("text").strip()
            image_list = page.get_images(full=True)
            has_images = len(image_list) > 0

            # ── 判定：扫描版还是原生 PDF ──────────────────────
            is_scanned = (len(native_text) < SCAN_TEXT_THRESHOLD) and has_images

            page_entry: Dict[str, Any] = {
                "page_num": page_num,
                "page_type": "scanned" if is_scanned else "native",
                "native_blocks": [],   # 原生文本块
                "ocr_task_indices": [], # 对应 ocr_tasks 中的索引
            }

            if is_scanned:
                # 整页渲染为图片
                render_dpi = 96 if self.fast_mode else RENDER_DPI
                logger.debug("Page %d: scanned version, sending full page to OCR (DPI: %d)", page_num, render_dpi)
                pix = page.get_pixmap(dpi=render_dpi)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                task_idx = len(ocr_tasks)
                ocr_tasks.append({"page_num": page_num, "task_type": "full_page", "image": img})
                page_entry["ocr_task_indices"].append(task_idx)

            else:
                # 原生 PDF：提取文本块（含坐标）
                logger.debug("Page %d: native PDF, extracting text + embedded images", page_num)
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if block["type"] == 0:  # 文字块
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                text = span.get("text", "").strip()
                                if text:
                                    bbox = list(span["bbox"])  # [x0,y0,x1,y1]
                                    page_entry["native_blocks"].append(
                                        {
                                            "text": text,
                                            "bbox": bbox,
                                            "source": "native",
                                            "confidence": 1.0,
                                        }
                                    )

                # 提取页面内嵌图片送 OCR
                for img_info in image_list:
                    xref = img_info[0]
                    try:
                        base_img = doc.extract_image(xref)
                        img_bytes = base_img["image"]
                        img = Image.open(__import__("io").BytesIO(img_bytes)).convert("RGB")
                        
                        # 性能优化: 过滤无用的微小装饰图片 (宽或高 < 100像素) 跳过 OCR
                        if img.width < 100 or img.height < 100:
                            logger.debug("Skipping tiny decorative image on page %d (size: %dx%d)", page_num, img.width, img.height)
                            continue
                            
                        # 性能优化: 极速模式下, 原生 PDF 直接跳过所有内嵌图片 OCR 分析
                        if self.fast_mode:
                            logger.debug("Fast mode enabled: skipping embedded image OCR entirely on page %d", page_num)
                            continue
                            
                        task_idx = len(ocr_tasks)
                        ocr_tasks.append(
                            {"page_num": page_num, "task_type": "embedded_image", "image": img}
                        )
                        page_entry["ocr_task_indices"].append(task_idx)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to extract embedded image on page %d (xref=%d): %s", page_num, xref, exc)

            page_data.append(page_entry)

        doc.close()

        # ── 并发 OCR ──────────────────────────────────────────────────────
        ocr_images = [t["image"] for t in ocr_tasks]
        ocr_results = self.ocr.process_images(ocr_images, progress_callback=progress_callback) if ocr_images else []

        # 构建 OCR 结果索引映射
        ocr_result_map: Dict[int, Dict] = {r["index"]: r for r in ocr_results}

        # ── 组装最终结果 ──────────────────────────────────────────────────
        for entry in page_data:
            all_blocks = list(entry["native_blocks"])

            for task_idx in entry["ocr_task_indices"]:
                ocr_res = ocr_result_map.get(task_idx)
                if ocr_res:
                    all_blocks.extend(ocr_res["blocks"])
                    if ocr_res.get("error"):
                        logger.warning(
                            "Page %d OCR task #%d failed: %s",
                            entry["page_num"], task_idx, ocr_res["error"]
                        )

            pages_result.append(
                {
                    "page_num": entry["page_num"],
                    "page_type": entry["page_type"],
                    "text_blocks": all_blocks,
                    "table_html": None,
                }
            )

        logger.info("PDF analysis complete, total pages: %d", len(pages_result))
        return pages_result
