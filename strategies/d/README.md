# D_JOINT_VIEWS

本分支的Q3实验候选，默认 `strategies.d.run` 和 `Controller(api)` 均使用该variant。
完整结果、几何证明和局限见根目录 `Q3_BREAKTHROUGH_REPORT.md`。

只需要Python 3.10及以上标准库；规划器只调用 `api.measure` 和 `api.clear`。
官方入口复用项目已有requests适配器。没有运行时真值、案例种子或随机参数。

```powershell
python run.py --strategy strategies.d --cases cases --out results/d_local
python experiments/run_breakthrough.py --generate 48 --cases cases_extra/breakthrough/validation --variants D_JOINT_VIEWS --out results/d_validation
```

`geometry.py`维护的是Q3物理先验与实际观测的保守交集。它与原Q1的纯bearing交集
是不同对象；没有修改或重新定义原Q1。清除必须有near证据或覆盖整个物理外包多边形
的半径小于20 m圆，实际API返回异常或合同矛盾时停止。

源码保留其他小原型供消融复现；应使用 `D_JOINT_VIEWS` 做下一次人工Q3演练。
`D_PURSUIT`等历史原型性能较差，不作为推荐入口。

官方演练必须由人工先在UI选择Q3演练，再设置账号环境变量并运行独立入口：

```powershell
python run_q3_breakthrough_official.py --variant D_JOINT_VIEWS --exercise
```

此文件不自动启动演练。不要把上述命令用于自动启动正式测试。
