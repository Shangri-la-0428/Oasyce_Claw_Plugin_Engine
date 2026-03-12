"""
IPFS 可插拔存储客户端

支持多种存储后端：
- LocalStorage: 本地文件系统（默认）
- IPFS: IPFS 分布式存储（需运行 IPFS 节点）
- Custom: 自定义存储后端（实现 StorageBackend 接口即可）

设计原则：
- 接口统一：所有后端实现相同的 upload/download/pin 接口
- 无缝切换：通过配置切换存储后端，上层代码无需修改
- 渐进式升级：当前使用 LocalStorage，未来可平滑迁移到 IPFS
"""

import os
import json
import shutil
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pathlib import Path


class StorageBackend(ABC):
    """存储后端抽象基类，所有存储实现必须继承此类"""
    
    @abstractmethod
    def upload(self, file_path: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        上传文件到存储后端
        
        Returns:
            {
                "cid": str,  # 内容标识符（IPFS）或文件路径（Local）
                "size": int,  # 文件大小
                "backend": str,  # 后端类型
                "metadata": dict,  # 元数据
            }
        """
        pass
    
    @abstractmethod
    def download(self, cid: str, dest_path: str) -> Dict[str, Any]:
        """
        从存储后端下载文件
        
        Returns:
            {
                "success": bool,
                "dest_path": str,
                "size": int,
            }
        """
        pass
    
    @abstractmethod
    def pin(self, cid: str) -> Dict[str, Any]:
        """
        固定文件（防止被 GC 回收）
        IPFS 专用，LocalStorage 可为空实现
        """
        pass
    
    @abstractmethod
    def unpin(self, cid: str) -> Dict[str, Any]:
        """
        取消固定文件
        IPFS 专用，LocalStorage 可为空实现
        """
        pass


class LocalStorage(StorageBackend):
    """本地文件存储后端（默认实现）"""
    
    def __init__(self, storage_dir: str):
        """
        初始化本地存储
        
        Args:
            storage_dir: 存储目录路径
        """
        self.storage_dir = Path(storage_dir).expanduser()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def upload(self, file_path: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        src = Path(file_path).expanduser()
        if not src.exists():
            return {"success": False, "error": f"File not found: {file_path}"}
        
        # 生成 CID（使用文件路径的哈希作为模拟 CID）
        import hashlib
        file_hash = hashlib.sha256(str(src.resolve()).encode()).hexdigest()[:16]
        cid = f"local_{file_hash}"
        
        # 复制到存储目录
        dest = self.storage_dir / f"{cid}_{src.name}"
        shutil.copy2(src, dest)
        
        size = dest.stat().st_size
        
        return {
            "success": True,
            "cid": cid,
            "size": size,
            "backend": "local",
            "storage_path": str(dest),
            "metadata": metadata or {},
        }
    
    def download(self, cid: str, dest_path: str) -> Dict[str, Any]:
        # 在存储目录中查找文件
        for file in self.storage_dir.iterdir():
            if file.name.startswith(cid):
                shutil.copy2(file, dest_path)
                return {
                    "success": True,
                    "dest_path": dest_path,
                    "size": file.stat().st_size,
                }
        
        return {"success": False, "error": f"CID not found: {cid}"}
    
    def pin(self, cid: str) -> Dict[str, Any]:
        # LocalStorage 不需要 pin，文件天然持久化
        return {"success": True, "message": "LocalStorage does not require pinning"}
    
    def unpin(self, cid: str) -> Dict[str, Any]:
        # LocalStorage 不支持 unpin（删除文件请直接调用 os.remove）
        return {"success": False, "error": "LocalStorage does not support unpin"}


class IPFSClient:
    """
    IPFS 客户端（支持可插拔存储后端）
    
    用法：
        # 使用本地存储（默认）
        client = IPFSClient(storage_type="local", storage_dir="~/oasyce/storage")
        
        # 使用 IPFS（需运行 IPFS 节点）
        client = IPFSClient(storage_type="ipfs", ipfs_host="127.0.0.1", ipfs_port=5001)
    """
    
    def __init__(
        self,
        storage_type: str = "local",
        storage_dir: Optional[str] = None,
        ipfs_host: str = "127.0.0.1",
        ipfs_port: int = 5001,
        ipfs_api: str = "/api/v0",
    ):
        """
        初始化 IPFS 客户端
        
        Args:
            storage_type: 存储类型 ("local" | "ipfs" | "custom")
            storage_dir: 本地存储目录（storage_type="local" 时使用）
            ipfs_host: IPFS 节点主机（storage_type="ipfs" 时使用）
            ipfs_port: IPFS 节点端口（storage_type="ipfs" 时使用）
            ipfs_api: IPFS API 路径
        """
        self.storage_type = storage_type
        
        if storage_type == "local":
            if not storage_dir:
                storage_dir = "~/.oasyce/storage"
            self.backend: StorageBackend = LocalStorage(storage_dir)
        elif storage_type == "ipfs":
            self.backend = self._init_ipfs_backend(ipfs_host, ipfs_port, ipfs_api)
        else:
            raise ValueError(f"Unknown storage_type: {storage_type}. Use 'local', 'ipfs', or 'custom'.")
    
    def _init_ipfs_backend(self, host: str, port: int, api_path: str) -> StorageBackend:
        """初始化 IPFS 后端（如果 ipfshttpclient 可用）"""
        try:
            import ipfshttpclient
            
            class IPFSBackend(StorageBackend):
                def __init__(self, host: str, port: int, api_path: str):
                    self.client = ipfshttpclient.connect(f"/dns/{host}/tcp/{port}/http")
                    self.api_path = api_path
                
                def upload(self, file_path: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
                    try:
                        result = self.client.add(file_path, pin=True)
                        cid = result["Hash"]
                        size = result["Size"]
                        return {
                            "success": True,
                            "cid": cid,
                            "size": size,
                            "backend": "ipfs",
                            "metadata": metadata or {},
                        }
                    except Exception as e:
                        return {"success": False, "error": str(e)}
                
                def download(self, cid: str, dest_path: str) -> Dict[str, Any]:
                    try:
                        self.client.get(cid, target=dest_path)
                        size = os.path.getsize(dest_path)
                        return {
                            "success": True,
                            "dest_path": dest_path,
                            "size": size,
                        }
                    except Exception as e:
                        return {"success": False, "error": str(e)}
                
                def pin(self, cid: str) -> Dict[str, Any]:
                    try:
                        self.client.pin.add(cid)
                        return {"success": True, "cid": cid}
                    except Exception as e:
                        return {"success": False, "error": str(e)}
                
                def unpin(self, cid: str) -> Dict[str, Any]:
                    try:
                        self.client.pin.rm(cid)
                        return {"success": True, "cid": cid}
                    except Exception as e:
                        return {"success": False, "error": str(e)}
            
            return IPFSBackend(host, port, api_path)
        except ImportError:
            # 如果 ipfshttpclient 未安装，降级到 LocalStorage
            print("⚠️  Warning: ipfshttpclient not installed. Falling back to LocalStorage.")
            print("   Install with: pip install ipfshttpclient")
            return LocalStorage("~/.oasyce/storage")
    
    def upload(self, file_path: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """上传文件到存储后端"""
        return self.backend.upload(file_path, metadata)
    
    def download(self, cid: str, dest_path: str) -> Dict[str, Any]:
        """从存储后端下载文件"""
        return self.backend.download(cid, dest_path)
    
    def pin(self, cid: str) -> Dict[str, Any]:
        """固定文件"""
        return self.backend.pin(cid)
    
    def unpin(self, cid: str) -> Dict[str, Any]:
        """取消固定文件"""
        return self.backend.unpin(cid)
    
    def register_asset_with_storage(
        self,
        file_path: str,
        metadata: Dict[str, Any],
        vault_path: str,
    ) -> Dict[str, Any]:
        """
        注册资产并存储到后端
        
        流程：
        1. 上传文件到存储后端
        2. 将 CID 添加到 metadata
        3. 保存 metadata 到 vault
        
        Returns:
            {
                "success": bool,
                "asset_id": str,
                "cid": str,
                "storage_backend": str,
                "vault_path": str,
            }
        """
        # 1. 上传文件
        upload_result = self.upload(file_path, metadata)
        if not upload_result.get("success"):
            return {"success": False, "error": upload_result.get("error")}
        
        cid = upload_result["cid"]
        
        # 2. 添加 CID 到 metadata
        metadata["storage_cid"] = cid
        metadata["storage_backend"] = self.storage_type
        
        # 3. 保存到 vault
        asset_id = metadata.get("asset_id")
        if not asset_id:
            return {"success": False, "error": "Missing asset_id in metadata"}
        
        vault_path = Path(vault_path).expanduser()
        vault_path.mkdir(parents=True, exist_ok=True)
        
        vault_file = vault_path / f"{asset_id}.json"
        with open(vault_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        
        return {
            "success": True,
            "asset_id": asset_id,
            "cid": cid,
            "storage_backend": self.storage_type,
            "vault_path": str(vault_file),
            "upload_result": upload_result,
        }
