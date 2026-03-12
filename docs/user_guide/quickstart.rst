快速开始
========

5 分钟上手 Oasyce

步骤 1: 配置环境
---------------

.. code-block:: bash

   cp .env.example .env
   nano .env  # 编辑配置

必填配置:

.. code-block:: env

   OASYCE_VAULT_DIR=~/oasyce/genesis_vault
   OASYCE_OWNER=YourName
   OASYCE_SIGNING_KEY=your-secret-key
   OASYCE_SIGNING_KEY_ID=my_key_001

步骤 2: 注册文件
---------------

.. code-block:: bash

   oasyce register /path/to/file.pdf

步骤 3: 查询资产
---------------

.. code-block:: bash

   oasyce search Core
   oasyce quote OAS_XXXXXXXX
