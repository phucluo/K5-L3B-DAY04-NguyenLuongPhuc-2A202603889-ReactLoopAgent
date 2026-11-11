# Ghi chú phân tích · Day 04

Họ và tên: Nguyễn Lương Phúc    
MSSV: 2A202603889

## 1. Case được chọn

- ID case: E2.
- Câu hỏi: Cloudflare cache purge có incident nào liên quan không? Một website CLB không thuộc FedRAMP có chắc bị ảnh hưởng không?
- Câu trả lời của agent (trích nguyên văn):
  > Sự cố trên chỉ giới hạn phạm vi tác động đối với các khách hàng thuộc phân khúc FedRAMP. Do đó, một website CLB thông thường **không bị ảnh hưởng bởi sự cố này**.
- Toàn bộ answer và trace được lưu tại case E2 trong eval_before.json.
- Điểm lần chạy 1: 100/100; evidence 20/20.
- Lỗi chọn để cải tiến: final answer không có URL nguồn trực tiếp, dù tool đã trả URL incident.

## 2. Bằng chứng trong trace

Trích các trường liên quan từ trace E2; đã lược bỏ các trường khác:

```json
{
  "event": "tool",
  "step": 2,
  "name": "get_incident_details",
  "arguments": {
    "incident_id": "wp49bp8bqo6c",
    "provider": "cloudflare"
  },
  "result": {
    "ok": true,
    "status": "identified",
    "url": "https://www.cloudflarestatus.com/incidents/wp49bp8bqo6c"
  }
}
```

Model sau đó dừng ở step 3:

```json
{
  "event": "model",
  "step": 3,
  "finish": "stop"
}
```

Nhận xét khi đọc trace và answer: agent đã nhận được URL incident nhưng final answer không chứa URL đó, cũng không có URL nguồn trực tiếp nào khác.

Nhận xét của LLM judge: câu trả lời chính xác, đầy đủ về incident và phạm vi non-FedRAMP; judge chấm 100/100 và ghi improvement là "Không có". Điểm này không phát hiện thiếu URL theo contract kiểm tra nguồn, không có nghĩa toàn bộ đánh giá nội dung của judge đều sai.

Nguyên nhân xác nhận từ code baseline: khi finish == "stop" và không có calls, loop trả completed ngay, chưa kiểm tra URL. System prompt đã nhắc dẫn nguồn nhưng chưa có kiểm tra bằng code để bảo đảm điều đó.

## 3. Thay đổi đã thực hiện

- Trong agent.py, thu thập observed_urls từ get_incident_details khi tool trả ok == true và URL là chuỗi không rỗng.
- Trước khi trả completed, kiểm tra answer có chứa ít nhất một URL đã quan sát.
- Nếu thiếu, ghi event validation_missing_source cùng draft_answer và observed_urls; yêu cầu model viết lại trong giới hạn max_steps.
- Nếu hết budget mà vẫn thiếu nguồn, trả max_steps thay vì completed.
- Dùng tools.schemas và tools.system_prompt khi có, fallback về cấu hình bài chính để hỗ trợ tools bonus.
- Khôi phục nhánh error cho response có finish == "tool_calls" nhưng calls rỗng; cập nhật mô tả cũ của file.

Lý do chọn: bổ sung kiểm tra trực tiếp cho lỗi nguồn thấy trong E2, thay vì chỉ dựa vào lời nhắc trong prompt.

Kiểm tra offline sau thay đổi: 42 tests chính và 3 tests bonus đều OK; fake provider với tool_calls rỗng trả error ngay khi max_steps=1.

Giới hạn: kiểm tra chỉ bảo đảm answer chứa ít nhất một URL incident đã quan sát; chưa chứng minh mọi claim hoặc mọi provider đều được dẫn nguồn. Chưa có kết quả eval_after hoặc điểm bonus.

## 4. So sánh hai lần chạy

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Điểm tổng |  |  |
| Điểm case đã chọn |  |  |
| Số model calls |  |  |
| Token, chi phí nếu có |  |  |

- Lỗi đã giải quyết:
- Lỗi còn lại hoặc mới xuất hiện:

## 5. Giới hạn

Nêu giới hạn của điểm judge, của snapshot và của việc chỉ chạy một lần mỗi phiên bản.
