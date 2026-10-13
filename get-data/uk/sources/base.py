from __future__ import annotations

import argparse

from common.release import Release

MARKET = "uk"


class Source:
    """Một tool cào dữ liệu. Lớp con khai báo name/dataset_id và viết plan() + download().

    plan()     : xác định phiên bản mới nhất (rẻ, không tải file lớn) → trả về Release.
    download() : tải file vào release.dir bằng release.download(...) / release.add_file(...).
    """

    name: str = ""
    dataset_id: str = ""
    description: str = ""

    def add_arguments(self, p: argparse.ArgumentParser) -> None:
        pass

    def plan(self, args: argparse.Namespace) -> Release:
        raise NotImplementedError

    def download(self, rel: Release, args: argparse.Namespace) -> None:
        raise NotImplementedError

    def release(self, version: str, **kw) -> Release:
        return Release(MARKET, self.name, self.dataset_id, version, **kw)
