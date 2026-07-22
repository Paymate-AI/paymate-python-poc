from sqlite3 import IntegrityError

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.payment_service import PaymentService
from models.payment import Payment


@pytest.mark.asyncio
async def test_generate_payment_virtual_account_rolls_back_and_raises_on_db_error(monkeypatch):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(first=MagicMock(return_value=MagicMock(
        id=1,
        order_id=1,
        amount=1000,
        reference='ref-1',
        transaction_id=None,
    )))))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    service = PaymentService(db)

    async def fake_generate_virtual_account(**kwargs):
        return {"account_number": "123", "bank_name": "Test Bank", "transaction_id": "txn-1", "expiry_minutes": 60}

    monkeypatch.setattr("services.payment_service.ALATPayService.generate_virtual_account", fake_generate_virtual_account)

    db.add.side_effect = IntegrityError("boom")

    with pytest.raises(Exception):
        await service.generate_payment_virtual_account(1, "whatsapp")

    db.rollback.assert_awaited()
