<img src="tools/icon-preview.png" width="96" align="right">

# Radio VN

App nghe radio Việt Nam (VOV, VOH, Đài Hà Nội...) qua WiFi cho máy chơi game **Anbernic RG40XXV** chạy **muOS**.

- Danh sách kênh, kênh đang phát được tô xanh, có vòng xoay khi đang kết nối
- Chỉ đổi kênh khi bấm A, bấm nhanh liên tục không làm treo app
- Tự kết nối lại khi rớt mạng, nhớ kênh nghe gần nhất
- Tắt màn hình để tiết kiệm pin trong khi vẫn nghe
- Nghe qua loa, tai nghe 3.5mm hoặc Bluetooth

## Cài đặt

1. Tắt máy, cắm thẻ nhớ muOS vào máy tính.
2. Chép thư mục này vào `MUOS/application/RadioVN/` trên thẻ (đường dẫn đúng: `MUOS/application/RadioVN/mux_launch.sh`). Thư mục `tools/` chỉ dùng trên máy tính, không cần chép.
3. Bật máy, kết nối WiFi, vào **Applications → Radio VN**.

## Nút bấm

| Nút | Chức năng |
| --- | --- |
| Lên / Xuống | Chọn kênh (chưa đổi kênh) |
| L1 / R1 | Lật trang danh sách |
| A | Nghe kênh đang chọn |
| B | Nhảy về kênh đang phát |
| X | Dừng / phát tiếp |
| Trái / Phải | Âm lượng |
| Y | Tắt màn hình (bấm nút bất kỳ để bật lại) |
| Menu + Start | Thoát |

## Thêm / sửa kênh

Sửa file [`kenh.m3u`](kenh.m3u), mỗi kênh 2 dòng:

```
#EXTINF:-1,Tên kênh - Mô tả
https://link-phat-cua-kenh
```

Lưu với mã UTF-8. Link dự phòng của VOV có sẵn trong phần ghi chú đầu file.

## Cách hoạt động

- `mux_launch.sh`: script muOS gọi khi mở app, chuẩn bị môi trường rồi chạy `radiovn.py`.
- `radiovn.py`: vẽ giao diện (gửi lệnh `osd-overlay` cho mpv qua socket IPC), đọc nút bấm trực tiếp từ `/dev/input` và điều khiển phát.
- `mpv/`: cấu hình mpv và font tiếng Việt. Bản mpv 0.35 của muOS không có Lua nên mọi logic nằm trong Python.
- Nếu `radiovn.py` lỗi, app tự chuyển sang chế độ đơn giản (mpv tự phát danh sách kênh) để vẫn nghe được.

Khi gặp lỗi, xem `radiovn.log`, `radiovn-ui.log`, `mpv.log` trong thư mục app trên thẻ nhớ.

## Công cụ trên máy tính

- `python tools/preview.py`: xuất các màn hình giao diện ra `tools/preview/*.svg` để xem trước.
- `python tools/make_icons.py <thư mục>`: vẽ lại icon PNG.

## Bản quyền

- Font [Be Vietnam Pro](https://github.com/bettergui/BeVietnamPro) theo giấy phép SIL Open Font License (`mpv/fonts/OFL-BeVietnamPro.txt`).
- Các luồng radio thuộc về đài phát thanh tương ứng; app chỉ phát lại link công khai trên website của đài.
