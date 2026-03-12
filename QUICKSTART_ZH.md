# 🦎 Oasyce 插件 - 简单说明

> **给非技术人员：5 分钟看懂这是什么、怎么用**

---

## 🤔 这是什么？

想象一下，你写了一篇很棒的文章、拍了一组很美的照片、或者做了一份重要的报告——这些都是你的**数字资产**。

但是在 AI 时代，有个问题：
> ❓ AI 可以随意复制、使用你的作品，而你**拿不到报酬**，也**无法阻止**

**Oasyce 插件就是解决这个问题的。**

---

## 🎯 它能帮你做什么？

### 1️⃣ **给你的文件盖上"数字印章"**
就像给艺术品盖收藏章一样，Oasyce 给你的文件生成一个独一无二的数字指纹（哈希值），证明：
- ✅ 这是你的原创作品
- ✅ 什么时候创作的
- ✅ 谁拥有它

### 2️⃣ **防止 AI 随意偷用**
当 AI 想读取你的文件时，Oasyce 会拦截并问：
> 🛑 "你经过允许了吗？付钱了吗？"

没有授权，AI 就看不了。

### 3️⃣ **自动定价收费**
你可以设置："想看我这份文件？可以，付 10 个 OAS 代币。"
看的人越多，价格会自动调整（类似滴滴打车的动态定价）。

---

## 🧩 谁需要这个？

| 你是... | 能帮你... |
|--------|----------|
| 📝 **作家/博主** | 保护文章不被 AI 免费爬取 |
| 📸 **摄影师** | 给照片确权，按次收费 |
| 🎨 **设计师** | 防止设计稿被偷用 |
| 📊 **分析师** | 研报付费阅读 |
| 🎵 **音乐人** | 音乐作品版权管理 |
| 💼 **企业** | 内部文档访问控制 |

**简单说**：只要你有**原创内容**，又怕被 AI 白嫖，就需要这个。

---

## 🚀 怎么用？（3 步搞定）

### 前提条件
- 你已经安装了 OpenClaw（一个 AI 助手框架）
- 你有 macOS 或 Linux 电脑

### 第 1 步：安装

打开终端（Terminal），输入：

```bash
# 1. 下载
git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine.git
cd Oasyce_Claw_Plugin_Engine

# 2. 安装
pip install -e .
```

### 第 2 步：配置

```bash
# 1. 复制配置模板
cp .env.example .env

# 2. 编辑配置（用记事本打开 .env 文件）
nano .env
```

在文件里填入：
```
OASYCE_VAULT_DIR=~/oasyce/genesis_vault
OASYCE_OWNER=你的名字
OASYCE_SIGNING_KEY=你的密钥（稍后生成）
```

> 💡 **密钥怎么来？** 运行这个命令自动生成：
> ```bash
> python scripts/quickstart.py
> ```
> 按提示操作就行！

### 第 3 步：使用

#### 方式 A：用命令行（推荐）

```bash
# 给文件盖章
oasyce register ~/Desktop/我的文章.pdf

# 查看你有哪些资产
oasyce search Core

# 看看别人要付多少钱才能看
oasyce quote OAS_XXXXXX
```

#### 方式 B：用 Python 代码

如果你是开发者：
```python
from oasyce_plugin.skills.agent_skills import OasyceSkills

skills = OasyceSkills()
skills.scan_data_skill("我的文件.pdf")
```

#### 方式 C：直接跟 AI 说

如果你用 OpenClaw，直接说：
> "帮我把桌面上的白皮书用 Oasyce 确权"

AI 会自动帮你搞定！

---

## ✅ 验证是否成功

运行这个命令：
```bash
python scripts/quickstart.py
```

看到 **"✅ 所有检查通过"** 就对了！

---

## 📋 常见问答

### Q: 这玩意儿收费吗？
A: 插件本身**免费**。你要付的"OAS 代币"是你向别人收的，不是给我的。

### Q: 安全吗？密钥丢了怎么办？
A: 
- 密钥存在你的电脑本地，不会上传
- 建议把密钥抄在纸上锁保险柜（认真脸）
- 丢了就真的找不回来了（去中心化的代价）

### Q: 我的文件会被上传到网上吗？
A: **不会**。文件存在你电脑本地，只有"数字指纹"（哈希值）会被记录。

### Q: 别人怎么付钱看我的文件？
A: 目前还是演示阶段，用的是模拟代币。真实支付功能开发中...

### Q: 听起来很复杂，我学不会怎么办？
A: 跟着上面的"3 步搞定"走，每一步都复制粘贴命令就行。卡住了就提 issue 问我！

---

## 🆘 遇到问题？

### 安装失败
```bash
# 检查 Python 版本（需要 3.9 或更高）
python --version

# 升级 pip
pip install --upgrade pip

# 重新安装
pip install -e .
```

### 说找不到命令
```bash
# 确保激活了虚拟环境
source venv/bin/activate

# 或者直接运行
python -m oasyce_plugin.cli register 文件.pdf
```

### 其他问题
1. 查看 [完整文档](docs/)
2. 看 [GitHub Issues](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues)
3. 提新 issue 问我

---

## 🎓 进阶阅读（可选）

想深入了解原理？看这些：
- [技术架构说明](docs/user_guide/)
- [API 文档](docs/api/)
- [白皮书](https://github.com/Shangri-la-0428/Oasyce_Project)

---

## 💡 小结

**Oasyce 插件 = 你的数字资产保镖**

1. **盖章确权** - 证明"这是我的"
2. **拦截白嫖** - AI 想看？先付钱
3. **自动定价** - 越多人看越贵

**5 分钟安装，一辈子保护你的原创作品。**

---

<div align="center">

**🌱 让数据回归用户，让价值流动起来**

[GitHub 仓库](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine) • [提问题](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues)

</div>
