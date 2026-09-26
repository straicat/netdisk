from __future__ import annotations

import functools
from typing import Iterable, Optional


_PATCHES_APPLIED = False


def apply() -> None:
    """应用全部补丁。幂等：多次调用也只会实际应用一次。"""
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED:
        return
    _apply_compat_attrs_patch()
    _apply_only_sheets_patch()
    _apply_pivot_caches_patch()
    _PATCHES_APPLIED = True


def is_applied() -> bool:
    """返回补丁是否已生效（用于测试 / 健康检查）。"""
    return _PATCHES_APPLIED


# ---------------------------------------------------------------------------
# 1) dimensions.py · 兼容 defaultColWidthPt / widthPt
# ---------------------------------------------------------------------------


def _apply_compat_attrs_patch() -> None:
    """让 SheetFormatProperties / RowDimension / ColumnDimension 容忍
    Excel / WPS 写出的非规范字段 ``defaultColWidthPt`` 与 ``widthPt``。
    """
    from openpyxl.descriptors import Float
    from openpyxl.worksheet.dimensions import (
        ColumnDimension,
        RowDimension,
        SheetFormatProperties,
    )

    # 1a) SheetFormatProperties.defaultColWidthPt —— 在类外追加描述符，
    #     再改写 __init__ 接受并保存 defaultColWidthPt。
    if "defaultColWidthPt" not in SheetFormatProperties.__dict__:
        SheetFormatProperties.defaultColWidthPt = Float(allow_none=True)
    if not getattr(SheetFormatProperties.__init__, "_patched_applied", False):
        # noinspection PyTypeChecker
        _orig_sfp_init = SheetFormatProperties.__init__

        @functools.wraps(_orig_sfp_init)
        def _patched_sfp_init(self, *args, defaultColWidthPt=None, **kwargs):
            # 原版 __init__ 不认识 defaultColWidthPt；先正常初始化其余字段，
            # 再把 defaultColWidthPt 通过描述符写入实例（描述符会做类型转换）。
            _orig_sfp_init(self, *args, **kwargs)
            self.defaultColWidthPt = defaultColWidthPt

        _patched_sfp_init._patched_applied = True
        SheetFormatProperties.__init__ = _patched_sfp_init

    # 1b) ColumnDimension.__init__ —— 吃掉 widthPt kwarg。
    if not getattr(ColumnDimension.__init__, "_patched_applied", False):
        _orig_cd_init = ColumnDimension.__init__

        @functools.wraps(_orig_cd_init)
        def _patched_cd_init(self, *args, **kwargs):
            kwargs.pop("widthPt", None)
            return _orig_cd_init(self, *args, **kwargs)

        _patched_cd_init._patched_applied = True
        ColumnDimension.__init__ = _patched_cd_init

    # 1c) RowDimension.__init__ —— 吃掉 widthPt kwarg（原版已有 **kw 兜底，
    #     但显式 pop 后行为更明确，也与 patched 源码保持一致）。
    if not getattr(RowDimension.__init__, "_patched_applied", False):
        _orig_rd_init = RowDimension.__init__

        @functools.wraps(_orig_rd_init)
        def _patched_rd_init(self, *args, **kwargs):
            kwargs.pop("widthPt", None)
            return _orig_rd_init(self, *args, **kwargs)

        _patched_rd_init._patched_applied = True
        RowDimension.__init__ = _patched_rd_init


# ---------------------------------------------------------------------------
# 2) reader/excel.py · load_workbook(only_sheets=...)
# ---------------------------------------------------------------------------


