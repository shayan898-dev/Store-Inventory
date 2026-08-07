import socket

# Raw ESC/POS bytes for "Test Receipt" + 5 blank lines + Paper Cut
test_data = b"Test Receipt Works!\n\n\n\n\n\x1d\x56\x00"

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect(("localhost", 9100))
    s.sendall(test_data)
    print("Test sent!")