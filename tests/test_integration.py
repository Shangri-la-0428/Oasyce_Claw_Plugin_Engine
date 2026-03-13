"""
Oasyce 集成测试 - 模拟真实用户工作流

测试整个系统的端到端集成，包括 CLI、SDK、和文件系统交互。
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

import pytest

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills
from oasyce_plugin.crypto import generate_keypair


class TestUserWorkflows:
    """真实用户工作流测试。"""
    
    @pytest.fixture
    def temp_vault(self):
        """创建临时账本目录。"""
        vault = tempfile.mkdtemp()
        yield vault
        shutil.rmtree(vault, ignore_errors=True)
    
    @pytest.fixture
    def test_files(self):
        """创建测试文件。"""
        files = {}
        temp_dir = tempfile.mkdtemp()
        
        # PDF 模拟
        pdf_path = Path(temp_dir) / "whitepaper.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% Oasyce Test PDF")
        files['pdf'] = str(pdf_path)
        
        # Markdown 文件
        md_path = Path(temp_dir) / "README.md"
        md_path.write_text("# Oasyce Test\n\nThis is a test.")
        files['markdown'] = str(md_path)
        
        # 大文件（测试流式哈希）
        large_path = Path(temp_dir) / "large_file.bin"
        with open(large_path, 'wb') as f:
            for i in range(1000):  # ~1MB
                f.write(os.urandom(1024))
        files['large'] = str(large_path)
        
        yield files
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def skills(self, temp_vault):
        """初始化 OasyceSkills。"""
        priv_hex, pub_hex = generate_keypair()
        config = Config.from_env(
            vault_dir=temp_vault,
            owner="TestUser",
            signing_key=priv_hex,
            public_key=pub_hex,
            signing_key_id="test_001"
        )
        return OasyceSkills(config)
    
    def test_workflow_register_pdf(self, skills, test_files):
        """工作流：注册 PDF 文件。"""
        # 注册
        file_info = skills.scan_data_skill(test_files['pdf'])
        metadata = skills.generate_metadata_skill(file_info, ["Whitepaper"], "TestUser")
        signed = skills.create_certificate_skill(metadata)
        result = skills.register_data_asset_skill(signed)
        
        # 验证
        assert 'asset_id' in signed
        assert signed['asset_id'].startswith('OAS_')
        assert result['status'] == 'success'
        
        # 检查账本文件存在
        vault_file = Path(result['vault_path'])
        assert vault_file.exists()
        
        # 验证 JSON 内容
        with open(vault_file) as f:
            stored = json.load(f)
        assert stored['asset_id'] == signed['asset_id']
        assert stored['popc_signature'] is not None
    
    def test_workflow_batch_register(self, skills, test_files):
        """工作流：批量注册多个文件。"""
        asset_ids = []
        
        for file_type, file_path in test_files.items():
            info = skills.scan_data_skill(file_path)
            meta = skills.generate_metadata_skill(info, ["Batch", "Test"], "TestUser")
            signed = skills.create_certificate_skill(meta)
            skills.register_data_asset_skill(signed)
            asset_ids.append(signed['asset_id'])
        
        # 验证所有资产都注册成功
        assert len(asset_ids) == 3
        for asset_id in asset_ids:
            assert asset_id.startswith('OAS_')
    
    def test_workflow_search_and_verify(self, skills, test_files):
        """工作流：注册后搜索和验证。"""
        # 注册
        file_info = skills.scan_data_skill(test_files['markdown'])
        metadata = skills.generate_metadata_skill(file_info, ["SearchTest"], "TestUser")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)
        
        # 搜索
        assets = skills.search_data_skill("SearchTest")
        assert len(assets) > 0
        
        # 验证找到的资产包含我们的文件
        found_ids = [a['asset_id'] for a in assets]
        assert signed['asset_id'] in found_ids
    
    def test_workflow_l2_pricing(self, skills, test_files):
        """工作流：L2 定价查询。"""
        # 注册
        file_info = skills.scan_data_skill(test_files['pdf'])
        metadata = skills.generate_metadata_skill(file_info, ["PricingTest"], "TestUser")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)
        
        # 查询价格
        quote = skills.trade_data_skill(signed['asset_id'])
        
        # 验证报价格式
        assert 'current_price_oas' in quote
        assert isinstance(quote['current_price_oas'], (int, float))
        assert quote['current_price_oas'] > 0
    
    def test_workflow_large_file(self, skills, test_files):
        """工作流：大文件注册（测试流式哈希）。"""
        import time
        
        start = time.time()
        file_info = skills.scan_data_skill(test_files['large'])
        duration = time.time() - start
        
        # 验证大文件处理成功
        assert file_info['file_hash'] is not None
        assert file_info['size'] > 1000000  # > 1MB
        
        # 应该在 2 秒内完成（性能要求）
        assert duration < 2.0, f"大文件哈希太慢：{duration:.2f}s"


class TestEdgeCases:
    """边界情况和错误处理测试。"""
    
    @pytest.fixture
    def skills(self):
        """初始化 OasyceSkills。"""
        priv_hex, pub_hex = generate_keypair()
        config = Config.from_env(
            vault_dir=tempfile.mkdtemp(),
            owner="TestUser",
            signing_key=priv_hex,
            public_key=pub_hex,
            signing_key_id="test_001"
        )
        return OasyceSkills(config)
    
    def test_nonexistent_file(self, skills):
        """测试：不存在的文件。"""
        with pytest.raises(RuntimeError, match="Path not found"):
            skills.scan_data_skill("/nonexistent/file.pdf")
    
    def test_empty_file(self, skills):
        """测试：空文件。"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_file = f.name
        
        try:
            result = skills.scan_data_skill(temp_file)
            assert result['file_hash'] is not None
            assert result['size'] == 0
        finally:
            os.unlink(temp_file)
    
    def test_duplicate_registration(self, skills):
        """测试：重复注册同一文件。"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Test content")
            temp_file = f.name
        
        try:
            # 第一次注册
            info1 = skills.scan_data_skill(temp_file)
            meta1 = skills.generate_metadata_skill(info1, ["Test"], "TestUser")
            signed1 = skills.create_certificate_skill(meta1)
            skills.register_data_asset_skill(signed1)
            
            # 第二次注册（应该生成相同 asset_id）
            info2 = skills.scan_data_skill(temp_file)
            meta2 = skills.generate_metadata_skill(info2, ["Test"], "TestUser")
            signed2 = skills.create_certificate_skill(meta2)
            skills.register_data_asset_skill(signed2)
            
            # asset_id 应该相同（因为哈希相同）
            assert signed1['asset_id'] == signed2['asset_id']
        finally:
            os.unlink(temp_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
