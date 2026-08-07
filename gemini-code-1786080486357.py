import socket

with open("receipt_output.bin", "rb") as file:
    receipt_data = file.read()
    print(f"Read {len(receipt_data)} bytes from file.")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect(("localhost", 9100))
    s.sendall(receipt_data)
    print("Data successfully sent to port 9100! Check http://localhost:3000")