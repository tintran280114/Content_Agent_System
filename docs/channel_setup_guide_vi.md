# Hướng dẫn tự thêm, thay và gỡ tài khoản kênh

Tài liệu này dành cho thành viên cần tự cấu hình hoặc test một tài khoản Facebook,
Threads hay LinkedIn khác. Mỗi tài khoản được định nghĩa bằng một policy Markdown ở
`accounts/<account-slug>.md`. Token và Client Secret **không** nằm trong file policy.

## 1. Chuẩn bị an toàn

1. Cập nhật source trước khi thao tác:

   ```powershell
   git switch main
   git pull origin main
   ```

2. Tạo môi trường và chạy dashboard theo README của dự án.
3. Chỉ đặt token/secret vào `.env` cục bộ hoặc các ô **session only** trên dashboard.
   Không commit `.env`, token, Client Secret hay authorization code.
4. Với một tài khoản mới, luôn chạy **dry-run** trước. Dry-run không gọi API bên ngoài.

## 2. Thêm một tài khoản mới trong dashboard

1. Mở dashboard, vào tab **Channels** → **Add channel**.
2. Điền:
   - **Display name:** tên dễ nhận biết, ví dụ `Demo Facebook Page`.
   - **Account slug:** định danh duy nhất, chỉ dùng chữ thường, số và dấu gạch ngang,
     ví dụ `demo-facebook-page`.
   - **Platform:** Facebook, Threads hoặc LinkedIn.
   - Audience, tone, goal, language và các rule nội dung cần thiết.
3. Trong **Publishing configuration**, điền đúng:
   - **Target ID:** ID Page (Facebook), User ID (Threads), hoặc Person URN
     `urn:li:person:...` (LinkedIn).
   - **Credential reference:** tên biến token cục bộ, ví dụ
     `FACEBOOK_DEMO_PAGE_TOKEN`. Đây chỉ là *tên tham chiếu*, không phải token.
   - Giữ **Approval required** bật khi test hoặc demo.
4. Bấm tạo cấu hình, kiểm tra preview, rồi **Save channel**.
5. Vào **Current channels** để xác nhận tài khoản xuất hiện.

## 3. Cấu hình token cục bộ

Trong `.env` trên máy test, tạo biến đúng với `credential_ref` của policy:

```dotenv
FACEBOOK_DEMO_PAGE_TOKEN=
```

Sau dấu `=` mới là token thật; không chia sẻ hay commit file này. Có thể dùng ô
**session only** trong sidebar để thử nhanh. Session-only mất khi dashboard khởi động
lại; `.env` cục bộ tiện hơn cho lần test sau.

## 4. Kiểm tra theo từng nền tảng

### Facebook Page

- Adapter: `facebook_page`.
- Target ID: đúng Page ID.
- Token phải là **Page Access Token** của chính Page đó và có quyền publish cần thiết.
- Test flow: tạo/nhập post → review → approve → **Run publishing dry-run** → live publish.

### Threads

- Adapter: `threads`.
- Target ID: Threads User ID.
- Kết nối OAuth trong sidebar của dashboard, hoặc dùng token hợp lệ ở ô session-only.
- OAuth redirect URL phải trùng tuyệt đối URL đã đăng ký với Meta. Test dry-run trước,
  sau đó mới publish live.

### LinkedIn

- Adapter: `linkedin`.
- Target ID: Person URN dạng `urn:li:person:...`, không phải URL profile.
- Token cần scope `w_member_social`. Nếu dùng OAuth, Client ID, Client Secret và
  Redirect URI phải khớp cấu hình LinkedIn; authorization code chỉ dùng được một lần.
- Test dry-run trước. Live publish còn phụ thuộc quyền truy cập/entitlement Posts API
  của LinkedIn; lỗi 403 thường là vấn đề quyền API, không phải do policy.

## 5. Thay token hoặc thay cấu hình của tài khoản đã có

### Chỉ thay token

Giữ nguyên policy. Cập nhật giá trị token trong `.env` cục bộ hoặc ô session-only,
sau đó restart dashboard nếu dùng `.env`. Không cần sửa Markdown và không cần commit.

### Thay Page/User/Person URN hoặc rule nội dung

1. Vào **Channels** → **Advanced Markdown**.
2. Tải policy hiện có tại **Current channels** → **View policy Markdown** →
   **Download policy**.
3. Sửa `target_id`, `credential_ref` hoặc rule cần thiết. Không thêm token vào file.
4. Upload file đã sửa, bật **Replace existing policy with the same slug**, rồi lưu.
5. Chạy dry-run lại trước live publish.

## 6. Tạm dừng hoặc gỡ tài khoản

### Tạm dừng (khuyến nghị)

Sửa trong policy:

```markdown
- active: false
```

Upload lại policy và bật tùy chọn replace. Tài khoản không còn được chọn trong các
batch mới, nhưng toàn bộ run, audit và delivery receipt cũ vẫn giữ nguyên.

### Gỡ hẳn khỏi source

1. Xóa duy nhất file `accounts/<account-slug>.md`.
2. Kiểm tra `git status`, sau đó commit và push/PR theo quy trình nhóm.
3. Tài khoản sẽ không còn được hệ thống phát hiện ở các lần chạy sau. Dữ liệu SQLite
   lịch sử không bị xóa chủ động.

Không xóa `.env` dùng chung của người khác và không đưa token vào Git để “giữ lại” cấu
hình. Người test mới tự tạo `.env` từ `.env.example` và điền credential của chính họ.

## 7. Checklist bàn giao cho người test

- [ ] Đã pull `main` mới nhất.
- [ ] Có policy Markdown với account slug riêng.
- [ ] `target_id` đúng nền tảng và `credential_ref` chỉ là tên biến.
- [ ] Token/secret chỉ nằm local hoặc session-only.
- [ ] Dry-run pass.
- [ ] Human approval đã được thực hiện trước live publish.
- [ ] Không có secret xuất hiện trong `git status` hoặc commit.
