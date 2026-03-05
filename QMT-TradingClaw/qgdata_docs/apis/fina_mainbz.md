# `fina_mainbz` 接口文档

## 接口说明

- 中文说明：主营业务构成
- 动态方法：`pro.fina_mainbz(...)`
- 默认时间字段：`end_date`
- 典型过滤参数：`period`, `start_date`, `end_date`, `type`
- 主要字段：`ts_code`, `end_date`, `bz_item`, `bz_sales`, `bz_profit`, `bz_cost`, `curr_type`, `update_flag`

## 调用示例

```python
df = pro.fina_mainbz(
    period="20251231",
    type="",
    start_date="20260101",
    end_date="20260217",
    fields="ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost,curr_type,update_flag",
    order_by="end_date",
    sort="desc",
    limit=50,
)
```