def _apply_only_sheets_patch() -> None:
    """给 ``load_workbook`` / ``ExcelReader`` 增加 ``only_sheets`` 支持。

    ``only_sheets`` 接受可迭代的 sheet 名集合；为 ``None`` 时行为与原版一致。
    非白名单的 sheet 在可写模式下被替换为只带 ``sheet_state`` 的占位 sheet，
    在 ``read_only=True`` 模式下直接跳过。整体保留原 patch 在可写模式下保留
    全部 sheet 名的语义，方便下游 ``wb.sheetnames`` 的判空逻辑继续工作。
    """
    import openpyxl
    from openpyxl.reader.excel import ExcelReader

    # 2a) ExcelReader.__init__ —— 默认存在 only_sheets 属性，便于后续
    #     read_worksheets 直接读取。
    if not getattr(ExcelReader.__init__, "_patched_applied", False):
        _orig_er_init = ExcelReader.__init__

        @functools.wraps(_orig_er_init)
        def _patched_er_init(self, *args, only_sheets: Optional[Iterable[str]] = None, **kwargs):
            _orig_er_init(self, *args, **kwargs)
            self.only_sheets = set(only_sheets) if only_sheets else None

        _patched_er_init._patched_applied = True
        ExcelReader.__init__ = _patched_er_init

    # 2b) ExcelReader.read_worksheets —— 保留原方法主体，仅在循环顶部
    #     插入 only_sheets 过滤（占位 sheet 创建）。通过替换 ``parser.find_sheets``
    #     为一个仅 yield 白名单 sheet 的生成器，避免大段复制 read_worksheets 主体。
    if not getattr(ExcelReader.read_worksheets, "_patched_applied", False):
        _orig_read_worksheets = ExcelReader.read_worksheets

        @functools.wraps(_orig_read_worksheets)
        def _patched_read_worksheets(self):
            only_sheets = getattr(self, "only_sheets", None)
            if not only_sheets:
                # 没有启用过滤，保持原行为
                return _orig_read_worksheets(self)

            # 一次性物化所有 sheet 列表（find_sheets 是生成器，不能反复遍历）
            all_pairs = list(self.parser.find_sheets())

            # 可写模式下：未在白名单的 sheet 创建占位 sheet，
            # 保证 wb.sheetnames 保持完整（与原 patch 行为一致）。
            if not self.read_only:
                for sheet, _rel in all_pairs:
                    if sheet.name not in only_sheets:
                        ws = self.wb.create_sheet(sheet.name)
                        ws.sheet_state = sheet.state

            # 临时替换 parser.find_sheets 为白名单版本。原方法在循环内
            # 通过 self.parser.find_sheets() 取 sheet，靠实例属性赋值屏蔽
            # 类方法。
            only_set = only_sheets

            def _filtered_find_sheets():
                for sheet, rel in all_pairs:
                    if sheet.name in only_set:
                        yield sheet, rel

            _orig_find_sheets = type(self.parser).find_sheets
            self.parser.find_sheets = _filtered_find_sheets
            try:
                return _orig_read_worksheets(self)
            finally:
                # 还原，避免影响后续使用 parser 的代码
                self.parser.find_sheets = _orig_find_sheets

        _patched_read_worksheets._patched_applied = True
        ExcelReader.read_worksheets = _patched_read_worksheets

    # 2c) openpyxl.load_workbook —— 把 only_sheets 透传给 ExcelReader。
    if not getattr(openpyxl.load_workbook, "_patched_applied", False):
        _orig_load = openpyxl.load_workbook

        @functools.wraps(_orig_load)
        def _patched_load_workbook(filename, *args, only_sheets: Optional[Iterable[str]] = None, **kwargs):
            reader = ExcelReader(filename, *args, **kwargs)
            # ExcelReader.__init__ 已设置 only_sheets=None，这里再覆盖
            # 以兼容调用方传 only_sheets 的场景。
            reader.only_sheets = set(only_sheets) if only_sheets else None
            reader.read()
            return reader.wb

        _patched_load_workbook._patched_applied = True
        _patched_load_workbook.__wrapped__ = _orig_load
        # 同时更新模块顶层 ``openpyxl.load_workbook`` 引用与 ``openpyxl.reader.excel``
        # 顶层 ``load_workbook`` 引用（后者是 openpyxl 公开 API 的真正源头）。
        openpyxl.load_workbook = _patched_load_workbook
        try:
            from openpyxl.reader import excel as _reader_excel_mod
            _reader_excel_mod.load_workbook = _patched_load_workbook
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# 3) reader/workbook.py · pivot_caches 短路
# ---------------------------------------------------------------------------


def _apply_pivot_caches_patch() -> None:
    """``WorkbookParser.pivot_caches`` 直接返回空 dict，跳过全部 pivot cache 解析。"""
    from openpyxl.reader.workbook import WorkbookParser

    if getattr(WorkbookParser.pivot_caches, "_patched_applied", False):
        return

    def _pivot_caches_empty(self):
        return {}

    _pivot_caches_empty._patched_applied = True
    # noinspection PyPropertyAccess
    setattr(WorkbookParser, "pivot_caches", property(_pivot_caches_empty))


# ---------------------------------------------------------------------------
# 模块 import 时自动应用
# ---------------------------------------------------------------------------

apply()
