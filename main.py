import threading
import time

def task(name):
    print(f"Bắt đầu công việc: {name}")
    time.sleep(3)  # Giả lập công việc tốn 3 giây
    print(f"Hoàn thành công việc: {name}")

# Tạo một thread
t = threading.Thread(target=task, args=("Tải dữ liệu",))

# Khởi chạy thread
t.start()

print("Chương trình chính vẫn tiếp tục chạy mà không bị chờ...")
