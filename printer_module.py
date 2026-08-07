import asyncio
import logging
from datetime import datetime
import os
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from escpos.printer import Usb, Network
from escpos.exceptions import Error as EscposError

logger = logging.getLogger(__name__)

# ==========================================
# PRINTER CONFIGURATION
# ==========================================
# Set to True to use the local network emulator on port 9100 instead of USB hardware
TEST_MODE = True

# Replace these with your actual thermal printer's USB Vendor ID and Product ID.
VENDOR_ID = 0x04b8  # Example: Epson
PRODUCT_ID = 0x0202 # Example: Epson TM-T20II

def _generate_urdu_tc_image() -> str:
    """
    Generates an image containing the Urdu terms and conditions and returns the path to the temp image.
    """
    urdu_text = (
        "بغیر بل کے کوئ چیز تبدیل یا واپس نہین ہوگی\n"
        "فروزن آئٹم کی تبدیلی یا واپسی نہین ہوگی\n"
        "کوئ بہی چیز واپسی یا تبدیلی کرنی ہوتو سات دن کے\n"
        "اندر ہوگی\n"
        "کھلونے اور کراکری کی واپسی یا تبدیلی نہین ہوگی موقع\n"
        "پر چیک کرلین"
    )
    
    # Try to load a font. Use arial as default fallback.
    font_path = "arial.ttf"
    if os.path.exists("Jameel Noori Nastaleeq.ttf"):
        font_path = "Jameel Noori Nastaleeq.ttf"
        
    try:
        font = ImageFont.truetype(font_path, 22)
    except IOError:
        # Fallback to default if arial is missing
        font = ImageFont.load_default()
        
    # Process text for RTL
    lines = urdu_text.split('\n')
    processed_lines = []
    for line in lines:
        reshaped = arabic_reshaper.reshape(line)
        bidi_text = get_display(reshaped)
        processed_lines.append(bidi_text)
        
    # Calculate image height
    line_spacing = 8
    img_width = 512 # Standard 80mm width in dots (approx)
    
    # We need a dummy draw object to measure text accurately
    dummy_img = Image.new('RGB', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    
    # Measure line heights
    total_height = 20
    line_heights = []
    for line in processed_lines:
        bbox = dummy_draw.textbbox((0, 0), line, font=font)
        h = bbox[3] - bbox[1]
        line_heights.append(h)
        total_height += h + line_spacing
        
    img = Image.new('RGB', (img_width, total_height), color='white')
    draw = ImageDraw.Draw(img)
    
    y = 10
    for i, line in enumerate(processed_lines):
        # Get text bounding box to center it
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (img_width - text_w) / 2
        draw.text((x, y), line, font=font, fill='black')
        y += line_heights[i] + line_spacing
        
    img_path = "temp_urdu_tc.png"
    img.save(img_path)
    return img_path

def _format_item_line(name, price, disc, dis_price, qty, total):
    """
    Columns: Product(12) | Price(6) | Disc(4) | Dis Price(6) | Qty(3) | Total(7)
    Total width = 12+1+6+1+4+1+6+1+3+1+7 = 42
    """
    name_str = (name[:10] + "..") if len(name) > 12 else name.ljust(12)
    price_str = f"{float(price):.0f}".rjust(6)
    disc_str = f"{float(disc):.0f}".rjust(4)
    dis_price_str = f"{float(dis_price):.0f}".rjust(6)
    qty_str = str(qty).rjust(3)
    total_str = f"{float(total):.0f}".rjust(7)
    
    return f"{name_str} {price_str} {disc_str} {dis_price_str} {qty_str} {total_str}"

def _do_print_receipt(data: dict) -> bool:
    try:
        if TEST_MODE:
            p = Network("localhost", port=9100, profile="TM-T88III")
        else:
            p = Usb(VENDOR_ID, PRODUCT_ID, profile="TM-T88III")
            
        # 1. Header (Logo & Name)
        p.set(align="center")
        if os.path.exists("logo.png"):
            p.image("logo.png")
            
        p.set(align="center", bold=True, double_width=True, double_height=True)
        p.text("Dua Pharmacy\n")
        
        p.set(align="center", bold=False, double_width=False, double_height=False)
        p.text("Main baranch\n")
        p.text("03XX-XXXXXXX\n")
        p.text("-" * 42 + "\n")
        
        # 2. Transaction Meta
        p.set(align="left")
        p.text(f"Date/Time: {data.get('timestamp', '')}\n")
        p.text(f"Customer Type: {data.get('customer_type', 'Walk in Customer')}\n")
        p.text(f"Customer Points: {data.get('transaction_id', '')}\n")
        p.text(f"Cashier Name: {data.get('cashier_name', 'ABC')}\n")
        p.text("-" * 42 + "\n")
        
        # 3. Itemized List & Subtotals
        p.set(align="left", bold=True)
        p.text("Product      Price  Disc DPrice Qty   Total\n")
        p.set(bold=False)
        
        total_disc = 0
        total_qty = 0
        
        for item in data.get("items", []):
            line = _format_item_line(
                item.get("name", ""),
                item.get("price", 0),
                item.get("discount", 0),
                item.get("discount_price", 0),
                item.get("quantity", 0),
                item.get("total", 0)
            )
            p.text(f"{line}\n")
            total_disc += float(item.get("discount", 0))
            total_qty += int(item.get("quantity", 0))
            
        p.set(align="right")
        p.text("-" * 23 + "\n") # Dashed line under the math columns
        
        # Subtotal line
        disc_str = f"{total_disc:.0f}".rjust(4)
        qty_str = str(total_qty).rjust(3)
        final_total = float(data.get("total", 0))
        tot_str = f"{final_total:.0f}".rjust(7)
        
        # Space alignment: Product(12) + Space(1) + Price(6) + Space(1) = 20
        dprice_empty = "      " # 6 spaces
        subtotal_line = f"{'Subtotal:'.ljust(20)}{disc_str} {dprice_empty} {qty_str} {tot_str}"
        
        p.set(align="left", bold=True)
        p.text(f"{subtotal_line}\n")
        p.set(bold=False)
        p.text("-" * 42 + "\n")
        
        # 4. Payment Details
        p.set(align="center")
        p.text("Paid By:      Rec Amount:         Change:\n")
        
        paid_by = str(data.get("paid_by", "Cash")).center(12)
        rec_amt = str(data.get("received_amount", "0")).center(15)
        change = f"{float(data.get('change_amount', 0)):.2f}".center(13)
        
        p.text(f"{paid_by} {rec_amt} {change}\n")
        p.text("\nThank You\n\n")
        
        # 5. Urdu Terms & Conditions
        tc_img_path = _generate_urdu_tc_image()
        p.set(align="center")
        # Center the image manually by passing center=True if supported, or relying on set(align="center")
        p.image(tc_img_path)
        
        # Clean up temp image
        try:
            os.remove(tc_img_path)
        except OSError:
            pass
        
        # 6. Barcode
        p.text("\n")
        transaction_id = data.get("transaction_id", "")
        if transaction_id:
            barcode_str = "{B" + transaction_id
            p.barcode(barcode_str, "CODE128", width=3, height=64, pos="BELOW", font="a")
            
        p.text("\n\n\n\n")
        p.cut()
        p.close()
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
