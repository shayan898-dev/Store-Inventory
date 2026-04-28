"""
barcode_scanner.py
------------------
Camera-based barcode / QR-code scanner for Inventory Manager Pro.

Decoder stack (zero external DLL dependencies):
  Primary  : zxing-cpp  — supports ALL barcode types (EAN, UPC, Code39/128,
             QR, DataMatrix, PDF417, Aztec, ITF, …)  Statically linked.
  Fallback : cv2.QRCodeDetector  — QR-only backup if zxingcpp unavailable

Image pre-processing pipeline (maximises detection in poor light):
  1. Raw colour frame
  2. Greyscale
  3. CLAHE-equalised greyscale   (improves low-contrast barcodes)
  4. Adaptive-threshold binary   (helps blurry / high-glare barcodes)

Each frame is tried against all four variants in order.  First hit wins.

Usage
-----
    scanner = BarcodeScanner()
    scanner.scan_async(
        on_found  = lambda code: process(code),
        on_cancel = lambda:      restore_ui(),
        on_error  = lambda msg:  show_error(msg),
        app       = self,          # CTk root for thread-safe after()
    )
    scanner.stop()   # cancel mid-session
"""

import threading
import cv2
import numpy as np

# ------------------------------------------------------------------ #
#  zxing-cpp lazy loader                                               #
# ------------------------------------------------------------------ #

_zxing_read = None   # cached reference to zxingcpp.read_barcodes


def _load_zxing():
    global _zxing_read
    if _zxing_read is not None:
        return _zxing_read
    try:
        import zxingcpp
        _zxing_read = zxingcpp.read_barcodes
        return _zxing_read
    except Exception:
        return None


# ------------------------------------------------------------------ #
#  Image pre-processing helpers                                        #
# ------------------------------------------------------------------ #

