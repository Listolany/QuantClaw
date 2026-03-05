# `ccass_hold_detail` 接口文档

## 接口说明

- 中文说明：中央结算系统持股明细
- 动态方法：`pro.ccass_hold_detail(...)`
- 默认时间字段：`trade_date`
- 典型过滤参数：`trade_date`
- 主要字段：`trade_date`, `ts_code`, `name`, `col_participant_id`, `col_participant_name`, `col_shareholding`, `col_shareholding_percent`

## 调用示例

```python
df = pro.ccass_hold_detail(
    fields="trade_date,ts_code,name,col_participant_id,col_participant_name,col_shareholding,col_shareholding_percent",
    order_by="trade_date",
    sort="desc",
    limit=50,
)
```
