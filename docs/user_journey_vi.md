# User journey: tạo, duyệt và đăng social content

Tài liệu này mô tả flow hiện tại của hệ thống từ lúc mở app đến khi có bài
Facebook Page hoặc Threads. Người tạo content chỉ làm việc với **một file
Markdown**. Account policy và credential được quản trị riêng.

## 1. Chuẩn bị và chạy app

```powershell
cd D:\Fantek_material\AI_AgentSystem\Content_Agent_System
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run streamlit_app.py
```

Mở `http://localhost:8501`. Trong sidebar:

1. Mở **Kết nối AI**.
2. Để trống các ô nếu `.env` đã có key; nếu không, paste key dùng riêng cho
   browser session hiện tại.
3. Bấm **Kiểm tra 3 kết nối**.
4. Mở **Facebook & Threads** để xem trạng thái social credential.

Key/token nhập trong password field không được ghi vào content Markdown hoặc
SQLite.

## 2. Chuẩn bị Facebook Page

Project chỉ đăng bằng Facebook Page API, không tự động hóa password/cookie của
profile cá nhân.

1. Mở `accounts/community-learning.md`.
2. Thay `target_id` bằng Page ID thật.
3. Giữ `credential_ref: FACEBOOK_COMMUNITY_PAGE_TOKEN`.
4. Đặt Page Access Token vào `.env`:

   ```dotenv
   FACEBOOK_COMMUNITY_PAGE_TOKEN=paste_page_access_token_here
   ```

5. Restart Streamlit sau khi sửa `.env`.

Page Token hiện có đủ để đăng. Nếu Meta trả `401/403`, app báo
`publish_authentication`. Chỉ Page Token thì app không thể tự tạo token Facebook
mới; muốn tự cấp lại cần bổ sung Meta App/Facebook Login và user-token flow.

## 3. Chọn một trong hai content template

Mở **1 · Create content** và tải một trong hai template bên phải.

### Template A — AI tự tạo bài

```md
---
mode: generate
task: create
pipeline: full
---

# Topic

Ba cách học Python hiệu quả cho người mới

# Instructions

Viết thành checklist ba bước, giọng thân thiện, có ví dụ thực tế và kết thúc
bằng một câu hỏi.

# Source

Phần này tùy chọn với task create. Đặt tài liệu nguồn tại đây nếu AI bắt buộc
phải sử dụng nó.
```

Các task:

| Task | Source bắt buộc | Ý nghĩa |
|---|---:|---|
| `create` | Không | Tạo bài mới từ topic, instructions và policy |
| `repurpose` | Có | Chuyển thể source cho đúng nền tảng/audience |
| `rewrite` | Có | Viết lại nhưng giữ ý chính |
| `summarize` | Có | Tóm tắt source thành social post |

`pipeline: full` chạy Research → Copywriter → hard-rule Critic → LLM Critic →
rewrite/review. `pipeline: draft` chỉ chạy Research và Copywriter.

### Template B — bài đã viết xong

```md
---
mode: publish
task: create
pipeline: full
---

# Topic

Học Python cho người mới

# Content

Bạn không cần học mọi thứ cùng lúc.

1. Chọn một bài toán nhỏ.
2. Viết phiên bản đầu tiên.
3. Sửa dựa trên lỗi thật.

Bạn đang muốn tự động hóa bài toán nào đầu tiên?

#HocPython #Python
```

Mode `publish` không gọi AI và không tiêu tốn AI token. App tạo một manual
draft có audit, chạy hard-rule validation rồi đưa vào Review hoặc trạng thái
Passed theo account policy.

Parser dùng CommonMark với raw HTML bị tắt. Heading, image, fenced code,
blockquote, ordered list và bullet list đều được nhận diện. Adapter hiện tại
đăng text; Markdown image được giữ trong cấu trúc nhưng chưa upload binary
image lên Meta.

## 4. Upload và chạy Markdown

1. Chọn **Kênh & phong cách**.
2. Upload đúng một file `.md` hoặc `.markdown`.
3. Đọc mode, task, block count, topic và preview app đã parse.
4. Bấm **Chạy content Markdown**.

Kết quả:

- `mode: generate`: AI tạo bài, chấm điểm và có thể rewrite tối đa hai lần.
- `mode: publish`: bài có sẵn được nhập thẳng vào workflow, không gọi AI.
- `approval_required: true`: bài vào **2 · Review & approve**.
- `approval_required: false` và hard rules pass: bài sẵn sàng trong
  **3 · Publish**.
- Hard-rule violation luôn yêu cầu sửa/duyệt, kể cả policy không bắt approval.

Không đặt `access_token`, `api_key`, `app_secret`, `password`, `cookie` hoặc
`refresh_token` trong front matter. Parser từ chối các field này.

## 5. Review và approve

Mở **2 · Review & approve**:

1. Chọn run.
2. So sánh original Markdown request với current post.
3. Kiểm tra score, violation, suggestion và policy threshold.
4. Có thể Edit hoặc Reject.
5. Nhập tên/email operator và approval note.
6. Bấm **Approve and move to Publish**.

Sau approve, app hiện result panel gồm action, state mới, run ID, draft ID và
operator. Đây là audit evidence cho demo.

## 6. Publish không còn phải nhập `PUBLISH`

Mở **3 · Publish**, chọn bài đã Approved/Passed:

1. Kiểm tra destination và post preview.
2. Có thể bấm **Run publishing dry-run**. Bước này được khuyến nghị nhưng không
   bắt buộc.
