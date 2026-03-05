# `trade_cal` 接口文档

## 接口说明

- 中文说明：交易日历
- 动态方法：`pro.trade_cal(...)`
- 默认时间字段：`cal_date`
- 典型过滤参数：`start_date`, `end_date`, `exchange`
- 主要字段：`exchange`, `cal_date`, `is_open`, `pretrade_date`

## 调用示例

```python
df = pro.trade_cal(
    exchange="SSE",
    start_date="20260101",
    end_date="20260217",
    fields="exchange,cal_date,is_open,pretrade_date",
    order_by="cal_date",
    sort="desc",
    limit=50,
)
```