def _preprocess_variants(frame):
    """
    Returns a list of image variants to try decoding.
    Each variant increases the chance of detecting a difficult barcode.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # CLAHE — boosts local contrast (great for dim/uneven lighting)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    eq    = clahe.apply(gray)

    # Adaptive threshold — produces clean binary for blurry barcodes
    thr   = cv2.adaptiveThreshold(
        eq, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 15, 8
    )

    # Sharpened — helps soft-focus webcams
    kernel  = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharp   = cv2.filter2D(gray, -1, kernel)

    return [frame, gray, eq, thr, sharp]


# ------------------------------------------------------------------ #
#  Overlay helpers                                                     #
# ------------------------------------------------------------------ #

_GREEN = (0, 220, 80)
_RED   = (50, 50, 220)
_FONT  = cv2.FONT_HERSHEY_SIMPLEX


def _draw_viewfinder(frame):
    h, w = frame.shape[:2]
    x1, y1 = w // 4, h // 4
    x2, y2 = 3 * w // 4, 3 * h // 4
    cv2.rectangle(frame, (x1, y1), (x2, y2), _GREEN, 2)
    tick = 22
    for px, py, dx, dy in [
        (x1, y1,  1,  1), (x2, y1, -1,  1),
        (x1, y2,  1, -1), (x2, y2, -1, -1),
    ]:
        cv2.line(frame, (px, py), (px + dx * tick, py), _GREEN, 3)
        cv2.line(frame, (px, py), (px, py + dy * tick), _GREEN, 3)


def _label(frame, text, y=30, color=_GREEN):
    cv2.putText(frame, text, (10, y), _FONT, 0.62, color, 2, cv2.LINE_AA)


def _draw_barcode_box(frame, result):
    """Draw the bounding box of a detected barcode from a zxingcpp Result."""
    try:
        pos   = result.position
        pts   = np.array(
            [[pos.top_left.x,     pos.top_left.y],
             [pos.top_right.x,    pos.top_right.y],
             [pos.bottom_right.x, pos.bottom_right.y],
             [pos.bottom_left.x,  pos.bottom_left.y]],
            dtype=np.int32,
        )
        cv2.polylines(frame, [pts], True, _RED, 3)
    except Exception:
        pass


# ------------------------------------------------------------------ #
#  BarcodeScanner                                                      #
# ------------------------------------------------------------------ #

class BarcodeScanner:
    """
    One-shot camera scanning session.

    Lifecycle
    ---------
    scan_async() → background thread opens camera → decode loop
    → on first successful decode → camera released → on_found(code) called
    → user presses Q/ESC → camera released → on_cancel() called
    → camera fails to open → on_error(msg) called
    """

    WINDOW_TITLE = "Inventory Manager Pro — Barcode Scanner"

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self._running     = False
        self._thread: threading.Thread | None = None
        self._app         = None

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def scan_async(self, *, on_found, on_cancel=None, on_error=None, app=None):
        if self._running:
            return
        self._running = True
        self._app     = app
        self._thread  = threading.Thread(
            target = self._worker,
            args   = (on_found, on_cancel, on_error),
            daemon = True,
            name   = "BarcodeScannerThread",
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def is_running(self) -> bool:
        return self._running

    # ----------------------------------------------------------------
    # Thread-safe callback dispatcher
    # ----------------------------------------------------------------

    def _post(self, fn):
        if self._app:
            self._app.after(0, fn)
        else:
            fn()

    # ----------------------------------------------------------------
    # Core decode — tries every preprocessing variant until a hit
    # ----------------------------------------------------------------

    def _decode(self, frame):
        """
        Returns (barcode_string, result_obj_or_None).

        Tries zxingcpp first (all barcode types, best detection).
        Falls back to cv2.QRCodeDetector for QR codes.
        """
        read_barcodes = _load_zxing()

        variants = _preprocess_variants(frame)

        # ── zxing-cpp ────────────────────────────────────────────────
        if read_barcodes:
            for img in variants:
                try:
                    results = read_barcodes(img)
                    for r in results:
                        text = (r.text or "").strip()
                        if len(text) >= 2:
                            return text, r
                except Exception:
                    continue

        # ── cv2.QRCodeDetector fallback ──────────────────────────────
        try:
            qrd = cv2.QRCodeDetector()
            for img in variants[:3]:   # raw, gray, equalized
                data, pts, _ = qrd.detectAndDecode(img)
                data = (data or "").strip()
                if len(data) >= 2:
                    return data, None
        except Exception:
            pass

        return None, None

    # ----------------------------------------------------------------
    # Background worker
    # ----------------------------------------------------------------

    def _worker(self, on_found, on_cancel, on_error):
        cap        = None
        found_code = None

        try:
            # ── Open camera ──────────────────────────────────────────
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.camera_index)

            if not cap.isOpened():
                self._running = False
                if on_error:
                    self._post(lambda: on_error(
                        "Camera not found.\n\n"
                        "Make sure a webcam is connected and not in use by\n"
                        "another app (Teams, Zoom, Skype, etc.)."
                    ))
                return

            # Prefer 1280×720 for better barcode resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            decoder_label = "zxing-cpp" if _load_zxing() else "OpenCV QR"

            # ── Frame loop ───────────────────────────────────────────
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    continue

                # Draw overlay on a copy so preprocessing isn't affected
                display = frame.copy()
                _draw_viewfinder(display)
                _label(display,
                    f"Aim at barcode  [{decoder_label}]   Q/ESC = Cancel",
                    y=28, color=_GREEN)

                code, result = self._decode(frame)

                if code:
                    # Show confirmed detection on screen briefly
                    if result:
                        _draw_barcode_box(display, result)
                    _label(display, f"FOUND: {code}", y=60, color=_RED)
                    cv2.imshow(self.WINDOW_TITLE, display)
                    cv2.waitKey(450)
                    found_code    = code
                    self._running = False
                    break

                cv2.imshow(self.WINDOW_TITLE, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    self._running = False
                    break

        except Exception as exc:
            msg = str(exc)
            if on_error:
                self._post(lambda m=msg: on_error(m))
        finally:
            if cap:
                cap.release()
            cv2.destroyAllWindows()
            self._running = False

            if found_code:
                code = found_code
                self._post(lambda c=code: on_found(c))
            elif on_cancel:
                self._post(on_cancel)


# ------------------------------------------------------------------ #
#  Standalone test  (python barcode_scanner.py)                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    print("BarcodeScanner test — press Q to cancel.")
    print(f"zxing-cpp available: {_load_zxing() is not None}")

    def on_found(code):
        print(f"Scanned: {code}")

    def on_cancel():
        print("Cancelled.")

    def on_error(msg):
        print(f"Error: {msg}")

    s = BarcodeScanner()
    s.scan_async(on_found=on_found, on_cancel=on_cancel, on_error=on_error)
    s._thread.join()
