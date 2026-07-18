import argparse
import sys
from pathlib import Path

from sqlalchemy import or_, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.config import SessionLocal
from models.payment import Payment


def get_payments_without_transaction_id():
    with SessionLocal() as session:
        return session.scalars(
            select(Payment)
            .where(or_(Payment.transaction_id.is_(None), Payment.transaction_id == ""))
            .order_by(Payment.id)
        ).all()


def delete_payments_without_transaction_id():
    with SessionLocal() as session:
        payments = session.scalars(
            select(Payment)
            .where(or_(Payment.transaction_id.is_(None), Payment.transaction_id == ""))
            .order_by(Payment.id)
        ).all()

        if not payments:
            return 0

        for payment in payments:
            if payment.virtual_account is not None:
                session.delete(payment.virtual_account)
            session.delete(payment)

        session.commit()
        return len(payments)


def main():
    parser = argparse.ArgumentParser(
        description="List or delete payments that do not have a transaction_id"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matching payments without deleting them",
    )
    args = parser.parse_args()

    payments = get_payments_without_transaction_id()

    if not payments:
        print("No payments without a transaction ID were found.")
        return

    print(f"Found {len(payments)} payments without a transaction ID:")
    for payment in payments:
        print(
            f"- payment_id={payment.id}, order_id={payment.order_id}, "
            f"reference={payment.reference}, status={payment.status}"
        )

    if args.dry_run:
        print("Dry run only. No payments were deleted.")
        return

    deleted_count = delete_payments_without_transaction_id()
    print(f"Deleted {deleted_count} payments without a transaction ID.")


if __name__ == "__main__":
    main()
