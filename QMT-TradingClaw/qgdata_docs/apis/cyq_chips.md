# `cyq_chips` 接口文档

## 接口说明

- 中文说明：每日筹码分布
- 动态方法：`pro.cyq_chips(...)`
- 默认时间字段：`trade_date`
- 典型过滤参数：`ts_code`, `start_date`, `end_date`
- 主要字段：`ts_code`, `trade_date`, `price`, `percent`

## 调用示例

```python
df = pro.cyq_chips(
    ts_code="000001.SZ",
    start_date="20260101",
    end_date="20260217",
    fields="ts_code,trade_date,price,percent",
    order_by="trade_date",
    sort="desc",
    limit=50,
)
```
