import os
import httpx
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. 从 GitHub Secrets 动态加载密钥
# ==============================================================================
openai_key = os.getenv("OPENAI_API_KEY", "")
os.environ["OPENAI_API_KEY"] = openai_key

av_keys_raw = os.getenv("AV_KEYS", "")
alpha_vantage_keys = [k.strip() for k in av_keys_raw.split(",") if k.strip()]

if not alpha_vantage_keys or not openai_key:
    print("❌ 致命错误: 未能在环境变量中找到必要的 API Keys。请检查 GitHub Secrets。")
    exit(1)

# 2. 导入 OpenAI 的官方库
import openai

# 3. 核心猴子补丁：直接拦截 OpenAI Client 的初始化行为
original_init = openai.AsyncOpenAI.__init__

def patched_init(self, *args, **kwargs):
    kwargs["base_url"] = "https://api.z.ai/api/coding/paas/v4"
    kwargs["api_key"] = openai_key
    if "http_client" in kwargs:
        del kwargs["http_client"]
    original_init(self, *args, **kwargs)

openai.AsyncOpenAI.__init__ = patched_init

original_sync_init = openai.OpenAI.__init__
def patched_sync_init(self, *args, **kwargs):
    kwargs["base_url"] = "https://api.z.ai/api/coding/paas/v4"
    kwargs["api_key"] = openai_key
    if "http_client" in kwargs:
        del kwargs["http_client"]
    original_sync_init(self, *args, **kwargs)

openai.OpenAI.__init__ = patched_sync_init

# ==============================================================================
# 补丁打完后，正常导入框架
# ==============================================================================
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        
config["deep_think_llm"] = "glm-5" 
config["quick_think_llm"] = "glm-5"
config["max_debate_rounds"] = 2 

# 创建专属文件夹
reports_dir = "reports"
if not os.path.exists(reports_dir):
    os.makedirs(reports_dir)

stock_list = ["CHRW", "RTX", "NOW", "TSM", "SHLD", "QQQM", "RSP", "VXUS", "VTI"] 

# 增加一个线程锁，专门用来防止 API Key 被其他线程覆盖
init_lock = threading.Lock()

# ==============================================================================
# 核心执行函数
# ==============================================================================
def process_stock(stock, current_key):
    # 使用锁来确保：修改环境变量 -> 初始化 Agent 这一步是安全的
    with init_lock:
        os.environ["ALPHA_VANTAGE_API_KEY"] = current_key
        print(f"\n=============================================")
        print(f"🔍 正在启动分析: {stock} ... (当前使用数据 Key: {current_key[:4]}****)")
        print(f"=============================================")
        
        # ⚠️ 必须在锁内初始化！这样它才会读到刚刚换上的新 Key
        ta = TradingAgentsGraph(debug=True, config=config)

    try:
        # 框架会自动跑当前股票 (这一步最耗时，放在锁外面并发执行)
        _, decision = ta.propagate(stock, "2026-02-15")
        
        print(f"\n📊 【{stock}】分析完成！")
        
        # 将最终的 decision 保存为 txt 文件
        file_path = os.path.join(reports_dir, f"{stock}_analysis.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"目标股票: {stock}\n")
            f.write(f"分析日期: 2026-02-15\n")
            f.write("="*50 + "\n\n")
            f.write(str(decision))
            
        return f"✅ 【{stock}】报告已成功保存至: {file_path}"
        
    except Exception as e:
        return f"❌ 【{stock}】分析失败，错误信息: {e}"

# ==============================================================================
# 核心更改：用 ThreadPoolExecutor 替换 for loop
# ==============================================================================
if __name__ == "__main__":
    print(f"🚀 开始批量运行测试并启用 API Key 自动轮询机制 (并发数: 3)...")
    print(f"✅ 成功加载 {len(alpha_vantage_keys)} 个 Alpha Vantage API Keys")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        # 提交所有的股票任务
        futures = []
        for i, stock in enumerate(stock_list):
            key = alpha_vantage_keys[i % len(alpha_vantage_keys)]
            futures.append(executor.submit(process_stock, stock, key))
            
        # 等待并打印结果
        for future in as_completed(futures):
            print(future.result())
            
    print("\n🎉 所有股票分析任务已全部结束！请去 reports 文件夹查看报告。")
