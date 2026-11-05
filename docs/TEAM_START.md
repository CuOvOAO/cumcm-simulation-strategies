# 从零开始三人协作

## 仓库管理员

1. 在GitHub创建私有仓库cumcm-2026-b-team，可勾选初始化README，确保存在默认分支。
2. 把仓库网址交给当前助手继续导入本项目。不要把ZIP当作源代码直接上传。
3. 确认文件已经导入后，在Settings的Collaborators中邀请两位队友的准确GitHub用户名。
4. main应要求通过PR合并、至少一位其他成员评审、测试通过、禁止强制推送。
5. 私有仓库的保护分支能力受GitHub套餐限制；若界面不支持，先由团队按规则人工执行，不要为了保护分支改成公开。

## 每位成员开始

电脑需安装Git，使用各自账号登录GitHub。命令中的占位地址换成真实仓库地址。

```bat
git clone https://github.com/OWNER/cumcm-2026-b-team.git
cd cumcm-2026-b-team
python -m venv .venv
.venv\Scripts\python.exe -m unittest -v
git switch -c feat/b-active-sensing
```

A与C负责人分别换成feat/a-coverage、feat/c-optimizer。
未配置Git提交身份时设置自己的user.name和user.email，不要复制队友身份。
首次push需要按Git安装环境的凭据管理器完成登录；不要在聊天中发送密码或token。

## 每个任务

1. 开始新任务前保证当前改动已提交或妥善保留；从更新后的main创建新任务分支。
2. 在你使用的AI开发工具中打开克隆的项目文件夹。任务开始明确要求读取AGENTS.md。
3. 只提交本任务文件，不使用git add .收集无关改动。
4. 运行测试，写清验证案例及结果，再提交推送。

```bat
git status
git add strategies/b
git commit -m "feat: implement B candidate actions"
git push -u origin feat/b-active-sensing
```

5. 打开GitHub仓库，选择Compare & pull request，目标分支main，按模板填写。
6. 另一位成员看差异和测试结果、提出修改或批准；约定管理员完成合并。
7. 下个任务从更新后的main创建新分支，不重复使用已合并的长期分支。

```bat
git switch main
git pull --ff-only origin main
git switch -c feat/b-next-task
```

出现冲突时保留双方逻辑，协调共享文件负责人，不用强制覆盖解决。
GitHub Projects看板不是此流程必需；仓库、Issue和PR足够开始协作。

## 给AI的一条任务指令

请先读取AGENTS.md和docs/EXPERIMENTS.md，检查当前分支与未提交改动。
本任务只实现方案B的候选动作生成，工作在feat/b-candidate-actions分支。
不读取环境真值、不改变模拟器规则、不直接提交main。
完成必要测试，给出可评审的变更与PR说明，不自动合并。
