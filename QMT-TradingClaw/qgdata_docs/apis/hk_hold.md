# `hk_hold` 接口文档

## 接口说明

- 中文说明：沪深港股通持股明细
- 动态方法：`pro.hk_hold(...)`
- 默认时间字段：`trade_date`
- 典型过滤参数：`trade_date`, `start_date`, `end_date`
- 主要字段：`code`, `trade_date`, `ts_code`, `name`, `vol`, `ratio`, `exchange`

## 调用示例

```python
df = pro.hk_hold(
    trade_date="20260217",
    start_date="20260101",
    end_date="20260217",
    fields="code,trade_date,ts_code,name,vol,ratio,exchange",
    order_by="trade_date",
    sort="desc",
    limit=50,
)
```
