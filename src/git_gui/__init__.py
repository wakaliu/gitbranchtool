"""Git 拉线切线工具主包。

严格遵循分层架构：
- config: 配置管理
- models: 数据模型
- core: 业务逻辑 (Git 操作核心)
- ui: 界面层 (仅负责展示和事件转发)
- utils: 通用工具函数

所有可配置项统一通过 config/settings.py 加载。
"""
