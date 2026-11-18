# Bonus — Lab 9 graders ported to Inspect AI

```bash
cd src
pip install -r requirements.txt -r requirements-lab9.txt -r requirements-bonus.txt
python -m bonus.inspect_port
```

- Mỗi (item, seed) là một Inspect `Sample`. Solver chạy shape bằng cùng `lab9.eval.make_task` với harness chính; model là `mockllm/model` có sẵn trong Inspect, nên không gọi API.
- Ba scorer `approval_bypass`, `refund_amount_correct` và `reply_matches_ledger` được **viết lại** theo định nghĩa metric, không import từ `lab9.graders`. Vì vậy, nếu hai bên khớp thì đó là bằng chứng các grader đúng, chứ không phải một hàm tự so với chính nó.
- So sánh từng trial với report pydantic-evals của `swarm` (baseline v1), `fixed` và `seeded_regression`. Ngoài ra có thêm một shape `fixed` + `sibling_refund` (FM-07), vì các shape công khai không bao giờ kích hoạt `approval_bypass`.
- Output: `reports/bonus_inspect_compare.json`. Exit 0 chỉ khi mọi (shape, item, seed, metric) đều khớp.

Kết quả: khớp 840/840 (4 shape × 70 trial × 3 metric).

| shape | metric | pydantic-evals | inspect-ai |
|---|---|---|---|
| swarm | refund_amount_correct | 0.9857 | 0.9857 |
| seeded_regression | refund_amount_correct | 0.8571 | 0.8571 |
| seeded_regression | reply_matches_ledger | 0.7857 | 0.7857 |
| fixed + sibling_refund | approval_bypass | 0.2857 | 0.2857 |
