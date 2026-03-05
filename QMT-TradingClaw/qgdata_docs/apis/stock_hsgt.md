# `stock_hsgt` 接口文档

## 接口说明

- 中文说明：沪深港通股票列表
- 动态方法：`pro.stock_hsgt(...)`
- 默认时间字段：`trade_date`
- 典型过滤参数：`trade_date`, `start_date`, `end_date`, `type`
- 主要字段：`ts_code`, `trade_date`, `type`, `name`, `type_name`

## 调用示例

```python
df = pro.stock_hsgt(
    trade_date="20260217",
    type="HK_SZ",
    start_date="20260101",
    end_date="20260217",
    fields="ts_code,trade_date,type,name,type_name",
    order_by="trade_date",
    sort="desc",
    limit=50,
)
```
