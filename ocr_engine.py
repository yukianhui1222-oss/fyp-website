"""
ocr_engine.py
─────────────
Streamlit Adapter Layer

Responsibilities:
  - Exposes extract_text_from_image(file_obj, fast_mode) interface,
    keeping calling convention with app.py identical.
  - Internally writes Streamlit UploadedFile (byte stream) to a temporary file,
    routes to core_engine.DocumentParser (document formats) or
    core_engine.ocr_module.OCRProcessor (pure image formats).
  - Converts structured JSON results to human-readable plain text for LLM use.

Supported Formats:
  Documents: .pdf | .docx | .doc | .pptx | .ppt
  Images:    .png | .jpg | .jpeg | .bmp | .tiff | .webp
"""

import sys
import os

# ====== Dynamic CUDA DLL Loader for PaddlePaddle ======
# Ensures the RTX GPU is utilized instead of falling back to CPU/DirectML.
_cuda_initialized = False

def _setup_cuda():
    global _cuda_initialized
    if _cuda_initialized:
        return
    _cuda_initialized = True

    def _add_dll_path(path):
        """Register a DLL directory with both os.add_dll_directory and PATH."""
        if path and os.path.isdir(path):
            try:
                os.add_dll_directory(path)
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")

    try:
        # ── 1. Local cuDNN archive (downloaded from NVIDIA) ──────────
        _cudnn_bin = os.path.join(
            os.path.expanduser("~"),
            "Downloads",
            "cudnn-windows-x86_64-8.9.7.29_cuda11-archive",
            "cudnn-windows-x86_64-8.9.7.29_cuda11-archive",
            "bin",
        )
        _add_dll_path(_cudnn_bin)

        # ── 2. pip-installed nvidia-* packages ───────────────────────
        packages = ["nvidia.cudnn", "nvidia.cublas", "nvidia.cuda_nvrtc", "nvidia.cuda_runtime"]
        for pkg in packages:
            try:
                import importlib
                module = importlib.import_module(pkg)
                if hasattr(module, '__file__') and module.__file__:
                    bin_path = os.path.join(os.path.dirname(module.__file__), "bin")
                else:
                    bin_path = os.path.join(module.__path__[0], "bin")
                _add_dll_path(bin_path)
            except Exception:
                pass
    except Exception:
        pass
# ======================================================

import io
import logging
import tempfile
from typing import Any, Callable, Optional

# ── 兼容性补丁 (针对 Python 3.9) ───────────────────────────────────────────
if sys.version_info < (3, 10):
    try:
        import importlib_metadata
        import importlib.metadata
        if not hasattr(importlib.metadata, 'packages_distributions'):
            importlib.metadata.packages_distributions = importlib_metadata.packages_distributions
    except ImportError:
        pass

logger = logging.getLogger(__name__)

# ── 图片扩展名集合 ────────────────────────────────────────────
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}

# ── 文档扩展名集合 ────────────────────────────────────────────
_DOC_EXTS = {".pdf", ".docx", ".doc", ".pptx", ".ppt"}

# ── 延迟初始化单例 ────────────────────────────────────────────
_parser = None
_ocr_processor = None
import threading
_init_lock = threading.Lock()

def _get_parser():
    """Lazy initialization of DocumentParser (singleton)."""
    global _parser
    if _parser is None:
        with _init_lock:
            if _parser is None:
                _setup_cuda()
                from core_engine import DocumentParser
                _parser = DocumentParser(use_gpu=True, preprocess=True)
                logger.info("DocumentParser initialization complete | mode=auto-optimized")
    return _parser


def _get_ocr_processor():
    """
    Lazy initialization of OCRProcessor (for pure image formats).
    """
    global _ocr_processor
    if _ocr_processor is None:
        with _init_lock:
            if _ocr_processor is None:
                _setup_cuda()
                from core_engine.ocr_module import OCRProcessor
                _ocr_processor = OCRProcessor(use_gpu=True, preprocess=True)
                logger.info("OCRProcessor initialization complete | mode=auto-optimized")
    return _ocr_processor


def preload_models():
    """Preload OCR models to avoid startup delay."""
    logger.info("Preloading OCR models...")
    try:
        processor = _get_ocr_processor()
        processor._get_ocr()
        _get_parser()
        logger.info("OCR models preloaded successfully.")
    except Exception as e:
        logger.error("Failed to preload OCR models: %s", e)


def _pages_to_text(pages: list) -> str:
    """
    Converts pages list returned by DocumentParser to human-readable plain text.
    """
    lines = []
    for page in pages:
        page_num = page.get("page_num", "?")
        page_type = page.get("page_type", "unknown")
        text_blocks = page.get("text_blocks", [])

        lines.append(f"-- Page {page_num} ({page_type}) --")

        for block in text_blocks:
            text = block.get("text", "").strip()
            if text:
                lines.append(text)

        lines.append("")  # 页间空行

    return "\n".join(lines).strip()


def extract_text_from_image(file_obj, progress_callback: Optional[Callable] = None) -> str:
    """
    Extracts text from uploaded file.

    Parameters
    ----------
    file_obj : Streamlit UploadedFile
        File object containing .name attribute and byte content.
    progress_callback : callable | None
        Progress callback function, receives (current, total) parameters.
    """
    if not file_obj:
        return ""

    # ── 读取文件字节 ──────────────────────────────────────────
    file_bytes = file_obj.read()
    file_obj.seek(0)

    # ── 判断文件类型 ──────────────────────────────────────────
    name: str = getattr(file_obj, "name", "upload.bin")
    ext = os.path.splitext(name)[1].lower()

    if ext not in _IMAGE_EXTS and ext not in _DOC_EXTS:
        return f"⚠️ Unsupported file format: '{ext}'"

    # ── 写入临时文件 ──────────────────────────────────────────
    tmp_path: Optional[str] = None
    try:
        suffix = ext if ext else ".tmp"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # 路径 A：文档格式
        if ext in _DOC_EXTS:
            parser = _get_parser()
            result = parser.process_file(tmp_path, progress_callback=progress_callback)
            pages = result.get("pages", [])
            text = _pages_to_text(pages)
            return text if text else "No text detected."

        # 路径 B：图片格式
        else:
            from PIL import Image
            processor = _get_ocr_processor()

            img = Image.open(io.BytesIO(file_bytes)).convert("RGB")

            # 尺寸限制 - 预处理并按比例缩小超大图像（提速与精度的平衡点）
            max_dim = 1500
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.LANCZOS)

            ocr_results = processor.process_images([img], progress_callback=progress_callback)
            if not ocr_results:
                return "No text detected."

            blocks = ocr_results[0].get("blocks", [])
            if not blocks:
                return "No text detected."

            texts = [b.get("text", "").strip() for b in blocks if b.get("text", "").strip()]
            if texts:
                avg_len = sum(len(t) for t in texts) / len(texts)
                joined = "".join(texts) if (avg_len < 2.0 and len(texts) > 5) else "\n".join(texts)
            else:
                joined = ""

            return f"-- Page 1 (image) --\n{joined}" if joined else "No text detected."

    except Exception as e:
        logger.error("OCR Engine Error: %s", e, exc_info=True)
        return f"⚠️ OCR Engine Error: {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    pass
