"""
test_runner.py — OCR 引擎集成测试（直接运行版）
================================================
使用方式：直接双击或运行:
    C:\\Users\\User\\AppData\\Local\\Programs\\Python\\Python39\\python.exe test_runner.py

⚠️  Windows 多进程保护：所有 DocumentParser 调用严格在 if __name__ == "__main__": 内
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Windows 控制台 UTF-8 输出支持（防止 cp1252 编码报错）──────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────────────────────
#  ★ 硬编码配置 — 按需修改以下三行
# ─────────────────────────────────────────────────────────────────────────────
INPUT_FILE   = r"C:\Users\User\Desktop\fyp\data_test\verify_legacy.ppt"   # 待解析文件
OUTPUT_DIR   = r"C:\Users\User\Desktop\output"          # 结果输出目录
USE_GPU      = False                                      # True=GPU, False=CPU
# ─────────────────────────────────────────────────────────────────────────────


# ── 全局 DEBUG 日志配置（输出到控制台） ──────────────────────────────────────
def _setup_logging() -> None:
    """Enable DEBUG level logging with formatted output for real-time progress tracking."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  [%(levelname)-8s]  %(name)s  →  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    # 避免重复添加 handler
    if not root.handlers:
        root.addHandler(handler)
    else:
        root.handlers = [handler]


# ── 结果写入 Markdown ──────────────────────────────────────────────────────
def _write_markdown(result: dict, md_path: str) -> None:
    """Write analysis results as plain text Markdown, suitable for manual comparison."""
    meta  = result["metadata"]
    pages = result["pages"]

    total_chars   = sum(len(b["text"]) for p in pages for b in p["text_blocks"] if b.get("text"))
    native_blocks = sum(1 for p in pages for b in p["text_blocks"] if b.get("source") == "native")
    ocr_blocks    = sum(1 for p in pages for b in p["text_blocks"] if b.get("source") == "ocr")
    scanned_cnt   = sum(1 for p in pages if p.get("page_type") == "scanned")
    avg_conf = (
        sum(b["confidence"] for p in pages for b in p["text_blocks"]
            if b.get("source") == "ocr" and b.get("confidence"))
        / max(ocr_blocks, 1)
    )

    lines = []

    # ── 标题 & 单行摘要 ────────────────────────────────────────────────
    lines += [
        f"# {meta['file_name']}",
        f"",
        (f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}　"
         f"{meta['total_pages']} Pages total　"
         f"Chars: {total_chars:,}　"
         f"Native Blocks: {native_blocks}　"
         f"OCR Blocks: {ocr_blocks} (Avg Conf: {avg_conf:.0%})　"
         f"Scanned Pages: {scanned_cnt}　"
         f"Time: {meta['processing_time_sec']:.1f}s"),
        f"",
        f"---",
        f"",
    ]

    # ── 逐页纯文字内容 ────────────────────────────────────────────────
    for page in pages:
        pn  = page["page_num"]
        tag = "Native" if page["page_type"] == "native" else "Scanned"
        blocks = page["text_blocks"]

        lines.append(f"## Page {pn}  [{tag}]")
        lines.append(f"")

        if page.get("table_html"):
            lines.append("```html")
            lines.append(page["table_html"])
            lines.append("```")
            lines.append("")

        for block in blocks:
            text = block.get("text", "").strip()
            if text:
                lines.append(text)
                lines.append("")

        lines.append("---")
        lines.append("")

    # ── 写文件 ──────────────────────────────────────────────────────
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nMarkdown report saved: {md_path}")





