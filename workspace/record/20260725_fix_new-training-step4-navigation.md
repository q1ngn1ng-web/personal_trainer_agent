# 2026-07-25 · fix · page_new_training Step 4 "查看训练详情" 按钮不跳转

## 变更摘要

**Bug**：在新建训练向导的第 4 步（完成页），点击「查看训练详情 →」按钮不会跳转到详情页。

### 根因

`src/ui/page_new_training.py` 第 374 行的 button handler 只设 `st.query_params["training_id"]`，没设 `page=detail`。`src/main.py` 的路由器看到当前页是 `new_training`，设置了 `?training_id=8` 后路由仍停在 `new_training` 页面，按钮视觉上"失效"。

```python
# 修改前
if st.button("查看训练详情 →", ...):
    st.query_params["training_id"] = str(training.id)  # 只设 training_id
    st.rerun()
```

### 修复

button handler 同时设 `page=detail` + `training_id`，让 main.py 路由跳到详情页：

```python
# 修改后
if st.button("查看训练详情 →", ...):
    st.query_params["page"] = "detail"                  # 新增
    st.query_params["training_id"] = str(training.id)
    st.rerun()
```

## 影响范围

```
src/ui/page_new_training.py:368-375
```

仅一处 button handler，不影响其他页面/服务。

## 相关文件路径

```
src/ui/page_new_training.py:368   # button handler
```

## 关联的 OpenSpec change id

无（bug fix；与 trainer-mvp-v1 实施产物内务修正同类，不产生新 spec）

## 验证

用户实际操作验证：完成训练向导后点击按钮 → 成功跳转到 `?page=detail&training_id=N`。

启动日志：`uv run streamlit run src/main.py` 启动无 traceback。

回归：30 单测 ✅。

## Git

```
(待提交) fix(ui): page_new_training Step 4 按钮同时设 page=detail 和 training_id
```

## 关联变更

本次修复后，"导航" 相关的另一个 UX gap（缺少全局导航）由同日 commit `feat(ui): main.py 加常驻 sidebar 导航` 解决，详见 `20260725_feat_sidebar-navigation.md`。