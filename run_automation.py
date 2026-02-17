import os
import httpx
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. 从 GitHub Secrets 动态加载密钥 (绝不暴露明文)
# ==============================================================================
openai_key = os.getenv("OPENAI_API_KEY", "")
os.environ["OPENAI_API_KEY"] = openai_key

av_keys_raw = os.getenv("AV_KEYS", "")
alpha_vantage_keys = [k.strip() for k in av_keys_raw.split(",") if k.strip()]

if not alpha_vantage_keys or not openai_key:
    print("❌ 致命错误: 未能在环境变量中找到必要的 API Keys。请检查 GitHub Secrets 配置。")
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
config["max_debate_rounds"] = 3

# 创建专属文件夹
reports_dir = "reports"
if not os.path.exists(reports_dir):
    os.makedirs(reports_dir)

stock_list = ["KWEB"]

# 增加一个线程锁，专门用来防止初始化时 API Key 被覆盖
init_lock = threading.Lock()

# ==============================================================================
# 核心执行函数：提取 State 并完美保存
# ==============================================================================
def process_stock(stock, current_key):
    # 使用锁来确保：修改环境变量 -> 初始化 Agent 这一步是安全的
    with init_lock:
        os.environ["ALPHA_VANTAGE_API_KEY"] = current_key
        print(f"\n=============================================")
        print(f"🔍 正在启动分析: {stock} ... (当前使用数据 Key: {current_key[:4]}****)")
        print(f"=============================================")
        
        # ⚠️ 必须在锁内初始化！
        ta = TradingAgentsGraph(debug=True, config=config)

    try:
        # 接收返回的 state（包含了所有历史对话记录）
        final_state, decision = ta.propagate(stock, "2026-02-15")
        
        print(f"\n📊 【{stock}】分析完成！正在保存全量对话报告...")
        
        # 将最终的内容保存为 txt 文件
        file_path = os.path.join(reports_dir, f"{stock}_analysis.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"目标股票: {stock}\n")
            f.write(f"分析日期: 2026-02-15\n")
            f.write("="*50 + "\n\n")
            
            f.write("【AI 团队推演与对话全记录】\n")
            f.write("-" * 50 + "\n")
            
            # 从内存中提取完整的历史聊天记录
            if isinstance(final_state, dict) and "messages" in final_state:
                for msg in final_state["messages"]:
                    msg_type = getattr(msg, "type", type(msg).__name__).upper()
                    content = getattr(msg, "content", "")
                    
                    f.write(f"\n[{msg_type} MESSAGE]\n")
                    
                    # 1. 写入普通文本
                    if content:
                        f.write(f"{content}\n")
                        
                    # 2. 写入 AI 调用工具的隐藏动作 (防止出现大段空白)
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        f.write("🔧 [动作] AI 正在调用工具:\n")
                        for tool in msg.tool_calls:
                            f.write(f"   - 工具名称: {tool.get('name')}\n")
                            f.write(f"   - 传递参数: {tool.get('args')}\n")
                    
                    # 3. 写入工具返回的数据
                    if msg_type == "TOOL" and not content:
                        f.write(str(msg) + "\n")
                        
                    f.write("-" * 30 + "\n")
            else:
                f.write(str(final_state) + "\n")
                
            f.write("\n" + "="*50 + "\n")
            f.write("【最终交易决策总结】\n")
            f.write("="*50 + "\n")
            f.write(str(decision) + "\n")
            
        return f"✅ 【{stock}】全量深度报告已成功保存至: {file_path}"
        
    except Exception as e:
        return f"❌ 【{stock}】分析失败，错误信息: {e}"

# ==============================================================================
# 主入口：用 ThreadPoolExecutor 并发执行
# ==============================================================================
if __name__ == "__main__":
    print(f"🚀 开始批量运行测试并启用 API Key 自动轮询机制 (并发数: 3)...")
    print(f"✅ 成功加载 {len(alpha_vantage_keys)} 个 Alpha Vantage API Keys")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for i, stock in enumerate(stock_list):
            key = alpha_vantage_keys[i % len(alpha_vantage_keys)]
            futures.append(executor.submit(process_stock, stock, key))
            
        for future in as_completed(futures):
            print(future.result())
            
    print("\n🎉 所有股票分析任务已全部结束！请在 Artifacts 中下载深度研报。")
