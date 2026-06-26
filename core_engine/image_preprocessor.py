"""
image_preprocessor.py
─────────────────────
OpenCV image preprocessing pipeline. Performs normalization before feeding images into PaddleOCR,
improving OCR accuracy especially for low-quality scans.

Processing steps:
  1. Grayscale conversion
  2. Adaptive thresholding (binarization)
  3. Fast Non-Local Means Denoising
"""

import logging
from typing import Union

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
    """Converts PIL Image to OpenCV BGR numpy array."""
    rgb = np.array(pil_image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def cv2_to_pil(cv2_image: np.ndarray) -> Image.Image:
    """Converts OpenCV BGR numpy array to PIL Image."""
    rgb = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def preprocess_image(
    image: Union[np.ndarray, Image.Image],
    do_grayscale: bool = True,
    do_denoise: bool = True,
    do_binarize: bool = True,
) -> np.ndarray:
    """
    Performs OCR preprocessing pipeline on input image, returning processed numpy array.

    Parameters
    ----------
    image : np.ndarray | PIL.Image.Image
        Input image (supports BGR numpy array or PIL Image)
    do_grayscale : bool
        Whether to convert to grayscale (default True)
    do_denoise : bool
        Whether to denoise (default True, depends on grayscale)
    do_binarize : bool
        Whether to perform adaptive binarization (default True, depends on grayscale)

    Returns
    -------
    np.ndarray
        Processed image (grayscale or pseudo-color, depending on parameters)
    """
    # --- 统一转为 OpenCV BGR array ---
    if isinstance(image, Image.Image):
        img = pil_to_cv2(image)
    else:
        img = image.copy()

    # --- 步骤 1：灰度化 ---
    if do_grayscale:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        return img  # 后续步骤依赖灰度图，直接返回

    # --- 步骤 2：去噪（快速非局部均值去噪，适合扫描件噪点）---
    if do_denoise:
        gray = cv2.fastNlMeansDenoising(
            gray,
            h=10,           # 滤波强度（值越大去噪越强，但会模糊细节）
            templateWindowSize=7,
            searchWindowSize=21,
        )

    # --- 步骤 3：自适应阈值二值化 ---
    if do_binarize:
        binary = cv2.adaptiveThreshold(
            gray,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            thresholdType=cv2.THRESH_BINARY,
            blockSize=11,   # 邻域大小（必须为奇数）
            C=2,            # 从均值中减去的常数
        )
        return binary

    return gray
