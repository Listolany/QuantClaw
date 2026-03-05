# `margin` 接口文档

## 接口说明

- 中文说明：融资融券交易汇总
- 动态方法：`pro.margin(...)`
- 默认时间字段：`trade_date`
- 典型过滤参数：`trade_date`, `start_date`, `end_date`
- 主要字段：`trade_date`, `exchange_id`, `rzye`, `rzmre`, `rzche`, `rqye`, `rqmcl`, `rzrqye`

## 调用示例

```python
df = pro.margin(
    trade_date="20260217",
    start_date="20260101",
    end_date="20260217",
    fields="trade_date,exchange_id,rzye,rzmre,rzche,rqye,rqmcl,rzrqye",
    order_by="trade_date",
    sort="desc",
    limit=50,
)
```
