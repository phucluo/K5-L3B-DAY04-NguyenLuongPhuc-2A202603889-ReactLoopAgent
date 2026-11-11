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

Giới hạn: kiểm tra chỉ bảo đảm answer chứa ít nhất một URL incident đã quan sát; chưa chứng minh mọi claim hoặc mọi provider đều được dẫn nguồn. Eval_after đã hoàn tất; chưa chạy eval bonus.

## 4. So sánh hai lần chạy

Hai lượt có cùng config: Gemini agent gemini-3.8-flash, judge gemini-3.5-flash-lite, core snapshot, max_steps=8 và các tham số còn lại. Code agent khác nhau theo cải tiến; manifest của từng lượt được giữ nguyên.

| Chỉ số | eval_before.json | eval_after.json |
|---|---|---|
| Case hoàn thành và được chấm | 22/22 | 22/22 |
| Điểm tổng | 100.0 | 100.0 |
| Điểm E2 | 100 | 100 |
| Agent model calls trong kết quả cuối | 53 | 56 |
| Judge calls | 22 | 22 |
| Tool calls trong trace cuối | 41 | 42 |
| Case có URL incident đã quan sát trong answer | 8/14 | 14/14 |
| Event validation_missing_source | 0 | 2 |
| Tổng request attempts, gồm phiên lỗi | 75 | 80 |
| Agent total_tokens API báo, gồm phiên lỗi | 54.152 | 62.344 |
| Judge total_tokens API báo | 42.322 | 44.948 |
| Tổng token API báo qua các phiên | 96.474 | 107.292 |

Mẫu số 14 chỉ gồm các case có get_incident_details thành công và nhận được URL. Chỉ số này kiểm tra answer có ít nhất một URL đã quan sát, không kiểm tra mọi nguồn hay mọi claim.

Lỗi nguồn đã cải thiện:
- E2 trước không có URL nguồn trực tiếp; sau có URL https://www.cloudflarestatus.com/incidents/wp49bp8bqo6c. Cả hai lượt E2 dùng 3 model calls; lượt sau không kích hoạt validation_missing_source, nên riêng E2 chưa chứng minh tác động trực tiếp của gate.
- E4: draft step 2 thiếu URL; gate ghi event và final step 3 có URL đã quan sát.
- A7: draft step 3 thiếu URL incident dù có URL trang chủ Cloudflare; gate yêu cầu sửa và final step 4 có URL incident.
- Cả 6 case trước thiếu đúng URL incident đã quan sát (E2, E3, E4, E5, A6, A7) đều có URL phù hợp trong answer sau.

Điểm judge không tăng: toàn bộ case vẫn đạt 100. Cải thiện hành vi nguồn có bằng chứng trực tiếp ở trace E4 và A7.

Lỗi vận hành:
- Phiên after đầu dừng do TimeoutError ở request LLM của A7, step 2; không có HTTP status được ghi nhận.
- Resume giữ nguyên 12 case đã chấm, chạy lại agent A7 chưa hoàn tất rồi hoàn thành bộ eval.
- Hai phiên dùng 46 + 34 = 80 request attempts: 57 agent requests thành công, 1 agent request lỗi và 22 judge requests thành công.
- Trace lỗi A7 được giữ trong previous_agent_errors.

Phân biệt token:
- Các kết quả agent cuối cùng của after có 61.985 token; judge có 44.948, tổng 106.933.
- Nhật ký request còn ghi thêm 359 token từ bước thành công của lần A7 bị gián đoạn, nên tổng API báo qua các phiên là 107.292.
- Request timeout không có usage trả về; không đủ dữ liệu xác định token hoặc chi phí thực tế của request đó.
- Chưa có số tiền thực tế; không tự quy đổi token thành chi phí.

## 5. Giới hạn

- Điểm eval là đánh giá xấp xỉ của judge kết hợp kiểm tra code, không phải điểm bài lab. Baseline E2 đạt evidence 20/20 dù không có URL trực tiếp.
- Sau cải tiến, A7 vẫn nêu nhận định về Anycast và các PoP gần Việt Nam mà tool results trong trace không cung cấp. Chưa xác minh các nhận định này; có URL không bảo đảm mọi lập luận đều được nguồn hỗ trợ.
- Gate chỉ kiểm tra sự hiện diện ít nhất một URL incident đã quan sát; không xác minh nội dung từng claim hoặc nguồn cho từng provider.
- Snapshot phản ánh dữ liệu đã lưu, không đại diện trạng thái hiện tại. Tìm kiếm và nội dung update có giới hạn.
- Chỉ chạy một lượt eval cho mỗi phiên bản; resume là tiếp tục lượt bị gián đoạn. Chưa đủ bằng chứng về độ ổn định hoặc quy mọi khác biệt token/calls cho cải tiến.
- Không tự ép total_tokens bằng prompt_tokens + completion_tokens; giữ số API thực sự báo.
- Ba tests bonus offline đã pass không tương đương hoàn thành 10 case eval bonus.