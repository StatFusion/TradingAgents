import os
import httpx
import threading
import io
import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. 从 GitHub Secrets 动态加载密钥
# ==============================================================================
# GitHub 会自动将 Secrets 注入到环境变量中
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

# 处理多个 Alpha Vantage Keys (从逗号分隔的字符串转为列表)
av_keys_raw = os.getenv("AV_KEYS", "")
alpha_vantage_keys = [k.strip() for k in av_keys_raw.split(",") if k.strip()]

if not alpha_vantage_keys:
    print("❌ 错误: 未能在环境变量中找到 AV_KEYS，请检查 GitHub Secrets 配置。")
    exit(1)

# 用于确保多线程下打印不乱序的锁
print_lock = threading.Lock()

# 2. 导入 OpenAI 的官方库并打补丁
import openai

def patch_openai(target):
    original_init = target.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["base_url"] = "https://api.z.ai/api/coding/paas/v4"
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
        if "http_client" in kwargs: del kwargs["http_client"]
        original_init(self, *args, **kwargs)
    target.__init__ = patched_init

patch_openai(openai.AsyncOpenAI)
patch_openai(openai.OpenAI)

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# ==============================================================================
# 3. 定义任务函数
# ==============================================================================
def analyze_stock_task(stock, api_key, config, reports_dir):
    os.environ["ALPHA_VANTAGE_API_KEY"] = api_key
    file_path = os.path.join(reports_dir, f"{stock}_analysis.txt")
    output_buffer = io.StringIO()
    
    with print_lock:
        print(f"🚀 线程启动: {stock} (使用 Key: {api_key[:4]}****)")

    try:
        with contextlib.redirect_stdout(output_buffer):
            ta = TradingAgentsGraph(debug=True, config=config)
            _, decision = ta.propagate(stock, "2026-02-15")
            print("\n" + "="*50)
            print(f"📊 {stock} 最终交易决策总结")
            print("="*50)
            print(decision)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(output_buffer.getvalue())
            
        return f"✅ 【{stock}】分析完成。"
    
    except Exception as e:
        return f"❌ 【{stock}】失败: {e}"
    finally:
        output_buffer.close()

# ==============================================================================
# 4. 主程序运行
# ==============================================================================
if __name__ == "__main__":
    reports_dir = "reports"
    if not os.path.exists(reports_dir): os.makedirs(reports_dir)
    
    # 待分析股票池
    stock_list = ["CHRW", "RTX", "NOW", "TSM", "SHLD", "QQQM", "RSP", "VXUS", "VTI"] 
    
    base_config = DEFAULT_CONFIG.copy()
    base_config["llm_provider"] = "openai"        
    base_config["deep_think_llm"] = "glm-5" 
    base_config["quick_think_llm"] = "glm-5"
    base_config["max_debate_rounds"] = 2

    print(f"🔥 并发分析模式开启（并发数: 3）...")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                analyze_stock_task, 
                stock, 
                alpha_vantage_keys[i % len(alpha_vantage_keys)], 
                base_config, 
                reports_dir
            ): stock for i, stock in enumerate(stock_list)
        }
        
        for future in as_completed(futures):
            print(future.result())

    print("\n🎉 所有任务已结束！")
