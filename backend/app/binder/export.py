"""Print export. Physical accuracy is the whole point -- a blurry or mis-scaled insert is a
wasted sheet of cardstock.

Requirements: exact mm dimensions, no scaling, >=300 DPI embed, 2mm bleed, crop marks,
Letter and A4 sheet packing. Reject sub-300-DPI sources with a clear warning rather than
silently printing something blurry. Build with ReportLab.
"""


def export_inserts_pdf(binder_id: int, out_path: str, page_size: str = "letter") -> str:
    raise NotImplementedError  # TODO(phase-3.9)


def export_spread_png(binder_id: int, spread_index: int, out_path: str) -> str:
    raise NotImplementedError  # TODO(phase-3.10)
