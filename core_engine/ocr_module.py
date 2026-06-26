"""
ocr_module.py
─────────────
PaddleOCR 封装模块 (Sequential In-Process 版)

设计决策：
  原始方案使用 ProcessPoolExecutor 并发处理图片，但在 Windows spawn 模式下，
  子进程加载深度学习模型（尤其是 GPU 上下文）时极易触发 WaitForMultipleObjects
  死锁，导致程序无限挂起。

  改为单进程顺序执行策略：
  - PaddleOCR 实例在主进程中初始化一次，后续复用。
  - 对单文档而言，IO 瓶颈远大于 OCR 计算，不存在明显并发收益。
  - 完全规避 Windows spawn 死锁、CUDA 多进程共享显存等问题。
  - 若需要并发处理多个文档，应在文档级而非图片级并发（由外部调用方控制）。

容错机制：
  - 单张图片失败时记录日志并返回空结果，不中断整批解析。
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
from PIL import Image

from .image_preprocessor import preprocess_image

logger = logging.getLogger(__name__)


class OCRProcessor:
    """
    PaddleOCR Single-process sequential processor.

    Parameters
    ----------
    use_gpu : bool
        Whether to enable GPU inference (paddlepaddle-gpu required)
    max_workers : int | None
        Reserved parameter (compatibility interface), current implementation is single-process
    use_structure : bool
        Whether to enable PP-Structure for table HTML conversion (reserved interface)
    preprocess : bool
        Whether to perform OpenCV preprocessing before OCR
    """

    def __init__(
        self,
        use_gpu: bool = False,
        max_workers: Optional[int] = None,
        use_structure: bool = False,
        preprocess: bool = True,
    ) -> None:
        self.use_gpu = use_gpu
        self.use_structure = use_structure
        self.preprocess = preprocess
        self._ocr = None   # 延迟初始化，第一次 process_images 时创建

        logger.info(
            "OCRProcessor initialized | use_gpu=%s | mode=sequential",
            self.use_gpu,
        )

    # ------------------------------------------------------------------
    def _get_ocr(self):
        """
        Lazy initialization of PaddleOCR instance.
        Automatically detects parameter differences between version 2.x and 3.x.
        """
        if self._ocr is not None:
            return self._ocr

        from paddleocr import PaddleOCR
        
        # 强制关闭 PaddleOCR 内部的日志器，防止在 Streamlit 线程中写向已关闭的 stdout 导致崩溃
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        logging.getLogger("paddleocr").setLevel(logging.ERROR)

        logger.info("Initializing PaddleOCR engine...")

        # 优先尝试 2.x 参数
        try:
            self._ocr = PaddleOCR(
                use_angle_cls=False,     # 禁用方向分类器（假设文档绝大多数偏正向），可提速 15%-20%
                det_limit_side_len=736,  # 缩小输入分辨率上限（默认960），大幅降低卷积耗时，对普通字体不影响
                use_gpu=self.use_gpu,
                show_log=False,
                lang="ch",
            )
            logger.info("PaddleOCR 2.x parameters initialized successfully")
        except (TypeError, Exception) as e1:
            logger.warning("2.x parameter initialization failed (%s), trying 3.x parameters...", e1)
            try:
                self._ocr = PaddleOCR(
                    use_textline_orientation=False,
                    det_limit_side_len=736,
                    show_log=False,
                    lang="ch",
                )
                logger.info("PaddleOCR 3.x parameters initialized successfully")
            except Exception as e2:
                logger.warning("3.x parameter initialization failed (%s), using minimal parameters...", e2)
                self._ocr = PaddleOCR(show_log=False, lang="ch")
                logger.info("PaddleOCR minimal parameters initialized successfully")

        return self._ocr

    # ------------------------------------------------------------------
    def _to_numpy(self, image: Union[np.ndarray, Image.Image]) -> np.ndarray:
        """统一转为 uint8 numpy array（RGB）。"""
        if isinstance(image, Image.Image):
            return np.array(image.convert("RGB"))
        return image

    # ------------------------------------------------------------------
    def _run_ocr_single(
        self, image: np.ndarray, index: int
    ) -> Dict[str, Any]:
        """
        对单张图片执行 OCR，失败时返回空结果（不抛异常）。

        Returns
        -------
        dict: {index, blocks: [{text, bbox, source, confidence}], table_html, error}
        """
        try:
            ocr = self._get_ocr()
            raw = ocr.ocr(image, cls=True)

            blocks = []
            if raw and raw[0]:
                for line in raw[0]:
                    bbox_points, (text, confidence) = line
                    xs = [p[0] for p in bbox_points]
                    ys = [p[1] for p in bbox_points]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                    blocks.append({
                        "text":       text,
                        "bbox":       bbox,
                        "source":     "ocr",
                        "confidence": round(float(confidence), 4),
                    })

            return {"index": index, "blocks": blocks, "table_html": None, "error": None}

        except Exception as exc:  # noqa: BLE001
            logger.error("Image #%d OCR failed: %s", index, exc, exc_info=False)
            return {"index": index, "blocks": [], "table_html": None, "error": str(exc)}

    # ------------------------------------------------------------------
    def process_images(
        self,
        images: List[Union[np.ndarray, Image.Image]],
        progress_callback: Optional[Callable] = None,
    ) -> List[Dict[str, Any]]:
        """
        Sequentially processes image list, performing preprocessing + OCR on each image.

        Parameters
        ----------
        images : list[np.ndarray | PIL.Image.Image]
            List of images to process
        progress_callback : callable | None
            Callback function, receives (current, total) parameters
        """
        if not images:
            return []

        total = len(images)
        logger.info("OCR starting to process %d images...", total)
        results: List[Dict[str, Any]] = []

        try:
            from tqdm import tqdm
            image_iterator = tqdm(images, desc="OCR Processing", unit="img")
        except ImportError:
            image_iterator = images

        for idx, img in enumerate(image_iterator):
            # ── 预处理 ──────────────────────────────────────────────
            if self.preprocess:
                try:
                    processed = preprocess_image(img)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Image #%d preprocessing failed, skipping: %s", idx, exc)
                    processed = self._to_numpy(img)
            else:
                processed = self._to_numpy(img)

            # ── OCR 推理（含单图容错）──────────────────────────────
            result = self._run_ocr_single(processed, idx)
            results.append(result)

            # ── 进度回调 ────────────────────────────────────────────
            if progress_callback:
                try:
                    progress_callback(idx + 1, total)
                except Exception as e:
                    logger.debug("Progress callback failed: %s", e)

        logger.info(
            "OCR complete | Total images=%d | Success=%d | Failed=%d",
            total,
            sum(1 for r in results if not r["error"]),
            sum(1 for r in results if r["error"]),
        )
        return results
