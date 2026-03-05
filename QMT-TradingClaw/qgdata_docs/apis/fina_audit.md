# `fina_audit` 接口文档

## 接口说明

- 中文说明：财务审计意见
- 动态方法：`pro.fina_audit(...)`
- 默认时间字段：`ann_date`
- 典型过滤参数：`ann_date`, `start_date`, `end_date`, `period`
- 主要字段：`ts_code`, `ann_date`, `end_date`, `audit_result`, `audit_fees`, `audit_agency`, `audit_sign`

## 调用示例

```python
df = pro.fina_audit(
    ann_date="20260217",
    start_date="20260101",
    end_date="20260217",
    period="20251231",
    fields="ts_code,ann_date,end_date,audit_result,audit_fees,audit_agency,audit_sign",
    order_by="ann_date",
    sort="desc",
    limit=50,
)
```
