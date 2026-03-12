Oasyce Claw Plugin Engine 文档
================================

.. toctree::
   :maxdepth: 2
   :caption: 用户指南

   user_guide/installation
   user_guide/quickstart
   user_guide/configuration

.. toctree::
   :maxdepth: 2
   :caption: API 参考

   api/oasyce_plugin.config
   api/oasyce_plugin.skills
   api/oasyce_plugin.engines
   api/oasyce_plugin.cli

.. toctree::
   :maxdepth: 2
   :caption: 开发指南

   development/contributing
   development/changelog

用户指南
========

安装
----

.. code-block:: bash

   git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine.git
   cd Oasyce_Claw_Plugin_Engine
   pip install -e .

快速开始
--------

.. code-block:: python

   from oasyce_plugin.config import Config
   from oasyce_plugin.skills.agent_skills import OasyceSkills

   config = Config.from_env()
   skills = OasyceSkills(config)
   
   result = skills.scan_data_skill("/path/to/file.pdf")
   print(result)

命令行使用
----------

.. code-block:: bash

   oasyce register file.pdf --owner "Alice" --tags "Core"
   oasyce search Core
   oasyce quote OAS_6596A36F


索引和表格
==========

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
