# `broker_recommend` 接口文档

## 接口说明

- 中文说明：券商月度金股
- 动态方法：`pro.broker_recommend(...)`
- 默认时间字段：`month`
- 典型过滤参数：`start_date`, `end_date`, `month`
- 主要字段：`month`, `broker`, `ts_code`, `name`

## 调用示例

```python
df = pro.broker_recommend(
    month="202602",
    start_date="20260101",
    end_date="20260217",
    fields="month,broker,ts_code,name",
    order_by="month",
    sort="desc",
    limit=50,
)
```
