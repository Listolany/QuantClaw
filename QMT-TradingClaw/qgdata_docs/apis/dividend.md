# `dividend` 接口文档

## 接口说明

- 中文说明：分红送股
- 动态方法：`pro.dividend(...)`
- 默认时间字段：`ann_date`
- 典型过滤参数：`ts_code`, `ann_date`, `start_date`, `end_date`, `record_date`, `ex_date`
- 主要字段：`ts_code`, `end_date`, `ann_date`, `div_proc`, `stk_div`, `stk_bo_rate`, `stk_co_rate`, `cash_div`

## 调用示例

```python
df = pro.dividend(
    ts_code="000001.SZ",
    ann_date="20260217",
    record_date="",
    ex_date="",
    start_date="20260101",
    end_date="20260217",
    fields="ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div",
    order_by="ann_date",
    sort="desc",
    limit=50,
)
```
