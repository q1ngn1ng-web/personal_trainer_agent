# 公开仓发布前整理

> 日期：2026-09-14
> 类型：chore

## 变更摘要

把项目准备成可上传到 GitHub 公开仓的状态，核心是**把个人求职材料从仓库中剔除**，并修正 README 中已失效的测试命令。

具体动作：

1. `.gitignore` 新增两组规则：个人求职材料（`docs/简历项目包装与深挖问答.md`、`docs/项目现状与改进方向.md` 及其 `workspace/record/` 下的变更记录）与 Obsidian 本地编辑状态（`workspace/.obsidian/`）。
2. 用 `git filter-branch` 把上述文件从**全部提交历史**中清除（不只是最新提交），避免公开仓通过历史 diff 泄露面试话术与简历包装策略。文件本身保留在本地磁盘，未删除。
3. 清理前建立本地备份分支 `backup/pre-public-20260914`，指向清理前的 `615095a`，可随时还原。
4. 修正 README「测试」章节：原命令引用了不存在的 `scripts/e2e_llm_observability.py`、`scripts/e2e_review_calibration.py`，改为 `scripts/` 下实际存在的脚本。

## 影响范围

- 公开仓中不再包含个人求职材料与编辑器本地状态。
- 提交历史被重写：涉及个人文档的若干提交（`0ab443e`、`5c5c811`、`45ad51a`、`e1eb16b`、`615095a`）因内容被清空而移除，其余提交的 hash 全部变化。
- 不影响 `src/`、`docs/architecture.md`、`codemap.md` 等代码与项目文档。

## 相关文件路径

- `.gitignore`
- `README.md`
- `docs/简历项目包装与深挖问答.md`（保留本地，不入库）
- `docs/项目现状与改进方向.md`（保留本地，不入库）
- `workspace/record/20260913_docs_*.md`（保留本地，不入库）

## 关联 OpenSpec change

无（仓库发布准备，不涉及产品规格变更）。

## 还原方式

```bash
git reset --hard backup/pre-public-20260914
```

> 注意：还原会同时恢复被清除的提交历史，请确认当前公开仓未推送过再执行。
