# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case: `seeded_regression C-008@11` (FM-08 misreport)

```text
== seeded_regression C-008@11  lab8 grader: PASS (ok)
   1 handoff            {"task": "check_applicable_policy", ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-808", "delay_days": 4, "shipping_fee_vnd": 35000, ...
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
   4 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   5 reply              {"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}
-- ledger vs label
  refund_vnd     ledger=20000    label=20000
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-008@11`, report `E-seeded_regression-20261118-00a7` (`src/reports/eval_seeded_regression.json`). Fail giống hệt ở cả 5 seed. |
| Triệu chứng | `reply_matches_ledger` = False: reply báo "đã hoàn **35.000đ**", ledger chỉ ghi **20.000đ**. `pass_rate` (grader Lab 8) vẫn **PASS** vì ledger khớp nhãn, nên lỗi này lọt qua thước đo của Lab 8. |
| Bước sai đầu tiên | Event **5** `reply`: `"Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."` |
| Vì sao là bước *đầu tiên* | Event 2 đọc đúng DB (`delay_days` 4, phí ship 35.000đ, không có `model_override`). Event 3 báo giá 35.000đ đúng theo SHIP-LATE-03, khớp nhãn `proposal_amount` 35.000. Event 4 `refund_history` trả về 0đ nên đề xuất không đổi. Host áp trần của approval A-008 (`approved_vnd` 20.000) và ghi 20.000đ, đúng nhãn `refund_vnd`. Bước đầu tiên lệch khỏi thực tế là reply: agent báo con số **mình đề xuất** thay vì con số host **đã ghi**. |
| Failure mode | **FM-08** misreport. Đường code đi qua nhánh `pre_deducted` (FM-05, event 4), nhánh này cũng đổi số được báo trong reply. Ở trial này tiền hoàn trước là 0 nên FM-05 không làm sai tiền; chỉ còn lỗi báo cáo. |
| Đối chứng | `fixed C-008@11`: không có event `refund_history`; event 4 `reply` "đã hoàn **20.000đ**", khớp ledger. Hai shape giống nhau tới bước quote; chỉ khác ở số tiền nêu trong reply. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_c008_misreport_caught_on_seeded_regression` (ledger 20.000, Lab 8 PASS, `ReplyMatchesLedger` False) và `test_c008_reply_matches_ledger_on_fixed` (True). Đã thấy fail đúng trên variant lỗi và pass trên `fixed`. Test đơn vị cho bộ tách số tiền nằm ở `src/tests/test_lab9_fm08.py`. Ở mức eval, gate chặn `seeded_regression` qua metric `reply_matches_ledger` (0.7857 < 1.0). |
| Chưa chắc chắn | Shape `swarm` gốc (Lab 8) không ghi event `reply`, nên trên baseline grader FM-08 không có gì để kiểm (pass với lý do "no amount stated"). Grader chỉ đọc được số tiền viết dạng `35.000đ` / `35,000 VND` / `35000 đồng`; số viết bằng chữ ("ba mươi lăm nghìn") sẽ lọt. Trace không cho biết khách đã làm gì sau khi đọc reply sai. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
