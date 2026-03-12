安装指南
========

系统要求
--------

- Python 3.9 或更高版本
- pip 包管理器
- Git

从 GitHub 安装
--------------

.. code-block:: bash

   git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine.git
   cd Oasyce_Claw_Plugin_Engine
   python3 -m venv venv
   source venv/bin/activate
   pip install -e .

验证安装
--------

.. code-block:: bash

   python scripts/quickstart.py

如果看到 "✅ 所有检查通过"，说明安装成功。