# ── 控制台性能面板 ────────────────────────────────────────────────────────────
def _print_performance_panel(result: dict) -> None:
    """Print detailed Performance panel in console."""
    meta  = result["metadata"]
    pages = result["pages"]

    total_chars    = sum(len(b["text"]) for p in pages for b in p["text_blocks"] if b.get("text"))
    native_blocks  = sum(1 for p in pages for b in p["text_blocks"] if b.get("source") == "native")
    ocr_blocks     = sum(1 for p in pages for b in p["text_blocks"] if b.get("source") == "ocr")
    scanned_pages  = sum(1 for p in pages if p.get("page_type") == "scanned")
    native_pages   = sum(1 for p in pages if p.get("page_type") == "native")
    avg_ocr_conf   = (
        sum(b["confidence"] for p in pages for b in p["text_blocks"] if b.get("source") == "ocr" and b.get("confidence"))
        / max(ocr_blocks, 1)
    )
    chars_per_sec  = total_chars / max(meta["processing_time_sec"], 0.001)
    pages_per_sec  = meta["total_pages"] / max(meta["processing_time_sec"], 0.001)

    W = 60
    sep  = "-" * W
    dsep = "=" * W

    print(f"\n{dsep}")
    print(f"  >> PERFORMANCE REPORT".center(W))
    print(f"{dsep}")
    print(f"  [FILE]  {meta['file_name']}")
    print(f"  [TYPE]  {meta['file_type'].upper()}")
    print(f"{sep}")
    print(f"  TIMING")
    print(f"  Total Time     : {meta['processing_time_sec']:.3f} sec")
    print(f"  Total Pages    : {meta['total_pages']}")
    print(f"    Native PDF   : {native_pages}")
    print(f"    Scanned      : {scanned_pages}")
    print(f"{sep}")
    print(f"  TEXT EXTRACTION")
    print(f"  Total Chars    : {total_chars:,}")
    print(f"  Native Blocks  : {native_blocks:,}")
    print(f"  OCR Blocks     : {ocr_blocks:,}")
    print(f"  OCR Avg Conf   : {avg_ocr_conf:.2%}")
    print(f"{sep}")
    print(f"  THROUGHPUT")
    print(f"  Chars / sec    : {chars_per_sec:,.1f}")
    print(f"  Pages / sec    : {pages_per_sec:.3f}")
    print(f"{sep}")
    print(f"  GPU Inference  : {'ON' if meta['use_gpu'] else 'OFF (CPU)'}")
    print(f"  OCR Engine     : {meta['ocr_engine']}")
    print(f"{dsep}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  ⚠️  __main__ 保护块 — Windows spawn 模式必须
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _setup_logging()

    # -- Check input file --------------------------------------------------
    input_path  = Path(INPUT_FILE)
    output_dir  = Path(OUTPUT_DIR)
    stem        = input_path.stem

    json_output = output_dir / f"{stem}_result.json"
    md_output   = output_dir / f"{stem}_report.md"

    if not input_path.is_file():
        print(f"\n[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # -- Startup banner ----------------------------------------------------
    W = 60
    print("=" * W)
    print("  OCR Document Parser -- Direct Run Test".center(W))
    print("=" * W)
    print(f"  Input File : {input_path.name}")
    print(f"  JSON Out   : {json_output}")
    print(f"  MD Report  : {md_output}")
    print(f"  GPU Mode   : {'ON' if USE_GPU else 'OFF'}")
    print("-" * W)
    print("  [DEBUG mode ON -- real-time logs below]")
    print("-" * W + "\n")

    # -- Import engine -----------------------------------------------------
    try:
        from core_engine.parser_main import DocumentParser
    except ImportError as e:
        print(f"[ERROR] Import failed: {e}\nRun this script from the project root (containing core_engine/).", file=sys.stderr)
        sys.exit(1)

    # -- Init & run --------------------------------------------------------
    parser = DocumentParser(use_gpu=USE_GPU)

    try:
        print(f"[...] Parsing: {input_path.name}\n")
        result = parser.process_file(
            file_path=str(input_path),
            output_json_path=str(json_output),
        )

        # -- Markdown report -----------------------------------------------
        _write_markdown(result, str(md_output))

        # -- Performance panel ---------------------------------------------
        _print_performance_panel(result)

        print(f"[OK] Done!")
        print(f"     JSON --> {json_output}")
        print(f"     MD   --> {md_output}\n")

    except FileNotFoundError as e:
        print(f"\n[ERROR] File error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"\n[ERROR] Format error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

