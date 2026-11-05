# 2026 B题三人协作项目

本项目包含问题三本地模拟器、固定案例和A/B/C开发入口。
当前A/B/C仍为待实现入口，demo只用于流程验证；没有冒充完整策略。

## 开始使用

Windows在项目根目录打开cmd：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m unittest -v
.venv\Scripts\python.exe run.py --strategy strategies.demo --cases cases/case_000.json --out results/demo
```

没有第三方依赖。详细安装与物理假设见[模拟器说明](docs/SIMULATOR.md)。

## 三人分工

| 成员角色 | 目录 | 任务分支示例 |
|---|---|---|
| A负责人 | strategies/a/ | feat/a-coverage |
| B负责人 | strategies/b/ | feat/b-active-sensing |
| C负责人 | strategies/c/ | feat/c-optimizer |

每位成员用自己的GitHub账号和工作目录；共同使用同一个私有仓库。
成员代码只有commit、push后才上传；队友fetch/pull后才获得变化。
聊天记录不会因连接仓库而自动共享。分支和PR减少冲突，但不能保证完全没有冲突。

## 文档

- [新手协作步骤](docs/TEAM_START.md)
- [实验规范](docs/EXPERIMENTS.md)
- [任务清单](docs/TASKS.md)
- [AI工作规范](AGENTS.md)

## 自动测试

.github/workflows/tests.yml配置Windows与Linux、Python 3.10/3.12测试。
推送远端后由GitHub Actions实际执行。本地生成文件不等于远端CI已运行。
分支保护需要在GitHub设置中单独开启，当前未配置远端规则。
