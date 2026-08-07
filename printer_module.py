import asyncio
import logging
from datetime import datetime

from escpos.printer import Usb, Network, Win32Raw
from escpos.exceptions import Error as EscposError

def _find_windows_printer():
    try:
        import win32print
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)
        keywords = ["pos", "receipt", "thermal", "xp-", "tm-", "80mm", "58mm", "printer"]
        for printer_info in printers:
            name = printer_info[2]
            if any(k in name.lower() for k in keywords):
                return name
        return None
    except ImportError:
        return None

logger = logging.getLogger(__name__)

# ==========================================
# PRINTER CONFIGURATION
# ==========================================
# Set to True to use the local network emulator on port 9100 instead of USB hardware
TEST_MODE = False

# Replace these with your actual thermal printer's USB Vendor ID and Product ID.
VENDOR_ID = 0x04b8  
PRODUCT_ID = 0x0202 

def _do_print_receipt(data: dict) -> bool:
    try:
        is_test_mode = data.get("test_mode", TEST_MODE)
        if is_test_mode:
            printer = Network("127.0.0.1", port=9100, profile="TM-T88III")
        else:
            win_printer_name = _find_windows_printer()
            if win_printer_name:
                logger.info(f"Auto-detected Windows printer: {win_printer_name}")
                printer = Win32Raw(win_printer_name)
            else:
                logger.info("Falling back to direct USB connection.")
                printer = Usb(VENDOR_ID, PRODUCT_ID, profile="TM-T88III")
            
        # Extract variables from data dictionary to match the new structure
        transaction_id = data.get("transaction_id", "")
        items = data.get("items", [])
        paid_by = data.get("paid_by", "Cash")
        rec_amount = float(data.get("received_amount", 0.0))
        change = float(data.get("change_amount", 0.0))
        customer_id = transaction_id  # Using transaction_id as customer_id for barcode per user prompt
        
        # 1. Header (Logo & Name)
        printer.set(align='center')
        # printer.image("logo.png") # Uncomment and ensure the path to our logo is correct
        
        printer.set(align='center', bold=True, double_width=True, double_height=True)
        printer.text("Dua Pharmacy\n")
        
        printer.set(align='center', bold=False, double_width=False, double_height=False)
        printer.text("Main baranch\n")
        printer.text("03XX-XXXXXXX\n\n")

        # 2. Transaction Meta
        printer.set(align='left')
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        printer.text(f"Date/Time: {current_time}\n")
        printer.text("Customer Type: Walk in Customer\n")
        printer.text(f"Customer Points: {transaction_id}\n")
        printer.text(f"Cashier Name: {data.get('cashier_name', 'ABC')}\n\n")

        # 3. Itemized List & Subtotals
        # 80mm paper = exactly 48 characters per line
        header_format = "{:<14} {:>6} {:>5} {:>8} {:>4} {:>7}\n"
        printer.text(header_format.format("Product", "Price", "Disc", "DisPrice", "Qty", "Total"))
        printer.text("-" * 48 + "\n")

        total_disc = 0
        total_qty = 0
        grand_total = 0

        for item in items:
            # Truncate product name to 14 chars to prevent line wrapping
            prod = str(item.get('name', ''))[:14]
            price = f"{float(item.get('price', 0)):.2f}"
            
            disc_val = float(item.get('discount', 0))
            disc = f"{disc_val:.0f}"
            
            dis_price_val = float(item.get('discount_price', 0))
            dis_price = f"{dis_price_val:.2f}"
            
            qty_val = int(item.get('quantity', 0))
            qty = f"{qty_val}"
            
            total_val = float(item.get('total', 0))
            total = f"{total_val:.2f}"

            total_disc += disc_val
            total_qty += qty_val
            grand_total += total_val

            printer.text(header_format.format(prod, price, disc, dis_price, qty, total))

        printer.set(align='right')
        printer.text("-" * 30 + "\n")

        printer.set(align='left')
        subtotal_line = header_format.format(
            "SUBTOTAL", "", f"{total_disc:.0f}", "", f"{total_qty}", f"{grand_total:.2f}"
        )
        printer.text(subtotal_line)
        
        printer.set(align='right')
        printer.text("-" * 30 + "\n\n")

        # 4. Payment Details
        printer.set(align='center')
        payment_format = "{:^16}{:^16}{:^16}\n"
        printer.text(payment_format.format("Paid By:", "Rec Amount:", "Change:"))
        printer.text(payment_format.format(str(paid_by), f"{rec_amount:.2f}", f"{change:.2f}"))
        printer.text("\n")

        # 5. Terms & Conditions
        printer.set(align='left')
        printer.text("-" * 48 + "\n")
        printer.text("No items will be exchanged or returned without a receipt.\n")
        printer.text("Frozen items cannot be exchanged or returned.\n")
        printer.text("Any exchange or return must be made within seven days.\n")
        printer.text("Toys and crockery are not eligible for return or exchange;\n")
        printer.text("please check them on the spot.\n")
        printer.text("-" * 48 + "\n\n")
        
        printer.set(align='center')
        printer.text("Thank You\n\n")

        # 6. Barcode
        printer.text("\n")
        
        # We ensure it complies with python-escpos syntax
        try:
            # python-escpos typically expects the subset to be defined in the string for CODE128
            printer.barcode("{B" + str(customer_id), 'CODE128', width=3, height=64, pos="BELOW")
        except Exception as e:
            logger.warning(f"Barcode warning: {e}. Trying fallback.")
            printer.barcode(str(customer_id), 'CODE128', width=3, height=64, pos="BELOW")
            
        printer.text("\n\n\n")
        printer.cut()
        printer.close()
        
        return True
        
    except EscposError as e:
        logger.error(f"ESC/POS Printer Error: {e}")
        return False
    except ValueError as e:
        logger.error(f"USB Error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during printing: {e}")
        return False

async def print_transaction_receipt(data: dict) -> bool:
    try:
        result = await asyncio.to_thread(_do_print_receipt, data)
        return result
    except Exception as e:
        logger.error(f"Async wrapper error: {e}")
        return False
