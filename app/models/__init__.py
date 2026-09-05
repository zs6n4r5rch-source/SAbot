from app.models.base import (
    Base,
    UserRole,
    Club,
    Employee,
    EmployeeClub,
    TelegramUser,
    AccessProfile,
    TelegramBindingRequest,
    Shift,
    ShiftStatus,
    ProductCategory,
    Product,
    Inventory,
    InventoryItem,
    InventoryBalance,
    InventoryOperation,
    InventoryOperationType,
    InventoryStatus,
    StockSnapshot,
    Writeoff,
    WriteoffItem,
    WriteoffStatus,
    WriteoffReason,
    Discrepancy,
    DiscrepancyStatus,
    AuditLog,
    LangameSyncLog,
)
from app.models.owner import Guest, GuestTelegram, OwnerDailyReportDelivery, OwnerReportSettings

_SALARY_EXPORTS = {
    "ShiftCloseReport",
    "ShiftCloseReportStatus",
    "ShiftCloseStockItem",
    "SalaryRule",
    "SalaryPeriod",
    "SalaryAdjustment",
    "SalaryViolation",
    "SalaryPayment",
    "NonMonetaryBonus",
}


def __getattr__(name):
    if name in _SALARY_EXPORTS:
        from app.models import salary
        return getattr(salary, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Base", "UserRole", "Club", "Employee", "EmployeeClub", "TelegramUser",
    "AccessProfile", "TelegramBindingRequest", "Shift", "ShiftStatus",
    "ProductCategory", "Product", "Inventory", "InventoryItem", "InventoryBalance",
    "InventoryOperation", "InventoryOperationType", "InventoryStatus", "StockSnapshot",
    "Writeoff", "WriteoffItem", "WriteoffStatus", "WriteoffReason", "Discrepancy",
    "DiscrepancyStatus", "AuditLog", "LangameSyncLog",
    "Guest", "GuestTelegram", "OwnerDailyReportDelivery", "OwnerReportSettings",
    "ShiftCloseReport", "ShiftCloseReportStatus", "ShiftCloseStockItem",
    "SalaryRule", "SalaryPeriod", "SalaryAdjustment", "SalaryViolation", "SalaryPayment",
    "NonMonetaryBonus",
]
