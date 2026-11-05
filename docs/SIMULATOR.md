# 问题三本地模拟器 v1.0

Python 3.10+，只用标准库，不需要pip。离线运行，不需官方账号。
这是本地物理测试工具，不是官方软件，不提供HTTP服务或正式日志。

## Windows启动

完整解压，进入包含run.py的文件夹，在资源管理器地址栏输入cmd并回车。
依次执行：

```bat
python --version
python -m venv .venv
.venv\Scripts\python.exe -m unittest -v
.venv\Scripts\python.exe run.py --strategy strategies.demo --cases cases/case_000.json --out results/demo_one
.venv\Scripts\python.exe run.py --strategy strategies.demo --cases cases --out results/demo_all
```

若python不可用，可用py -3.10 -m venv .venv。无需激活环境。
包内20个固定案例。新增案例：

```bat
.venv\Scripts\python.exe make_cases.py --count 100 --seed 5000 --out cases_extra
```

只生成一次，将整个cases文件夹发给队友，不要仅共享种子。

## 输出

summary.csv：清除比例、总虚拟秒数、平均清除时间、运行秒数、路程、动作次数、案例哈希。
environment.json：Python完整版本、系统、核心及策略代码哈希、命令。
每局jsonl：动作和可观测反馈。
演示策略很慢，只用于跑通流程，不代表方案A/B/C。
status=error或清除比例小于1，不能只凭平均时间评价。
运行秒数包含本地环境计算，不是纯策略时间，也不等于官方运行时间。

## 接入自己策略

复制strategies/template.py为strategies/strategy_b.py。修改run(api, seed=0)。
只调用api.measure((x,y),channel)与api.clear((x,y),channel)。
measure_result有no_signal/near/direction，只有direction返回svd_deg。
clear_result有success/no_target_in_range。两者返回virtual_time_s。
run返回后框架自动退出、评分；不要自行读取目标真值。

```bat
.venv\Scripts\python.exe run.py --strategy strategies.strategy_b --cases cases --out results/B
```

A/C使用同样接口，输出不同目录。C可用random.Random(seed)独立生成策略随机数。
--seed设置策略种子，不修改固定案例。随机策略需多种子重复，报告分布。
RobotAPI是接口分离，不是防恶意读取的安全沙箱；禁止读取cases文件或内部属性。

## 题目规则与自主假设

实现：全向源、每频道最多一个、1000至1500米接收半径、5米near、20米清除。
速度5米/秒；检测5秒；换频道1秒；清除失败3秒、成功5秒。
clear不改变测向频道。初始原点、频道1。允许走出目标圆，坐标分量上限2000000。
清除后同频道无信号。无须sleep。设本地动作数、1200秒运行及100小时虚拟限额。
不实现官方登录、HTTP幂等重试或25分钟测试窗口。

自主误差模型：每频道每1米网格内的误差由SHA256确定，固定在[-1,1]度内。
同地点不重采样，不依赖策略调用顺序。随后round到两位小数并归一化。
这不是官方误差模型；后续应改变误差空间尺度/模型检验鲁棒性。
案例包含均匀面积、靠边、聚集、最小接收半径四类，均为自主测试设计。
目标真值、接收半径、误差种子只给环境，不给策略。B模型不应据此假定后验均匀。

## B策略开发顺序

维护每频道观测与保守区域；用20米覆盖条件判断可清除；选较近可靠清除点；
否则生成接近/侧向补测点，以动作时间加近似后续时间比较；每一步反馈后重算。
模板仅原点扫描，不包含完整B求解器。自建环境验证不能代替官方演练。

## 公平比较与兼容

统一JSON案例、模拟器规则和代码、策略随机种子、未来依赖版本。
先看清除比例，再对全部清除案例配对比较虚拟时间；两台电脑的运行时间不直接排名。
浮点边界可能改变决策分支，不能保证跨平台逐位一致。
交付在Python 3.12执行测试，并做3.10语法检查；本机务必先运行单元测试。
