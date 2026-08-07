import asyncio
from printer_module import print_transaction_receipt

async def main():
    print("Testing Printer Module with New 'Dua Pharmacy' Layout...")
    
    test_data = {
        "timestamp": "2026-08-06 23:15:00",
        "customer_type": "Walk in Customer",
        "transaction_id": "TEST-7890",
        "cashier_name": "Shayan",
        "items": [
            {
                "name": "Panadol 500mg",
                "price": 25.00,
                "discount": 5.00,
                "discount_price": 20.00,
                "quantity": 2,
                "total": 40.00
            },
            {
                "name": "Surbex Z",
                "price": 450.00,
                "discount": 0.00,
                "discount_price": 450.00,
                "quantity": 1,
                "total": 450.00
            }
        ],
        "total": 490.00,
        "paid_by": "Cash",
        "received_amount": 500.00,
        "change_amount": 10.00
    }
    
    print("\nSending test print job...")
    success = await print_transaction_receipt(test_data)
    
    if success:
        print("\n[SUCCESS] Print job was sent successfully! Check your emulator.")
    else:
        print("\n[FAILED] Print job failed. Check the logs.")

if __name__ == "__main__":
    asyncio.run(main())
