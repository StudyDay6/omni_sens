"""自动更新模块 - 自动检查并更新集成代码"""
import asyncio
import logging
import aiohttp
import aiofiles
import json
import shutil
from pathlib import Path
from packaging import version
from typing import Optional, Tuple
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components import persistent_notification

_LOGGER = logging.getLogger(__name__)

# GitHub 仓库信息
GITHUB_REPO = "StudyDay6/ct_ble_devices"  # 修改为你的仓库
GITHUB_API_BASE = "https://api.github.com/repos"
CHECK_INTERVAL = timedelta(hours=24)  # 每24小时检查一次（测试用）
AUTO_UPDATE_ENABLED = True  # 是否启用自动更新


async def async_setup_auto_update(hass: HomeAssistant, entry: ConfigEntry) -> Optional['IntegrationUpdater']:
    """设置自动更新功能
    
    Args:
        hass: Home Assistant 实例
        entry: 配置条目
        
    Returns:
        IntegrationUpdater 实例，如果启用失败则返回 None
    """
    _LOGGER.info("初始化自动更新功能...")
    
    if not AUTO_UPDATE_ENABLED:
        _LOGGER.info("自动更新已禁用（AUTO_UPDATE_ENABLED=False）")
        return None
    
    try:
        # 获取当前版本
        # 在运行时，集成路径是 config/custom_components/ct_ble_devices/
        integration_path = Path(__file__).parent
        manifest_path = integration_path / "manifest.json"
        _LOGGER.debug("集成路径: %s", integration_path)
        _LOGGER.debug("Manifest 路径: %s", manifest_path)
        
        current_version = "1.0.0"
        
        if manifest_path.exists():
            _LOGGER.debug("读取 manifest.json...")
            with open(manifest_path) as f:
                manifest = json.load(f)
                current_version = manifest.get("version", "1.0.0")
                _LOGGER.info("从 manifest.json 读取到版本: %s", current_version)
        else:
            _LOGGER.warning("manifest.json 不存在，使用默认版本: %s", current_version)
        
        # 创建并启动更新器
        _LOGGER.info("创建 IntegrationUpdater 实例...")
        updater = IntegrationUpdater(hass, integration_path, current_version, entry.entry_id)
        _LOGGER.info("启动更新器...")
        await updater.start()
        
        _LOGGER.info("自动更新功能已启动")
        return updater
        
    except Exception as e:
        _LOGGER.error("启动自动更新失败: %s", e, exc_info=True)
        return None


