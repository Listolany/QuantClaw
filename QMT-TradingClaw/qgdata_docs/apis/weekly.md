# `weekly` 接口文档

## 接口说明

- 中文说明：周线行情
- 动态方法：`pro.weekly(...)`
- 默认时间字段：`trade_date`
- 典型过滤参数：`ts_code`, `trade_date`, `start_date`, `end_date`
- 主要字段：`ts_code`, `trade_date`, `close`, `open`, `high`, `low`, `pre_close`, `change`

## 调用示例

```python
df = pro.weekly(
    ts_code="000001.SZ",
    trade_date="20260217",
    start_date="20260101",
    end_date="20260217",
    fields="ts_code,trade_date,close,open,high,low,pre_close,change",
    order_by="trade_date",
    sort="desc",
    limit=50,
)
```
