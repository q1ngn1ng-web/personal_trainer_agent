# trainer-generation Specification

## MODIFIED Requirements

### Requirement: 用户能创建新训练主题
系统 SHALL 提供「新建训练」入口（Streamlit 页面或按钮），用户输入训练主题后能跑通完整创建流程。主题创建 MUST 先经过目标澄清与确认（见 `goal-clarification`），目标未确认的训练 MUST NOT 进入关键词生成与训练文件生成。

#### Scenario: 主题输入页可达
- **WHEN** 用户在首页点击「新建训练」
- **THEN** 系统跳转到新建训练向导页

#### Scenario: 主题持久化入口
- **WHEN** 用户在向导中提交主题描述
- **THEN** 系统在 `trainings` 表写入一条记录（topic 字符串、status=draft、created_at 时间戳），且该主题在首页训练列表中可见

#### Scenario: 未确认不得生成
- **WHEN** 训练状态仍为 `draft` 或 `pending_confirm`
- **THEN** 系统不发起关键词白名单生成，也不渲染 10 份训练文件
- **THEN** 页面提示「请先确认训练目标」
