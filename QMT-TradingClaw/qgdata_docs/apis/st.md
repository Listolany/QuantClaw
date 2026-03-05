# `st` 接口文档

## 接口说明

- 中文说明：ST风险警示板股票
- 动态方法：`pro.st(...)`
- 默认时间字段：`pub_date`
- 典型过滤参数：`start_date`, `end_date`, `pub_date`
- 主要字段：`ts_code`, `name`, `pub_date`, `imp_date`, `st_tpye`, `st_reason`, `st_explain`

## 调用示例

```python
df = pro.st(
    pub_date="",
    start_date="20260101",
    end_date="20260217",
    fields="ts_code,name,pub_date,imp_date,st_tpye,st_reason,st_explain",
    order_by="pub_date",
    sort="desc",
    limit=50,
)
```
