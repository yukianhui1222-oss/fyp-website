
import sys
from pathlib import Path

# 使用系统 Python 3.9
python_exe = r"C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe"

try:
    from paddleocr import PaddleOCR
    import inspect
    
    print("--- PaddleOCR Inspect ---")
    sig = inspect.signature(PaddleOCR.__init__)
    print(f"PaddleOCR.__init__ signature: {sig}")
    
    # 尝试最小化初始化
    print("\nAttempting minimal init...")
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        print("Minimal init successful")
    except Exception as e:
        print(f"Minimal init failed: {e}")

    # 尝试带 use_gpu 初始化
    print("\nAttempting init with use_gpu=False...")
    try:
        ocr = PaddleOCR(use_gpu=False)
        print("Init with use_gpu=False successful")
    except Exception as e:
        print(f"Init with use_gpu=False failed: {e}")

except Exception as e:
    print(f"Global error: {e}")
