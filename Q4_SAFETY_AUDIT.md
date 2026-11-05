# Q4 Safety Audit

候选：Q4_FORK_VIEWS，hash见experiments/q4_candidate_freeze.json。审计脚本experiments/audit_q4.py。

600运行，7756源次全部清除，220138动作，6712次fork负裁剪，独立50位重放失败0。

|检查|结果|
|---|---|
|真实源遗漏 / 错误排除|0 / 0|
|无证clear / failed clear|0 / 0|
|合同错误 / 时间账本冲突|0 / 0|
|truth不在保守域|0|
|positive/near清除证书独立重建|7756通过|
|未知频道完整可见性覆盖或16源上限|通过|
|运行时API访问|仅measure、clear|
|冻结Q1/Q2、Q3、D、原simulator、固定cases|未改|
|项目Python3.12端到端复跑|128/128，mean567.501；跨版本轨迹有数值平局差异|
|单元测试|22+74通过|

审计不采用控制器polygon；fork见证核验anchor真实正反馈、真实两次相邻no_signal、两点位置与range不等式后才加入负半平面。near证明距离≤5；否则整个外包集合在20米圆内。概率和估计点从未授权clear。

数值仍依赖libm三角函数和float外扩；Decimal为独立高精度复核，不是完整区间证明。40轮局部上限失败时停止，不假报完成；验证中未触发。压力四场重复同64布局，不能当256独立样本。

性能限制：独立验证总体mean566.665，但edge_outward mean756.519、10源mean约710；安全全清不意味着所有布局性能达标。官方演练尚待用户人工启动。
