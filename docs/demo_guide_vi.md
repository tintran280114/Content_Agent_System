# Demo guide — Social Content Agent Studio

Kịch bản này dùng `dry-run` để chứng minh full flow mà không tạo bài thật.
Hướng dẫn setup Facebook/Threads chi tiết nằm trong
[user journey](user_journey_vi.md).

## 1. Chuẩn bị

```powershell
cd D:\Fantek_material\AI_AgentSystem\Content_Agent_System
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Trong sidebar:

1. Nhập tên operator.
2. Mở **Kết nối AI** và bấm **Kiểm tra 3 kết nối**.
3. Mở **Facebook & Threads** và show trạng thái credential.

## 2. Tạo bài bằng một file Markdown

Mở **1 · Create content**:

1. Tải **template Generate**.
2. Sửa `# Topic`, `# Instructions` và tùy chọn `# Source`.
3. Chọn channel.
4. Upload file `.md`.
5. Show parser preview: mode, task, pipeline, block types và topic.
6. Bấm **Chạy content Markdown**.

App chạy Research → Copywriter → hard-rule Critic → LLM Critic. Show result,
score, Run ID, Request ID và Draft ID.

Để chứng minh không bắt buộc dùng AI, upload **template Publish** với
`mode: publish`. App nhập bài hoàn chỉnh vào workflow và usage AI bằng zero.

## 3. Review và approve

Mở **2 · Review & approve**:

1. Chọn run.
2. Show original Markdown request, current post, score và violations.
3. Nhập operator và approval note.
4. Bấm **Approve and move to Publish**.
5. Show result panel: action, state, Run ID, Draft ID và operator.

## 4. Publish

Mở **3 · Publish**:

1. Chọn approved post.
2. Kiểm tra preview, destination và credential reference.
3. Bấm **Run publishing dry-run**.
4. Show `Publish result: dry_run` và Delivery receipts.

Dry-run không đọc Meta token và không gọi Meta. Nếu quay live demo, thay target
ID thật, có Page/Threads token hợp lệ rồi bấm **Publish live now**. Không còn
checkbox hoặc ô nhập chuỗi `PUBLISH`; một click gửi ngay, trong khi backend vẫn
kiểm tra state, permission, credential, target và idempotency.

## 5. Threads

Trong sidebar **Facebook & Threads**:

1. Show Threads App ID/Redirect URI.
2. Bấm **Đăng nhập và cấp quyền Threads**.
3. Sau redirect, exchange authorization code.
4. Show User ID, expiry và encrypted-store status.
5. Giải thích app tự refresh long-lived token trong bảy ngày trước hạn.
6. Trong account policy, show `topic_tag_candidates` và `trend_search`.

## 6. Audit

Mở **5 · Analytics**:

- Run history: input mode, state và terminal error.
- Score history: policy/account score.
- Tokens & quota: provider/model/request/retry.
- Data transfer: SQLite snapshot có tên timestamp + random suffix; tối đa 20
  snapshot local.

## 7. Câu kết video

“Một content Markdown đi xuyên suốt từ input tới audit. AI generation và manual
publish-ready content dùng chung policy/review/publisher. Nút Publish không còn
typed confirmation, nhưng tất cả backend guard vẫn còn. Facebook Page chạy bằng
Page Token; Threads có OAuth, encrypted token rotation và trend-aware topic
tag.”
