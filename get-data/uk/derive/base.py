from __future__ import annotations

import logging

from ..loaders.base import LoadContext

log = logging.getLogger(__name__)


class Step:
    """Một bước derive. run(ctx) → dict thống kê. Chạy trong một transaction; lỗi/kiểm tra fail → rollback."""

    name: str = ""
    depends_on: tuple[str, ...] = ()   # bước derive khác phải chạy trước
    needs_sources: tuple[str, ...] = ()  # nguồn phải đã 'loaded'
    description: str = ""

    def run(self, ctx: LoadContext) -> dict:
        raise NotImplementedError


DERIVED_DATASET = "uk.derived.geo"