3. Với token và target ID thật, bấm **Publish live now**.

Không còn checkbox hoặc operation input để nhập cụm từ xác nhận. Một lần click
sẽ gọi publisher ngay. Backend vẫn giữ:

- workflow-state guard;
- approval/permission policy;
- target-ID validation;
- hard-rule validation trước approve;
- credential lookup;
- idempotency reservation;
- retry có giới hạn cho network, HTTP `429` và `5xx`;
- audit receipt và remote post ID.

## 7. Lấy và kết nối Threads

### 7.1 Tạo Meta App

1. Vào [Meta for Developers](https://developers.facebook.com/apps/).
2. Bấm **Create App** và chọn Threads use case.
3. Trong App Dashboard, lấy **Threads App ID** và **Threads App Secret**.
4. Trong Threads API settings, thêm OAuth Redirect URI:

   ```text
   http://localhost:8501
   ```

   Giá trị phải giống hoàn toàn `THREADS_REDIRECT_URI`.

5. Khi app còn Development mode, thêm Threads account của bạn vào role/tester
   phù hợp và accept invitation.
6. Xin tối thiểu:

   - `threads_basic`
   - `threads_content_publish`
   - `threads_keyword_search` nếu policy dùng `trend_search: true`

Meta mô tả luồng authorization-code, đổi short-lived token sang long-lived
token và refresh token chưa hết hạn trong
[Threads API Authorization](https://www.postman.com/meta/threads/folder/34203612-e0373e84-de6b-46f1-b90d-3fea76ba6782).

### 7.2 Bật encrypted token store

Tạo Fernet key một lần:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy output vào `.env`:

```dotenv
THREADS_APP_ID=your_threads_app_id
THREADS_APP_SECRET=your_threads_app_secret
THREADS_REDIRECT_URI=http://localhost:8501
THREADS_TOKEN_REFRESH_DAYS=7
CONTENT_AGENT_TOKEN_ENCRYPTION_KEY=paste_generated_fernet_key
CONTENT_AGENT_TOKEN_STORE=artifacts/meta_tokens.enc
```

Không commit `.env`, encryption key hoặc `artifacts/meta_tokens.enc`.

### 7.3 Kết nối ngay trong UI

1. Restart Streamlit.
2. Mở sidebar **Facebook & Threads**.
3. Chọn Threads account policy.
4. Mở **OAuth setup · lấy Threads token**.
5. Kiểm tra App ID, App Secret và Redirect URI.
6. Bấm **1 · Đăng nhập và cấp quyền Threads**.
7. Đăng nhập Threads và Allow.
8. Meta redirect về app với `code`; app tự điền code.
9. Bấm **3 · Exchange code và kết nối**.
10. Copy Threads User ID app hiển thị vào `target_id` của Threads account
    policy nếu ID hiện tại là placeholder.

App đổi code thành short-lived token, tiếp tục đổi thành long-lived token và
lưu encrypted token. Meta hiện trả `expires_in` cho long-lived token; app lưu
expiry và tự gọi `th_refresh_token` trong bảy ngày trước hạn. Refresh thành công
được rotate vào encrypted store, nên restart app không làm mất kết nối.

Nếu bạn đã có long-lived token, có thể paste vào
`THREADS_RESPONSIBLE_AI_TOKEN (session only)`, chọn số ngày còn lại rồi bấm
**Lưu/kích hoạt Threads token**.

### 7.4 Community/topic tag

Trong Threads account policy:

```md
## Publishing
- adapter: threads
- target_id: YOUR_THREADS_USER_ID
- credential_ref: THREADS_RESPONSIBLE_AI_TOKEN
- topic_tag: Responsible AI
- topic_tag_candidates: Responsible AI | AI Tools | AI for Business
- trend_search: true
- approval_required: true
```

Khi `trend_search: true`, app tìm recent activity trong tối đa năm candidate,
chọn candidate có nhiều kết quả nhất rồi gửi một `topic_tag`. Đây là lựa chọn
trend-aware trong niche đã được operator phê duyệt, không phải global trending
feed.

## 8. Kịch bản demo ngắn

1. Mở sidebar và show ba AI connections sẵn sàng.
2. Show Facebook Page configured; Threads có thể show Connected hoặc Setup.
3. Download `content-generate.md`, chỉnh Topic/Instructions, upload lại.
4. Bấm **Chạy content Markdown** và show AI result/score.
5. Approve kèm operator + note; show result panel.
6. Trong Publish, chạy dry-run và show receipt.
7. Nếu muốn quay live demo, kiểm tra Page ID/token rồi bấm **Publish live now**
   một lần.
8. Mở Analytics để show run events, token usage, publish receipt và SQLite
   snapshot có tên ngẫu nhiên.

## 9. Rủi ro và cách xử lý

- Page/Threads token bị revoke: Meta trả `401/403`; điều tra trước khi retry.
- Threads token đã hết hạn: token hết hạn không silent-refresh được, phải OAuth
  reconnect.
- App Secret lộ: rotate ngay trong Meta Dashboard và thay secret hệ thống.
- Process crash sau khi reserve publish: hệ thống giữ reservation để tránh đăng
  trùng; cần điều tra receipt trước khi thao tác tiếp.
- File có raw HTML: parser không render HTML.
- Markdown image: adapter text không tự upload file ảnh.
- SQLite/local encrypted store trên Streamlit Cloud có thể mất khi container
  reboot; production nên thay bằng database/secret manager bền vững.

