# Hướng dẫn demo Social Content Agent

Tài liệu này dùng cho một video khoảng 5–7 phút. Kịch bản gọi AI thật nhưng chỉ
`dry-run` phần đăng bài, vì vậy không tạo bài Facebook/Threads ngoài hệ thống.

## 1. Mở app bằng database demo riêng

Mở PowerShell tại thư mục project:

```powershell
cd D:\Fantek_material\AI_AgentSystem\Content_Agent_System
$env:CONTENT_AGENT_DB = "$PWD\artifacts\demo_video_20260725.sqlite3"
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Mở `http://localhost:8501`. Nếu quay lại nhiều lần, đổi tên
`demo_video_20260725.sqlite3` để có màn hình sạch mà không phải xóa dữ liệu cũ.

## 2. Kiểm tra ba kết nối AI

1. Mở **🔑 Kết nối AI** ở sidebar.
2. Nếu key đã nằm trong `.env`/Streamlit Secrets, để trống cả ba ô. App sẽ hiện
   `Key mặc định hệ thống đang hoạt động`.
3. Nếu muốn thay key tạm thời, dán vào ô tương ứng. Key nhập tay chỉ ghi đè
   trong phiên trình duyệt và không được lưu vào Markdown/SQLite.
4. Bấm **Kiểm tra 3 kết nối**.
5. Chỉ tiếp tục khi Gemini Research, Groq Copywriter và GitHub Models Critic đều
   hiện `ready`.

Không mở file `.env` trong lúc quay và không đọc key thành tiếng.

## 3. Tạo content mới chỉ bằng prompt

Mở **1 · Create content**, giữ chế độ **✨ Tạo mới từ prompt** và nhập:

- **Kênh & phong cách:** `responsible-ai-lab`
- **Chủ đề / Topic:** `Pre-publish checks for AI-assisted social content`
- **Mục tiêu bài viết:** `Chia sẻ kiến thức / hướng dẫn`
- **Bạn muốn AI viết bài như thế nào?:**

```text
Write a practical three-step post about the topic and end with one question for small-team leaders.
```

- **Pipeline:** `Full`

Bấm **✨ Tạo bài bằng AI**. Bình thường flow mất khoảng 30–90 giây:

```text
Gemini Research → Groq Copywriter → rule Critic → GitHub Models Critic
                                      ↓ nếu chưa đạt
                               rewrite tối đa 2 lần
```

Kết quả mong đợi:

- có bài viết sinh ra;
- có Critic score và workflow state;
- có Run ID, Request ID và Draft ID;
- state chuyển sang `human_review`;
- phần “View the exact input” vẫn giữ đúng topic và prompt người dùng.

Nút tạo bài không đăng bài ra Meta.

Muốn demo nguồn có sẵn, chuyển sang **📄 Biến nội dung có sẵn thành bài đăng**,
chọn chuyển thể/viết lại/tóm tắt, rồi dán text hoặc upload `.md/.txt`.

## 4. Duyệt bài và kiểm tra phản hồi Approve

Mở **2 · Review & approve**:

1. Chọn run vừa tạo.
2. Cho camera thấy Post preview, Critic score, threshold, violations,
   suggestions và số lần rewrite.
3. Có thể mở tab **Edit** để chỉ ra hệ thống tạo revision mới và vẫn yêu cầu
   duyệt lại; trong video ngắn thì không cần lưu edit.
4. Quay lại tab **Approve**.
5. **Operator:** tên hoặc email của người duyệt.
6. **Approval note:**

```text
Checked the final content, factual claims, tone, CTA, and account-policy constraints.
```

7. Bấm **Approve and move to Publish**.

Sau khi bấm, app phải hiện panel xác nhận gồm:

- `Approved successfully`;
- action `approve`;
- new state `approved`;
- Run ID, Draft ID và operator;
- hướng dẫn bước kế tiếp và lệnh CLI dry-run.

Đây là phần nên quay rõ để chứng minh nút Approve có phản hồi và audit.

## 5. Dry-run phần đăng bài

Mở **3 · Publish**:

1. Chọn approved post vừa duyệt.
2. Kiểm tra preview và destination.
3. Bấm **Run publishing dry-run**.
4. Cho camera thấy `Publish result: dry_run` và bảng Delivery receipts.

Dry-run không đọc Meta token, không gọi Meta và không tạo bài thật. Khu vực live
bị khóa nếu policy vẫn dùng target ID mẫu; muốn live phải đồng thời xác nhận,
gõ `PUBLISH`, thay ID thật và có token hợp lệ.

## 6. Chứng minh audit, token và SQLite

Mở **5 · Analytics**:

1. **Run history:** chọn run và mở Events, Revisions, Critics, Reviews,
   Publishing, Artifacts.
2. **Scores:** cho thấy score theo bài/account.
3. **Usage:** cho thấy token, request và retry theo provider/model.
4. **Data transfer:** tải **Download prepared unique snapshot**.

Tên snapshot có timestamp và chuỗi ngẫu nhiên để không đè file cũ. App dùng một
database vận hành chính, còn thư mục snapshot chỉ giữ tối đa 20 bản gần nhất;
không tạo 20 database vận hành cạnh tranh nhau.

## 7. Nói ngắn về kênh, cấu hình nâng cao và Threads community tag

Mở **4 · Accounts & policies → Kênh hiện có**, chọn
`responsible-ai-lab`. Giải thích:

- người dùng có thể tạo account bằng tab **Tạo kênh bằng form**, không cần biết
  Markdown;
- phía sau, mỗi account vẫn là một file `.md` để thêm/xóa mà không sửa Python;
- Markdown giữ audience, tone, constraints, rubric, model route và đích đăng;
- API key/token không nằm trong Markdown;
- Threads policy có `topic_tag`, `topic_tag_candidates` và `trend_search`;
- khi live và có quyền `threads_keyword_search`, hệ thống so sánh các tag ứng
  viên trong niche rồi lưu tag được chọn vào delivery receipt.

Facebook trong project là Facebook Page qua API chính thức. Hệ thống không tự
đăng bằng mật khẩu/cookie của tài khoản cá nhân hoặc acc clone.

## 8. Lệnh kiểm tra dự phòng trước khi quay

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
python run.py --list-accounts
```

Kết quả release hiện tại: 112 test pass, lint/format/compile/dependency sạch và
package `0.7.0` build được.