class IntegrationUpdater:
    """集成自动更新器"""
    
    def __init__(self, hass: HomeAssistant, integration_path: Path, current_version: str, entry_id: Optional[str] = None):
        """初始化更新器"""
        self.hass = hass
        self.integration_path = integration_path
        self.current_version = current_version
        self.entry_id = entry_id
        self.last_check: Optional[datetime] = None
        self.update_task: Optional[asyncio.Task] = None
        self.auto_reload = True  # 是否自动重载集成
        
    async def start(self):
        """启动自动更新检查"""
        if not AUTO_UPDATE_ENABLED:
            _LOGGER.debug("自动更新已禁用")
            return
        
        _LOGGER.info("自动更新功能初始化中...")
        _LOGGER.info("当前版本: %s", self.current_version)
        _LOGGER.info("集成路径: %s", self.integration_path)
        _LOGGER.info("GitHub 仓库: %s", GITHUB_REPO)
        _LOGGER.info("检查间隔: %s", CHECK_INTERVAL)
        
        # 延迟启动，避免影响集成初始化
        _LOGGER.info("等待 60 秒后开始首次检查...")
        try:
            await asyncio.sleep(60)  # 等待60秒后开始检查
        except asyncio.CancelledError:
            _LOGGER.debug("启动延迟被取消（集成可能正在卸载）")
            return
        
        # 立即检查一次（启动时检查）
        _LOGGER.info("开始首次更新检查...")
        await self.check_and_update()
        
        # 启动定期检查任务
        self.update_task = self.hass.async_create_background_task(
            self._periodic_check(),
            "ct_ble_devices_auto_update"
        )
        _LOGGER.info("自动更新检查已启动（启动时已检查一次，之后每 %s 检查一次）", CHECK_INTERVAL)
    
    async def _periodic_check(self):
        """定期检查更新"""
        _LOGGER.info("定期检查任务已启动")
        while True:
            try:
                now = datetime.now()
                # 检查是否需要检查更新
                if self.last_check is None:
                    _LOGGER.info("首次定期检查，立即执行")
                    await self.check_and_update()
                    self.last_check = now
                else:
                    time_since_last = now - self.last_check
                    _LOGGER.debug("距离上次检查: %s，检查间隔: %s", time_since_last, CHECK_INTERVAL)
                    
                    if time_since_last > CHECK_INTERVAL:
                        _LOGGER.info("达到检查间隔，开始检查更新...")
                        await self.check_and_update()
                        self.last_check = now
                    else:
                        remaining = CHECK_INTERVAL - time_since_last
                        _LOGGER.debug("未到检查时间，还需等待: %s", remaining)
                
                # 等待一段时间后再次检查
                await asyncio.sleep(300)  # 每5分钟检查一次是否需要更新
                
            except asyncio.CancelledError:
                _LOGGER.info("自动更新任务被取消")
                break
            except Exception as e:
                _LOGGER.error("自动更新检查出错: %s", e, exc_info=True)
                await asyncio.sleep(300)  # 出错后等待5分钟再试
    
    async def check_and_update(self) -> bool:
        """检查并更新集成"""
        _LOGGER.info("=" * 60)
        _LOGGER.info("开始检查更新...")
        _LOGGER.info("当前版本: %s", self.current_version)
        
        try:
            _LOGGER.info("正在获取最新版本信息...")
            latest_version, download_url = await self._get_latest_version()
            
            if not latest_version:
                _LOGGER.warning("无法获取最新版本信息，可能原因：网络问题、仓库不存在、API 限制")
                return False
            
            _LOGGER.info("获取到最新版本: %s", latest_version)
            if download_url:
                _LOGGER.debug("下载 URL: %s", download_url)
            
            # 比较版本
            try:
                current_ver = version.parse(self.current_version)
                latest_ver = version.parse(latest_version)
                _LOGGER.info("版本比较: 当前=%s, 最新=%s", current_ver, latest_ver)
                
                if latest_ver <= current_ver:
                    _LOGGER.info("当前已是最新版本，无需更新")
                    return False
                
                _LOGGER.info("发现新版本！需要更新")
            except Exception as e:
                _LOGGER.error("版本比较失败: %s", e)
                return False
            
            _LOGGER.info(
                "发现新版本: %s (当前版本: %s)，开始自动更新...",
                latest_version,
                self.current_version
            )
            
            # 自动下载并更新
            if await self._download_and_update(download_url, latest_version):
                _LOGGER.info("集成已自动更新到版本: %s", latest_version)
                await self._notify_update_success(latest_version, reloaded=True)
                return True
            else:
                _LOGGER.error("自动更新失败")
                return False
                
        except Exception as e:
            _LOGGER.error("检查更新时出错: %s", e, exc_info=True)
            return False
        finally:
            _LOGGER.info("检查更新完成")
            _LOGGER.info("=" * 60)
    
    async def _get_latest_version(self) -> Tuple[Optional[str], Optional[str]]:
        """获取最新版本信息"""
        url = f"{GITHUB_API_BASE}/{GITHUB_REPO}/releases/latest"
        _LOGGER.debug("请求 GitHub API: %s", url)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    _LOGGER.debug("GitHub API 响应状态码: %d", response.status)
                    
                    if response.status == 200:
                        data = await response.json()
                        _LOGGER.debug("GitHub API 响应数据: %s", json.dumps(data, indent=2))
                        
                        latest_version = data.get("tag_name", "").lstrip("v")
                        _LOGGER.info("解析到版本标签: %s", data.get("tag_name"))
                        _LOGGER.info("处理后版本号: %s", latest_version)
                        
                        if not latest_version:
                            _LOGGER.warning("无法从响应中提取版本号")
                            return None, None
                        
                        # 获取下载 URL（ZIP 文件）
                        assets = data.get("assets", [])
                        _LOGGER.debug("找到 %d 个 Release 资源", len(assets))
                        
                        download_url = None
                        for asset in assets:
                            asset_name = asset.get("name", "")
                            _LOGGER.debug("检查资源: %s", asset_name)
                            if asset_name.endswith(".zip"):
                                download_url = asset.get("browser_download_url")
                                _LOGGER.info("找到 ZIP 资源: %s", asset_name)
                                break
                        
                        # 如果没有找到 ZIP，使用源码 ZIP
                        if not download_url:
                            download_url = f"https://github.com/{GITHUB_REPO}/archive/refs/tags/v{latest_version}.zip"
                            _LOGGER.info("使用源码 ZIP URL: %s", download_url)
                        
                        return latest_version, download_url
                    elif response.status == 404:
                        _LOGGER.warning("仓库或 Release 不存在 (404)，请检查仓库名和是否有 Release")
                        return None, None
                    else:
                        response_text = await response.text()
                        _LOGGER.warning("获取最新版本失败，状态码: %d，响应: %s", response.status, response_text[:200])
                        return None, None
                        
        except asyncio.TimeoutError:
            _LOGGER.error("获取最新版本超时（10秒）")
            return None, None
        except aiohttp.ClientError as e:
            _LOGGER.error("网络请求失败: %s", e)
            return None, None
        except Exception as e:
            _LOGGER.error("获取最新版本信息失败: %s", e, exc_info=True)
            return None, None
    
    async def _download_and_update(self, download_url: str, new_version: str) -> bool:
        """下载并更新集成"""
        import zipfile
        import tempfile
        
        _LOGGER.info("开始下载并更新流程...")
        _LOGGER.info("目标版本: %s", new_version)
        _LOGGER.info("下载 URL: %s", download_url)
        
        temp_dir = None
        try:
            # 创建临时目录
            temp_dir = Path(tempfile.mkdtemp())
            zip_path = temp_dir / "update.zip"
            _LOGGER.debug("临时目录: %s", temp_dir)
            _LOGGER.debug("ZIP 文件路径: %s", zip_path)
            
            # 下载 ZIP 文件
            _LOGGER.info("正在下载新版本...")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    download_url,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    _LOGGER.debug("下载响应状态码: %d", response.status)
                    if response.status != 200:
                        _LOGGER.error("下载失败，状态码: %d", response.status)
                        return False
                    
                    file_size = 0
                    async with aiofiles.open(zip_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                            file_size += len(chunk)
                    
                    _LOGGER.info("下载完成，文件大小: %d 字节 (%.2f MB)", file_size, file_size / 1024 / 1024)
            
            # 解压 ZIP 文件
            _LOGGER.info("正在解压新版本...")
            extract_dir = temp_dir / "extract"
            extract_dir.mkdir()
            _LOGGER.debug("解压目录: %s", extract_dir)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                _LOGGER.debug("ZIP 包含 %d 个文件/目录", len(file_list))
                _LOGGER.debug("ZIP 文件列表（前10个）: %s", file_list[:10])
                zip_ref.extractall(extract_dir)
            
            _LOGGER.info("解压完成")
            
            # 找到集成目录（HACS 标准结构：custom_components/ct_ble_devices/）
            extracted_path = None
            
            # 方式1：查找解压根目录下的 custom_components/ct_ble_devices/ 结构（HACS 标准）
            _LOGGER.debug("尝试查找 HACS 标准结构（根目录）...")
            custom_components_path = extract_dir / "custom_components" / "ct_ble_devices"
            _LOGGER.debug("检查路径: %s (存在: %s)", custom_components_path, custom_components_path.exists())
            if custom_components_path.exists():
                manifest_path = custom_components_path / "manifest.json"
                _LOGGER.debug("检查 manifest.json: %s (存在: %s)", manifest_path, manifest_path.exists())
                if manifest_path.exists():
                    extracted_path = custom_components_path
                    _LOGGER.info("找到 HACS 标准结构: custom_components/ct_ble_devices/")
            
            # 方式2：查找版本号前缀目录下的 custom_components/ct_ble_devices/（如 ct_ble_devices-1.0.1/custom_components/ct_ble_devices/）
            if not extracted_path:
                _LOGGER.debug("未找到根目录下的 HACS 结构，尝试查找版本号前缀目录...")
                items = list(extract_dir.iterdir())
                _LOGGER.debug("扫描解压目录，找到 %d 个项目", len(items))
                
                for item in items:
                    if item.is_dir() and "ct_ble_devices" in item.name.lower():
                        _LOGGER.debug("检查版本号目录: %s", item.name)
                        # 查找 custom_components/ct_ble_devices/ 结构
                        versioned_custom_components = item / "custom_components" / "ct_ble_devices"
                        _LOGGER.debug("检查路径: %s (存在: %s)", versioned_custom_components, versioned_custom_components.exists())
                        if versioned_custom_components.exists():
                            manifest_path = versioned_custom_components / "manifest.json"
                            _LOGGER.debug("检查 manifest.json: %s (存在: %s)", manifest_path, manifest_path.exists())
                            if manifest_path.exists():
                                extracted_path = versioned_custom_components
                                _LOGGER.info("找到版本号目录下的 HACS 结构: %s/custom_components/ct_ble_devices/", item.name)
                                break
            
            # 方式3：查找直接包含 manifest.json 的目录（兼容旧结构）
            if not extracted_path:
                _LOGGER.debug("未找到版本号目录下的 HACS 结构，尝试查找直接包含 manifest.json 的目录...")
                items = list(extract_dir.iterdir())
                for item in items:
                    if item.is_dir():
                        _LOGGER.debug("检查目录: %s", item.name)
                        # 检查是否是集成目录（包含 manifest.json）
                        if (item / "manifest.json").exists():
                            extracted_path = item
                            _LOGGER.info("找到集成目录: %s", item.name)
                            break
                        # 检查是否在子目录中（ct_ble_devices-1.0.0/ct_ble_devices/）
                        sub_integration = item / "ct_ble_devices"
                        if sub_integration.exists() and (sub_integration / "manifest.json").exists():
                            extracted_path = sub_integration
                            _LOGGER.info("找到嵌套集成目录: %s", sub_integration)
                            break
            
            if not extracted_path:
                _LOGGER.error("无法找到集成目录，请确保 ZIP 包含 custom_components/ct_ble_devices/ 或 ct_ble_devices/")
                _LOGGER.error("解压目录路径: %s", extract_dir)
                _LOGGER.error("解压目录内容:")
                try:
                    items = list(extract_dir.iterdir())
                    for item in items:
                        if item.is_dir():
                            _LOGGER.error("  目录: %s", item.name)
                            # 列出目录内容
                            try:
                                sub_items = list(item.iterdir())
                                for sub_item in sub_items[:10]:  # 只显示前10个
                                    if sub_item.is_dir():
                                        _LOGGER.error("    └─ 目录: %s", sub_item.name)
                                    else:
                                        _LOGGER.error("    └─ 文件: %s", sub_item.name)
                                if len(sub_items) > 10:
                                    _LOGGER.error("    ... 还有 %d 个项目", len(sub_items) - 10)
                            except Exception as e:
                                _LOGGER.error("    无法列出目录内容: %s", e)
                        else:
                            _LOGGER.error("  文件: %s", item.name)
                except Exception as e:
                    _LOGGER.error("无法列出解压目录内容: %s", e)
                
                # 尝试递归查找所有 manifest.json
                _LOGGER.info("尝试递归查找所有 manifest.json 文件...")
                try:
                    manifest_files = list(extract_dir.rglob("manifest.json"))
                    _LOGGER.info("找到 %d 个 manifest.json 文件:", len(manifest_files))
                    for manifest_file in manifest_files:
                        _LOGGER.info("  - %s (父目录: %s)", manifest_file, manifest_file.parent)
                except Exception as e:
                    _LOGGER.error("递归查找 manifest.json 失败: %s", e)
                
                return False
            
            _LOGGER.info("找到集成目录: %s", extracted_path)
            
            # 备份当前版本
            _LOGGER.info("开始备份当前版本...")
            backup_path = self.integration_path.parent / f"{self.integration_path.name}.backup"
            _LOGGER.debug("备份路径: %s", backup_path)
            if backup_path.exists():
                _LOGGER.debug("删除旧备份...")
                shutil.rmtree(backup_path)
            _LOGGER.debug("复制当前版本到备份目录...")
            shutil.copytree(self.integration_path, backup_path)
            _LOGGER.info("已备份当前版本到: %s", backup_path)
            
            # 更新文件（排除某些文件）
            _LOGGER.info("开始更新文件...")
            exclude_files = {'__pycache__', '.git', 'venv', '.backup', '*.pyc', '*.pyo'}
            file_count = 0
            excluded_count = 0
            for item in extracted_path.rglob('*'):
                if item.is_file():
                    file_count += 1
                    # 检查是否应该排除
                    should_exclude = False
                    for exclude in exclude_files:
                        if exclude in str(item):
                            should_exclude = True
                            break
                    
                    if should_exclude:
                        excluded_count += 1
                        _LOGGER.debug("排除文件: %s", item)
                        continue
                    
                    # 计算相对路径
                    rel_path = item.relative_to(extracted_path)
                    target_path = self.integration_path / rel_path
                    
                    # 创建目标目录
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # 复制文件
                    shutil.copy2(item, target_path)
                    _LOGGER.debug("更新文件: %s -> %s", rel_path, target_path)
            
            _LOGGER.info("文件更新完成: 共处理 %d 个文件，排除 %d 个文件", file_count, excluded_count)
            
            # 更新版本信息
            await self._update_version_info(new_version)
            
            # 自动重载集成
            if self.auto_reload and self.entry_id:
                _LOGGER.info("正在自动重载集成...")
                await asyncio.sleep(2)  # 等待文件系统同步
                try:
                    await self._reload_integration()
                    await self._notify_update_success(new_version, reloaded=True)
                except Exception as e:
                    _LOGGER.error("自动重载集成失败: %s", e, exc_info=True)
                    await self._notify_restart_required(new_version)
            else:
                # 无法自动重载，提示手动重启
                await self._notify_restart_required(new_version)
            
            return True
            
        except Exception as e:
            _LOGGER.error("下载和更新过程中出错: %s", e, exc_info=True)
            
            # 尝试恢复备份
            backup_path = self.integration_path.parent / f"{self.integration_path.name}.backup"
            if backup_path.exists():
                _LOGGER.warning("尝试恢复备份...")
                try:
                    if self.integration_path.exists():
                        shutil.rmtree(self.integration_path)
                    shutil.copytree(backup_path, self.integration_path)
                    _LOGGER.info("已恢复备份")
                except Exception as restore_error:
                    _LOGGER.error("恢复备份失败: %s", restore_error)
            
            return False
            
        finally:
            # 清理临时文件
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    _LOGGER.warning("清理临时文件失败: %s", e)
    
    async def _update_version_info(self, new_version: str):
        """更新版本信息"""
        try:
            manifest_path = self.integration_path / "manifest.json"
            if manifest_path.exists():
                async with aiofiles.open(manifest_path, 'r') as f:
                    content = await f.read()
                    manifest = json.loads(content)
                    manifest['version'] = new_version
                
                async with aiofiles.open(manifest_path, 'w') as f:
                    await f.write(json.dumps(manifest, indent=2))
                
                _LOGGER.info("版本信息已更新: %s", new_version)
        except Exception as e:
            _LOGGER.warning("更新版本信息失败: %s", e)
    
    async def _notify_update_success(self, new_version: str, reloaded: bool = False):
        """通知更新成功"""
        if reloaded:
            message = f"CT BLE Devices 已自动更新到版本 {new_version}，集成已自动重载。"
        else:
            message = f"CT BLE Devices 已自动更新到版本 {new_version}。\n请重启 Home Assistant 以应用更改。"
        
        persistent_notification.create(
            self.hass,
            message,
            "CT BLE Devices 自动更新",
            f"ct_ble_devices_update_{new_version}"
        )
    
    async def _notify_restart_required(self, new_version: str):
        """通知需要重启"""
        persistent_notification.create(
            self.hass,
            f"CT BLE Devices 已更新到版本 {new_version}。\n"
            "⚠️ 请重启 Home Assistant 以应用更改。",
            "CT BLE Devices 更新完成",
            "ct_ble_devices_restart_required"
        )
    
    async def _reload_integration(self):
        """自动重载集成"""
        if not self.entry_id:
            _LOGGER.warning("无法重载集成：entry_id 未设置")
            return False
        
        try:
            from homeassistant.config_entries import ConfigEntryState
            
            # 获取配置条目
            entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if not entry:
                _LOGGER.error("无法找到配置条目: %s", self.entry_id)
                return False
            
            # 检查条目状态
            if entry.state == ConfigEntryState.SETUP_IN_PROGRESS:
                _LOGGER.info("配置条目正在初始化中，延迟 10 秒后重试重载...")
                # 延迟重载，等待初始化完成
                await asyncio.sleep(10)
                # 重新检查状态
                entry = self.hass.config_entries.async_get_entry(self.entry_id)
                if not entry:
                    _LOGGER.error("延迟后无法找到配置条目: %s", self.entry_id)
                    return False
                if entry.state != ConfigEntryState.LOADED:
                    _LOGGER.warning("延迟后配置条目仍未加载，状态: %s，跳过自动重载", entry.state)
                    return False
            elif entry.state != ConfigEntryState.LOADED:
                _LOGGER.warning("配置条目未加载，无法重载: %s", entry.state)
                return False
            
            # 重载集成
            _LOGGER.info("开始重载集成: %s", self.entry_id)
            result = await self.hass.config_entries.async_reload(self.entry_id)
            
            if result:
                _LOGGER.info("集成重载成功")
                return True
            else:
                _LOGGER.error("集成重载失败")
                return False
                
        except Exception as e:
            _LOGGER.error("重载集成时出错: %s", e, exc_info=True)
            return False
    
    def stop(self):
        """停止自动更新"""
        if self.update_task:
            self.update_task.cancel()

