"""Generate the disposable bilingual PDF used by the local Demo acceptance run."""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="PDF path outside this repository")
    return parser.parse_args()


def main() -> None:
    output = parse_args().output.expanduser().resolve()
    if output == REPOSITORY_ROOT or output.is_relative_to(REPOSITORY_ROOT):
        raise SystemExit("output must be outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)

    document = pymupdf.open()
    document.set_metadata(
        {
            "title": "Aurora Bamboo Calibration Study",
            "author": "Lin Qiao; Morgan Reed",
            "creationDate": "D:20260301000000+08'00'",
        }
    )

    page_one = document.new_page(width=595, height=842)
    page_one.insert_textbox(
        pymupdf.Rect(54, 60, 541, 780),
        """Aurora Bamboo Calibration Study

Lin Qiao and Morgan Reed, 2026

Abstract

This synthetic study evaluates a bilingual retrieval pipeline on the Aurora-Bamboo benchmark. The benchmark contains paired English and Chinese passages and requires every reported result to remain traceable to its source page.

Method

The system first recalls candidate passages with multilingual dense embeddings. A local cross-encoder then reranks the candidates before evidence is presented to the language model. The experiment intentionally records the decisive calibration result on the following page so page-level citation behavior can be tested.
""",
        fontsize=12,
        fontname="helv",
        lineheight=1.45,
    )

    page_two = document.new_page(width=595, height=842)
    page_two.insert_textbox(
        pymupdf.Rect(54, 60, 541, 780),
        """实验结果 / Results

在 Aurora-Bamboo 双语基准上，研究团队将“月光竹门控”（Moonlight Bamboo Gate）的校准延迟固定为 37 毫秒。这个数值只出现在本页，用于验证问答系统能否检索并引用正确页码。

The decisive result is that the Moonlight Bamboo Gate uses a calibration latency of exactly 37 milliseconds. This value appears only on page 2 and is the ground-truth answer for the citation acceptance test.

After local reranking, the passage containing the 37-millisecond result ranked above general method descriptions. The authors therefore recommend preserving page, quote, and chunk identifiers throughout retrieval and answer generation.
""",
        fontsize=12,
        fontname="china-s",
        lineheight=1.5,
    )

    document.save(output, garbage=4, deflate=True)
    document.close()
    print(f"generated bilingual PDF: {output} (2 pages)")


if __name__ == "__main__":
    main()
