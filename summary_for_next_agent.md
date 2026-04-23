# Context & Progress cho Agent tiếp theo

Dự án này là **Autonomous Content Bridge (Video Hermes)**, sử dụng Hermes Agent để thực hiện các quy trình tự động trên các video TikTok (tải xuống, dịch thuật, tạo lồng tiếng, đăng X). 

## Những việc agent trước (vừa rồi) đã làm:

### 1. Tính năng AI Cover Video Pipeline
- Đã thêm thành công luồng tự động tạo Cover Video bằng AI cho các video.
- Đã khai báo 3 công cụ (tools) mới cho Hermes Agent trong file `backend/agent/tools.py`:
  - `rewrite_script`: Sử dụng LLM để viết lại kịch bản sáng tạo từ tóm tắt video.
  - `generate_scene_images`: Gọi API `fal.ai` (mô hình FLUX) để tạo hình ảnh từ kịch bản mới.
  - `compose_cover_video`: Sử dụng FFmpeg tạo video slideshow có hiệu ứng Ken Burns từ các ảnh AI.
- Đã cập nhật `models.py` và `database.py` để lưu 3 trường dữ liệu mới: `cover_path`, `ai_scenes_path`, `script_json`.
- Đã mở endpoint `POST /api/jobs/{id}/generate-cover` trong `backend/api/jobs.py` để trigger pipeline khởi tạo cover.

### 2. Frontend / Giao diện người dùng
- Đã sửa thành công lỗi syntax (JSX error: Extra `</div>`) trong file `frontend/app/page.tsx`. Frontend đã build `npm run dev` thành công mà không còn lỗi.
- Đã thêm UI cho AI Cover Video:
  - Nút **"🎬 Generate Cover"** sẽ xuất hiện khi trạng thái video đã hoàn thành (`completed`).
  - Đã thêm bộ sưu tập ảnh (AI Scene Gallery) để preview ngay trên màn hình dashboard các ảnh FLUX được tạo ra.
  - Tích hợp thêm AI Cover Video Player phía cạnh video gốc.
- Đã cập nhật `frontend/app/settings/page.tsx` và `backend/api/settings.py` để hỗ trợ lưu trữ API key của `fal.ai` (`fal_api_key`).

### 3. Setup chạy Local để test
- Đã thiết lập môi trường Cài đặt Local trên Windows cho backend:
  - Backend sử dụng Python 3.13. Do có một dependency cũ là `openai-whisper` không tương thích dễ dàng, Agent đã có workaround là: cài đặt `setuptools<70` trước khi cài các module khác để vượt qua lỗi `No module named pkg_resources`.
  - Hầu thết tất cả module đều đã install thành công ngoại trừ đôi lúc gặp lỗi xung đột port. 

## Vấn đề hiện tại (Nhiệm vụ cho agent tiếp theo):
- Người dùng hiện đang muốn **thử tải chạy server trực tiếp ở môi trường Local (thay vì VPS)**.
- Gần đây nhất, khi chạy `py -m uvicorn backend.main:app --port 8000`, hệ điều hành báo lỗi **[Errno 10048] address already bound (Cổng 8000 đang bị chiếm)** vì trước đó server uvicorn đã bị chạy ngầm nhưng chưa kết thúc triệt để.
- **Tiếp tục với:**
  1. Kill các process Python đang chiếm localhost `8000` và Node.js đang chiếm localhost `3000`.
  2. Bật lại Backend API (`cd content-bridge && py -m uvicorn backend.main:app --reload --port 8000`).
  3. Bật lại Frontend Nextjs (`cd content-bridge/frontend && npm run dev --port 3000`).
  4. Mở http://localhost:3000 để người dùng test trực tiếp tính năng "Generate Cover" với link video TikTok mẫu.

*(Mọi source code về AI Cover Generator đã hoàn thiện, chỉ còn thao tác restart server local cho sạch là chạy được).*
