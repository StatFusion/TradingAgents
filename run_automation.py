from datetime import datetime
import os
import httpx
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. 从 GitHub Secrets 动态加载密钥 (绝不暴露明文)
# ==============================================================================
openai_key = os.getenv("OPENAI_API_KEY", "")
os.environ["OPENAI_API_KEY"] = openai_key

# 【新增】动态加载 Brave Search API Key 并注入环境变量
brave_key = os.getenv("BRAVE_API_KEY", "")
os.environ["BRAVE_API_KEY"] = brave_key

av_keys_raw = os.getenv("AV_KEYS", "")
alpha_vantage_keys = [k.strip() for k in av_keys_raw.split(",") if k.strip()]

# 【修改】安全检查：确保三种 Key 都有配置
if not alpha_vantage_keys or not openai_key or not brave_key:
    print("❌ 致命错误: 未能在环境变量中找到必要的 API Keys (OpenAI, AV, 或 BRAVE)。请检查 GitHub Secrets 配置。")
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

stock_list = ["AMZN","VTI","TSM","NOW","NVDA","MSFT","AMD"]

# 增加一个线程锁，专门用来防止初始化时 API Key 被覆盖
init_lock = threading.Lock()

# ==============================================================================
# 核心执行函数：提取 State 并完美保存
# ==============================================================================
def process_stock(stock, current_key):
    # 自动获取今天日期，格式为 YYYY-MM-DD
    today_str = datetime.today().strftime('%Y-%m-%d')
    
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
        final_state, decision = ta.propagate(stock, today_str)
        
        print(f"\n📊 【{stock}】分析完成！正在保存全量对话报告...")
        
        # 将最终的内容保存为 txt 文件
        file_path = os.path.join(reports_dir, f"{stock}_analysis.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"目标股票: {stock}\n")
            f.write(f"分析日期: {today_str}\n")
            f.write("="*50 + "\n\n")
            
            f.write("【AI 投研团队推演与深度分析全记录】\n")
            f.write("-" * 50 + "\n")
            
            # --- 核心修改：针对 TradingAgents 的底层结构进行精准提取 ---
            if isinstance(final_state, dict):
                # 状态数据可能被日期键包裹，剥开它
                state_data = final_state.get(today_str, final_state)
                
                # 1. 提取各个专业分析师的报告
                reports = {
                    "📈 市场与技术面分析 (Market Report)": "market_report",
                    "📊 基本面分析 (Fundamentals Report)": "fundamentals_report",
                    "📰 新闻与事件分析 (News Report)": "news_report",
                    "🧠 市场情绪分析 (Sentiment Report)": "sentiment_report"
                }
                for title, key in reports.items():
                    if key in state_data and state_data[key]:
                        f.write(f"\n\n{'='*40}\n{title}\n{'='*40}\n")
                        f.write(str(state_data[key]))
                
                # 2. 提取投资逻辑辩论记录 (Investment Debate)
                if "investment_debate_state" in state_data:
                    f.write(f"\n\n{'='*40}\n🗣️ 投资逻辑内部辩论 (Investment Debate)\n{'='*40}\n")
                    debate = state_data["investment_debate_state"]
                    if "bull_history" in debate:
                        f.write(f"\n[🟢 多方观点 Bull Analyst]:\n{debate['bull_history']}\n")
                    if "bear_history" in debate:
                        f.write(f"\n[🔴 空方观点 Bear Analyst]:\n{debate['bear_history']}\n")
                    if "judge_decision" in debate:
                        f.write(f"\n[⚖️ 投资总监裁决 Portfolio Manager]:\n{debate['judge_decision']}\n")
                
                # 3. 提取风险管理辩论记录 (Risk Debate)
                if "risk_debate_state" in state_data:
                    f.write(f"\n\n{'='*40}\n🛡️ 风险控制内部辩论 (Risk Debate)\n{'='*40}\n")
                    risk = state_data["risk_debate_state"]
                    if "aggressive_history" in risk:
                        f.write(f"\n[⚔️ 激进派观点 Aggressive Analyst]:\n{risk['aggressive_history']}\n")
                    if "conservative_history" in risk:
                        f.write(f"\n[🛡️ 保守派观点 Conservative Analyst]:\n{risk['conservative_history']}\n")
                    if "neutral_history" in risk:
                        f.write(f"\n[⚖️ 中立派观点 Neutral Analyst]:\n{risk['neutral_history']}\n")
                    if "judge_decision" in risk:
                        f.write(f"\n[🛑 风控总监裁决 Risk Judge]:\n{risk['judge_decision']}\n")
            else:
                f.write("⚠️ 未能解析到标准的状态字典，输出原始状态：\n")
                f.write(str(final_state) + "\n")
                
            # --- 最终决策输出 ---
            f.write("\n\n" + "="*50 + "\n")
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
