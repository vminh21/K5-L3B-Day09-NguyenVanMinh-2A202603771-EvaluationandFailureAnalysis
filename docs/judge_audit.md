# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (trong `src/`). Lớp positive là FAIL: việc của judge là **tìm ra** reply hỏng.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt | **dùng**, kèm hiệu chỉnh Rogan-Gladen |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt (κ và R dưới sàn) | **loại** |

Ma trận nhầm lẫn (FAIL = positive):

| Tiêu chí | tp | fp | fn | tn | Tỉ lệ FAIL quan sát → sau Rogan-Gladen |
|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 → 0.30 |
| helpful | 9 | 0 | 21 | 70 | 0.09 → 0.30 |

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú | Sửa rubric |
|---|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" và dùng "nha" là quá suồng sã với khách. Judge nhầm suồng sã thành thân thiện. | Thêm vào rubric tone: xưng hô bắt buộc "anh/chị" và "LogiX"; "em/bạn" + "nha/nhé" = FAIL. Thêm H-008 làm ví dụ FAIL. |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Gọi khách là "bạn" sai chuẩn xưng hô của CS. Đây là lỗi cùng kiểu với case 1. | Cùng quy tắc xưng hô ở case 1; thêm H-017 làm ví dụ FAIL có chữ "Dạ" ở đầu (lịch sự bề mặt không cứu được xưng hô sai). |
| 3 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Câu mang giọng ra lệnh. Judge bị mở đầu "Dạ, vui lòng" đánh lừa, tức là chấm theo từ khóa lịch sự. | Thêm tiêu chí: câu mệnh lệnh hoặc cấm khách liên hệ ("không cần nhắn thêm") = FAIL dù có từ lịch sự. Ghi rõ: chấm giọng điệu cả câu, không chấm từ khóa. |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Reply ngắn nhưng đủ ý. Judge phạt vì thiếu lời xin lỗi, thể hiện thiên kiến chuộng câu dài và xin lỗi nhiều. | Ghi rõ: lời xin lỗi **không bắt buộc**; reply ngắn, đủ thông tin, xưng hô đúng = PASS. Thêm H-042 làm ví dụ PASS. |
| 5 | tone H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Quy định CS cho phép dùng từ "refund". Judge phạt vì có tiếng Anh, tức là dùng tiêu chí không có trong rubric. | Thêm danh sách từ tiếng Anh được phép theo chuẩn CS LogiX (bắt đầu với "refund", theo ghi chú của người dán nhãn); dùng từ trong danh sách không bị trừ điểm. |
| 6 | helpful HL-015 "đã hoàn 55.000đ cho đơn O-112" | PASS | FAIL | Người | Ledger ghi 40.000đ. Judge chỉ thấy reply, không thấy ledger, nên không thể bắt lỗi sai tiền. | Rubric `helpful` bỏ tiêu chí "đúng số tiền": judge không có ledger nên không chấm được. Tiêu chí này chuyển sang grader code `ReplyMatchesLedger`. |
| 7 | helpful HL-016 (xin lỗi dài, "đã hoàn 55.000đ") | PASS | FAIL | Người | Ledger ghi 35.000đ. Lời xin lỗi dài làm judge chấm "helpful", trong khi số tiền sai. | Thêm vào rubric `helpful`: độ dài/xin lỗi không cộng điểm; chấm theo "khách biết rõ chuyện gì đã xảy ra và bước tiếp theo". |
| 8 | helpful HL-020 "đã hoàn 90.000đ cho đơn O-303" | PASS | FAIL | Người | Ledger ghi 120.000đ. Đây là FM-08 misreport. | Như case 6: số tiền chấm bằng code. Thêm HL-020 vào tập hồi quy của `reply_matches_ledger`. |
| 9 | helpful HL-028 (xin lỗi lặp lại hai lần, "50.000đ") | PASS | FAIL | Người | Ledger ghi 35.000đ, và câu xin lỗi bị lặp nguyên văn. | Thêm tiêu chí: lặp nguyên văn câu xin lỗi = FAIL (lan man, che thông tin chính). |
| 10 | helpful HL-035 (xin lỗi trước và sau, "50.000đ") | PASS | FAIL | Người | Ledger ghi 35.000đ. Lỗi cùng kiểu với case 7 và 9. | Như case 7 và 9; dùng HL-035 làm ví dụ FAIL trong rubric để judge thấy mẫu "xin lỗi bọc ngoài số tiền sai". |

## Kết luận
- **Loại `helpful`.** Theo ma trận nhầm lẫn, judge bỏ sót 21/30 reply FAIL (R = 0.30). Cả 5 case audit đều là reply **sai số tiền** so với ledger. Judge chỉ đọc reply nên về nguyên tắc không thể phát hiện lỗi này. Theo quy tắc "tiền luôn chấm bằng code", phần đúng/sai số tiền chuyển sang grader code `ReplyMatchesLedger` (metric `reply_matches_ledger`, FM-08). P = 1.0 chỉ cho thấy judge hiếm khi báo FAIL, không phải judge tốt.
- **Giữ `tone_ok`** nhưng không dùng làm metric chặn release. Judge có hai thiên kiến cụ thể: (a) chấm theo từ khóa lịch sự ("Dạ, vui lòng") thay vì giọng điệu thật, nên sót 6 FAIL; (b) phạt reply ngắn, thiếu lời xin lỗi, hoặc có từ "refund", nên báo nhầm 4 FAIL. Khi báo cáo tỉ lệ lỗi tone, dùng con số đã hiệu chỉnh Rogan-Gladen (0.28 → 0.30), không dùng tỉ lệ thô.
- **Sau khi sửa rubric:** phải dán nhãn lại và chạy lại `python -m lab9.judge` trên một tập **mới** (không dùng lại 100 dòng đã audit, vì các ví dụ đã đưa vào rubric). Chỉ khi κ, P, R vẫn đạt sàn trên tập mới thì mới dùng `tone_ok` bản mới. `helpful` không dùng làm gate trong mọi trường hợp: phần số tiền đã thuộc về code.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí). Cần nhãn người mới để có tập held-out thật. Có thể judge đã được chỉnh prompt trên chính tập này, nên κ thật có thể thấp hơn.
