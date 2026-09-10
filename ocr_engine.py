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

def _check_gpu_support() -> bool:
    """Dynamically check if GPU is available and supported by Paddle."""
    try:
        import paddle
        return bool(paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0)
    except Exception:
        return False

def _get_parser():
    """Lazy initialization of DocumentParser (singleton)."""
    global _parser
    if _parser is None:
        with _init_lock:
            if _parser is None:
                _setup_cuda()
                use_gpu = _check_gpu_support()
                from core_engine import DocumentParser
                _parser = DocumentParser(use_gpu=use_gpu, preprocess=True)
                logger.info("DocumentParser initialization complete | use_gpu=%s | mode=auto-optimized", use_gpu)
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
                use_gpu = _check_gpu_support()
                from core_engine.ocr_module import OCRProcessor
                _ocr_processor = OCRProcessor(use_gpu=use_gpu, preprocess=True)
                logger.info("OCRProcessor initialization complete | use_gpu=%s | mode=auto-optimized", use_gpu)
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


def extract_text_via_gemini_vision(image, api_key: str) -> str:
    """
    Transcribes handwritten notes and complex document images using Google Gemini Multimodal Vision.
    Specifically solves ruled notebook paper, cursive, equations, and informal handwriting.
    """
    if not api_key:
        return ""
    try:
        from summarizer import _get_model_name, _generate_with_retry
        import google.generativeai as genai
        
        genai.configure(api_key=api_key)
        model_name = _get_model_name(api_key)
        model = genai.GenerativeModel(model_name)
        
        prompt = """You are an expert Academic Document & Handwriting Transcription Engine.
Your task is to accurately transcribe all handwritten or printed text, formulas, symbols, and notes visible in this image.

RULES:
1. Accurately transcribe all handwritten and printed text line by line.
2. Faithfully preserve list hierarchies (e.g., i, ii, iii, bullets, numbers, dashes, sub-items).
3. Faithfully transcribe equations, formulas, code, and academic terms.
4. If words are crossed out or erased, ignore the strikethrough error and transcribe the intended clean text.
5. Output ONLY the raw transcribed text. Do NOT add preamble, conversational remarks, or markdown code fence blocks."""

        response = _generate_with_retry(model, [prompt, image])
        return response.text.strip() if response and response.text else ""
    except Exception as e:
        logger.warning("Gemini Vision transcription error: %s", e)
        return ""


def extract_text_from_image(
    file_obj, 
    progress_callback: Optional[Callable] = None,
    api_key: Optional[str] = None,
    handwritten_mode: bool = False,
    **kwargs
) -> str:
    """
    Extracts text from uploaded file supporting both classical OCR (PaddleOCR)
    and Multimodal LLM Vision (Gemini Vision) for handwritten lecture notes.

    Parameters
    ----------
    file_obj : Streamlit UploadedFile
        File object containing .name attribute and byte content.
    progress_callback : callable | None
        Progress callback function, receives (current, total) parameters.
    api_key : str | None
        Gemini API key for multimodal vision transcription.
    handwritten_mode : bool
        Whether to prioritize multimodal vision for handwritten notes.
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

    # ── 优先处理手写模式（Handwritten Notes Mode）────────────────
    if handwritten_mode and api_key:
        try:
            from PIL import Image
            if ext in _IMAGE_EXTS:
                if progress_callback:
                    progress_callback(1, 1)
                img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
                vision_text = extract_text_via_gemini_vision(img, api_key)
                if vision_text:
                    return f"-- Page 1 (Handwritten Notes - Gemini Vision) --\n{vision_text}"
            elif ext == ".pdf":
                # Multi-page handwritten PDF support
                import fitz
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                total_pages = len(doc)
                page_texts = []
                for p_idx in range(total_pages):
                    if progress_callback:
                        progress_callback(p_idx + 1, total_pages)
                    page = doc[p_idx]
                    pix = page.get_pixmap(dpi=150)
                    p_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    p_text = extract_text_via_gemini_vision(p_img, api_key)
                    if p_text:
                        page_texts.append(f"-- Page {p_idx + 1} (Handwritten Notes - Gemini Vision) --\n{p_text}")
                if page_texts:
                    return "\n\n".join(page_texts)
        except Exception as e_hw:
            logger.warning("Handwritten mode direct vision failed: %s, falling back to standard pipeline", e_hw)

    # ── 写入临时文件执行标准解析管线 ────────────────────────────
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
            
            # 如果文档解析出来字数极少且为扫描 PDF，尝试 Gemini Vision 兜底
            if (not text or len(text.strip()) < 20 or "No text detected" in text) and ext == ".pdf" and api_key:
                try:
                    import fitz
                    from PIL import Image
                    doc = fitz.open(tmp_path)
                    total_pages = min(len(doc), 5)
                    recovered = []
                    for p_idx in range(total_pages):
                        page = doc[p_idx]
                        pix = page.get_pixmap(dpi=150)
                        p_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        p_txt = extract_text_via_gemini_vision(p_img, api_key)
                        if p_txt:
                            recovered.append(f"-- Page {p_idx + 1} (Recovered via Gemini Vision) --\n{p_txt}")
                    if recovered:
                        return "\n\n".join(recovered)
                except Exception:
                    pass
            return text if text else "No text detected."

        # 路径 B：图片格式
        else:
            from PIL import Image
            img = Image.open(io.BytesIO(file_bytes)).convert("RGB")

            # 尺寸限制 - 预处理并按比例缩小超大图像
            max_dim = 1500
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.LANCZOS)

            processor = _get_ocr_processor()
            ocr_results = processor.process_images([img], progress_callback=progress_callback)
            
            blocks = ocr_results[0].get("blocks", []) if ocr_results else []
            texts = [b.get("text", "").strip() for b in blocks if b.get("text", "").strip()]
            
            paddle_text = ""
            if texts:
                avg_len = sum(len(t) for t in texts) / len(texts)
                paddle_text = "".join(texts) if (avg_len < 2.0 and len(texts) > 5) else "\n".join(texts)
            
            # 智能兜底检测（Auto Fallback for Handwriting / Low Confidence）:
            clean_paddle = paddle_text.strip()
            if (not clean_paddle or len(clean_paddle) < 20 or len(texts) <= 2) and api_key:
                logger.info("PaddleOCR yielded minimal/no text (%d chars). Triggering Gemini Vision recovery...", len(clean_paddle))
                vision_text = extract_text_via_gemini_vision(img, api_key)
                if vision_text and len(vision_text) > len(clean_paddle):
                    return f"-- Page 1 (Auto-Recovered via Gemini Vision) --\n{vision_text}"

            return f"-- Page 1 (image) --\n{paddle_text}" if paddle_text else "No text detected."

    except Exception as e:
        logger.error("OCR Engine Error: %s", e, exc_info=True)
        # 如果传统 OCR 崩溃（如系统缺失图形库），且有 API Key，无缝启用 Gemini Vision 兜底！
        if api_key and ext in _IMAGE_EXTS:
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
                vision_text = extract_text_via_gemini_vision(img, api_key)
                if vision_text:
                    return f"-- Page 1 (Image - Gemini Vision Fallback) --\n{vision_text}"
            except Exception:
                pass
        return f"⚠️ OCR Engine Error: {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    pass
