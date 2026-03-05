# `cashflow` 接口文档

## 接口说明

- 中文说明：现金流量表
- 动态方法：`pro.cashflow(...)`
- 默认时间字段：`ann_date`
- 典型过滤参数：`ann_date`, `start_date`, `end_date`, `period`, `f_ann_date`, `report_type`
- 主要字段：`ts_code`, `ann_date`, `f_ann_date`, `end_date`, `comp_type`, `report_type`, `end_type`, `net_profit`

## 调用示例

```python
df = pro.cashflow(
    ann_date="20260217",
    f_ann_date="",
    start_date="20260101",
    end_date="20260217",
    fields="ts_code,ann_date,f_ann_date,end_date,comp_type,report_type,end_type,net_profit",
    order_by="ann_date",
    sort="desc",
    limit=50,
)
```
