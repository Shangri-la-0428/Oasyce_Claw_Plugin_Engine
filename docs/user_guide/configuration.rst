配置指南
========

环境变量
--------

===================== =============================== ===================
变量名                说明                            默认值
===================== =============================== ===================
OASYCE_VAULT_DIR      数据账本目录                    ./genesis_vault
OASYCE_OWNER          资产所有者名称                  Shangrila
OASYCE_TAGS           默认标签（逗号分隔）            Core,Genesis
OASYCE_SIGNING_KEY    HMAC-SHA256 签名密钥           (必填)
OASYCE_SIGNING_KEY_ID 签名密钥标识符                  dev_key_001
OASYCE_LOG_LEVEL      日志级别                       INFO
OASYCE_LOG_FILE       日志文件路径                   (无)
===================== =============================== ===================

密钥管理
--------

开发环境可以使用示例密钥，**生产环境必须**:

1. 生成强随机密钥（至少 32 字符）
2. 存储到密码管理器（1Password / Keychain）
3. 绝不提交到 Git

生成密钥:

.. code-block:: bash

   python -c "import secrets; print(secrets.token_hex(32))"
