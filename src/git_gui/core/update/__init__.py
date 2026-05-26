"""应用更新：GitHub Release 检测与跨平台安装。"""
from .release_checker import UpdateOffer, check_for_update, check_for_update_safe
from .update_controller import UpdateController

__all__ = ["UpdateOffer", "check_for_update", "check_for_update_safe", "UpdateController"]
