#API_KEY = "sk-ws-H.EILEEHY.2lbD.MEUCIQCNP1wDT1N2lQ2F8JEjhzGMg5MfhmCwjv5zfgL4WBSrTgIgQbtdwY9_QgYYyDA9Kr0Zo-YGuoMdBgykvRBRJBDBD0A"  # ← 改成你的阿里云百炼 API Key
#MCP_URL = "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp"


import os
import sys
from dotenv import load_dotenv

# ============================================
# 1. 和 search_web_node.py 一样的方式加载
# ============================================
load_dotenv()  # 和节点中一样

print("=" * 70)
print("配置读取测试（使用节点相同的方式）")
print("=" * 70)

# ============================================
# 2. 方式一：从 os.getenv 读取（节点中也用这个）
# ============================================
print("\n【方式一：os.getenv() 直接读取】")
print("-" * 70)

api_key_env = os.getenv("OPENAI_API_KEY")
mcp_url_env = os.getenv("MCP_DASHSCOPE_BASE_URL")

print(f"OPENAI_API_KEY          = {api_key_env[:20] if api_key_env else '❌ 未找到'}...")
print(f"MCP_DASHSCOPE_BASE_URL  = {mcp_url_env if mcp_url_env else '❌ 未找到'}")
print(f"OPENAI_API_KEY 是否为空: {api_key_env is None or api_key_env == ''}")
print(f"MCP_URL 是否为空:        {mcp_url_env is None or mcp_url_env == ''}")

# ============================================
# 3. 方式二：从 config 对象读取（节点也这样用）
# ============================================
print("\n【方式二：config 对象读取】")
print("-" * 70)

try:
    from knowledge.processor.query_process.config import get_config

    config = get_config()

    api_key_config = config.openai_api_key
    mcp_url_config = config.mcp_dashscope_base_url

    print(f"config.openai_api_key          = {api_key_config[:20] if api_key_config else '❌ 未找到'}...")
    print(f"config.mcp_dashscope_base_url  = {mcp_url_config if mcp_url_config else '❌ 未找到'}")
    print(f"config.openai_api_key 是否为空: {api_key_config is None or api_key_config == ''}")
    print(f"config.mcp_url 是否为空:        {mcp_url_config is None or mcp_url_config == ''}")

    # 打印 config 对象的其他信息
    print(f"\nconfig 对象类型: {type(config)}")
    print(f"config 所有属性: {[attr for attr in dir(config) if not attr.startswith('_')]}")

except ImportError as e:
    print(f"❌ 导入 get_config 失败: {e}")
    api_key_config = None
    mcp_url_config = None
except Exception as e:
    print(f"❌ 读取 config 失败: {e}")
    api_key_config = None
    mcp_url_config = None

# ============================================
# 4. 方式三：查看 .env 文件内容
# ============================================
print("\n【方式三：检查 .env 文件】")
print("-" * 70)

env_file_path = os.path.join(os.getcwd(), ".env")
if os.path.exists(env_file_path):
    print(f"✅ .env 文件存在: {env_file_path}")
    with open(env_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        # 只显示非空行
        lines = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]
        for line in lines:
            if '=' in line:
                key, value = line.split('=', 1)
                if 'KEY' in key.upper():
                    print(f"  {key} = {value[:20]}..." if len(value) > 20 else f"  {key} = {value}")
                else:
                    print(f"  {line}")
else:
    print(f"❌ .env 文件不存在: {env_file_path}")
    print(f"   当前目录: {os.getcwd()}")

# ============================================
# 5. 方式四：查看系统环境变量
# ============================================
print("\n【方式四：系统环境变量】")
print("-" * 70)

env_keys = ['OPENAI_API_KEY', 'MCP_DASHSCOPE_BASE_URL', 'DASHSCOPE_API_KEY']
for key in env_keys:
    value = os.environ.get(key)
    if value:
        print(f"  {key} = {value[:20]}..." if len(value) > 20 else f"  {key} = {value}")
    else:
        print(f"  {key} = (未设置)")

# ============================================
# 6. 总结
# ============================================
print("\n" + "=" * 70)
print("【总结】")
print("=" * 70)

# 判断哪个方式能读到值
if api_key_env and mcp_url_env:
    print("✅ os.getenv() 读取成功")
    print(f"   OPENAI_API_KEY = {api_key_env[:20]}...")
    print(f"   MCP_DASHSCOPE_BASE_URL = {mcp_url_env}")
else:
    print("❌ os.getenv() 读取失败")
    print("   可能原因:")
    print("   1. .env 文件不存在或路径不对")
    print("   2. .env 文件中变量名拼写错误")
    print("   3. 环境变量未设置")

if api_key_config and mcp_url_config:
    print("\n✅ config 对象读取成功")
    print(f"   config.openai_api_key = {api_key_config[:20]}...")
    print(f"   config.mcp_dashscope_base_url = {mcp_url_config}")
else:
    print("\n❌ config 对象读取失败")
    print("   可能原因:")
    print("   1. config.py 中未定义这些属性")
    print("   2. config 读取的环境变量名不同")

print("=" * 70)