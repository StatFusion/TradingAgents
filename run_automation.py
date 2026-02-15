import os
import sys
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. 子进程任务（负责干活：完全独立的环境和 API Key）
# ==============================================================================
def worker_main(stock):
    # 猴子补丁在这里打，确保每个进程独立拦截 GLM
    import openai
    original_init = openai.OpenAI.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["base_url"] = "https://api.z.ai/api/coding/paas/v4"
        # 从老板进程传下来的环境变量中读取 Key
        kwargs["api_key"] = os.environ.get("OPENAI_API_KEY")
        if "http_client" in kwargs: del kwargs["http_client"]
        original_init(self, *args, **kwargs)
    
    openai.OpenAI.__init__ = patched_init
    openai.AsyncOpenAI.__init__ = patched_init

    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "openai"        
    config["deep_think_llm"] = "glm-5" 
    config["quick_think_llm"] = "glm-5"
    config["max_debate_rounds"] = 2

    # 以下内容会被操作系统强制“录音”并写入文件
    print(f"🚀 [AI Agent 启动] 正在深度分析: {stock}")
    print(f"🔑 当前分配数据 Key: {os.environ.get('ALPHA_VANTAGE_API_KEY', '')[:4]}****")
    print("="*60)
    
    # 必须是 debug=True 才能生成深度研报
    ta = TradingAgentsGraph(debug=True, config=config)
    _, decision = ta.propagate(stock, "2026-02-15")
    
    print("\n" + "="*60)
    print(f"📊 【{stock}】最终交易决策总结")
    print("="*60)
    print(decision)


# ==============================================================================
# 2. 主进程调度函数（负责分配工作并收集报告）
# ==============================================================================
def master_task(stock, api_key, reports_dir):
    # 将 Key 和无缓冲设置写入独立的系统环境变量
    env = os.environ.copy()
    env["ALPHA_VANTAGE_API_KEY"] = api_key
    env["PYTHONUNBUFFERED"] = "1" 
    
    file_path = os.path.join(reports_dir, f"{stock}_analysis.txt")
    
    # 召唤隐形的子终端
    cmd = [sys.executable, os.path.abspath(__file__), "--worker", stock]
    
    try:
        # 强制把所有标准输出和框架底层日志吸走
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)
            if result.stderr:
                f.write("\n\n--- ⚠️ 底层框架调试信息 (STDERR) ---\n")
                f.write(result.stderr)
                
        return f"✅ 【{stock}】分析完成，全量思考过程已存入: {file_path}"
    
    except subprocess.CalledProcessError as e:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("⚠️ 程序运行崩溃，以下是崩溃前的截获日志：\n")
            f.write(e.stdout)
            f.write("\n\n--- ❌ 崩溃详细报错 (STDERR) ---\n")
            f.write(e.stderr)
        return f"❌ 【{stock}】分析失败 (详细报错已存入 txt 文件)"


# ==============================================================================
# 3. 脚本入口 (老板模式与打工人模式分流)
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=str, help="子进程专属参数")
    args, _ = parser.parse_known_args()

    if args.worker:
        worker_main(args.worker)
        sys.exit(0)

    # ==========================================================================
    # 4. 老板模式：发号施令 (从 GitHub Secrets 读取配置)
    # ==========================================================================
    reports_dir = "reports"
    if not os.path.exists(reports_dir): os.makedirs(reports_dir)
    
    # 安全读取 GitHub 注入的环境变量
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        print("❌ 致命错误: 未能在环境变量中找到 OPENAI_API_KEY")
        sys.exit(1)

    av_keys_raw = os.getenv("AV_KEYS", "")
    alpha_vantage_keys = [k.strip() for k in av_keys_raw.split(",") if k.strip()]
    
    if not alpha_vantage_keys:
        print("❌ 致命错误: 未能在环境变量中找到 AV_KEYS")
        sys.exit(1)

    # 你的持仓与观察池
    stock_list = ["RTX", "NOW", "TSM", "SHLD", "QQQM", "RSP", "VXUS", "VTI"] 

    print(f"🔥 终极子进程并发模式启动 (物理级防串线, 并发数: 3)...")
    print(f"✅ 成功加载 {len(alpha_vantage_keys)} 个 Alpha Vantage API Keys")
    print(f"⚠️ 系统正在强制截获底层框架日志，过程将直接写入 txt，终端只显示进度。\n")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                master_task, 
                stock, 
                alpha_vantage_keys[i % len(alpha_vantage_keys)], 
                reports_dir
            ): stock for i, stock in enumerate(stock_list)
        }
        
        for future in as_completed(futures):
            print(future.result())

    print("\n🎉 所有任务已结束！云端研报生成完毕。")
