# 20260920 · feat · PDF / Word / Excel 解析（阶段 A 的 A2.3–A2.5）

## 变更摘要

接入三种新格式的文件解析，并把上传入口扩展到 PDF / Word / Excel。阶段 A 的解析部分完成。

## 实现内容

| 文件 | 内容 |
|---|---|
| `src/services/doc_parser.py`（新增） | 统一把文件转成 Markdown：文本 / PDF / Word / Excel；不支持与解析失败分别抛不同异常 |
| `src/services/source_service.py` | 新增 `create_source_from_file`（文件 → Markdown → 走原切片流程）、`mark_unsupported`、`get_chunks_by_ids` |
| `src/ui/page_sources.py` | 上传入口支持 `pdf / docx / xlsx`；失败时按状态给不同提示 |
| `tests/test_doc_parser.py`（新增） | 8 项：各格式解析、Excel 表头识别、空 PDF、不支持格式 |
| `tests/test_source_service.py` | 新增 4 项：不支持格式落 `unsupported`、坏文件落 `failed`、Excel 变成切片、按 ID 查出处的返回结构 |
| `requirements.txt` | 追加 `pymupdf` / `python-docx` / `openpyxl` |

## 设计要点

1. **解析器只产出 Markdown**：之后走与粘贴文本完全相同的切片与索引流程，**下游不需要知道原始格式**
2. **Excel 按表头语义解析**：识别题干 / 选项 / 正确答案 / 解析列 → 每道题变成一个 `## 题目 N` 小节；
   找不到题干列时**直接报错并提示调整表头，不猜列含义**
3. **失败分档**：`unsupported`（格式不支持）与 `failed`（解析失败）分开，界面提示不同
4. **PDF 无文本时明确报错**，提示"可能是扫描件，需要 OCR"，不产出空来源

## 过程记录

| 现象 | 原因 | 处理 |
|---|---|---|
| PDF 测试抽出的是 `···` | PyMuPDF 默认字体渲染不了中文，写进去的就是省略号 | 测试样本改用内置中文字体 `china-s` |
| （无其它阻塞） | 装依赖需要联网，本次已获授权，`uv pip install` 正常 | 依赖已同步进 `requirements.txt` |

## 影响范围

- 测试：**107 passed, 1 skipped**（新增 12 项）
- 依赖：新增 3 个第三方包（`pymupdf` / `python-docx` / `openpyxl`，含传递依赖 `lxml` / `et-xmlfile`）
- 规格：`training-source-selection` 阶段 A 已完成 **23/40** 项，剩余 17 项集中在阶段 B 与收尾
- 证据：`workspace/evidence/20260920-资料来源阶段A.md`

## 尚未完成的

- **A4.1**（训练项落 `source_chunk_ids`）：依赖 `training_items` 表，属 `training-path-generation`，未建；
  校验函数 `link_chunk_ids` 已实现并测过，等表建好直接挂
- **A6.2**（真实资料的解析统计）：需要你提供真实 PDF / Word / Excel 样本，当前只用测试构造的样本验证过

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/services/doc_parser.py` | 新增 |
| `src/services/source_service.py` | 修改 |
| `src/ui/page_sources.py` | 修改 |
| `tests/test_doc_parser.py` | 新增 |
| `tests/test_source_service.py` | 修改 |
| `requirements.txt` | 修改 |

## 关联 OpenSpec change id

`training-source-selection`（阶段 A 解析部分完成）
