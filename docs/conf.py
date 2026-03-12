# Sphinx 配置文件
import os
import sys
sys.path.insert(0, os.path.abspath('..'))

project = 'Oasyce Claw Plugin Engine'
copyright = '2026, Shangrila / Oasyce Project'
author = 'Shangrila'
release = '0.3.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.githubpages',
    'sphinx_autodoc_typehints',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_title = 'Oasyce Claw Plugin Engine'

# AutoDoc 配置
autodoc_member_order = 'bysource'
autodoc_typehints = 'description'
napoleon_google_docstring = True
napoleon_numpy_docstring = False
