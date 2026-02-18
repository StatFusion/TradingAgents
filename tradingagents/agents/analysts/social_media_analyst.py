import os
import requests
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.agents.utils.agent_utils import get_news
from tradingagents.dataflows.config import get_config

# ==============================================================================
# 【修改 1】把它变成一个普通的 Python 函数，去掉 @tool 装饰器
# ==============================================================================
def perform_brave_search(query: str) -> str:
    """自动在后台搜索社交媒体数据，直接喂给大模型"""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return "Brave Search API Key missing."
    
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key
    }
    params = {"q": query, "count": 5} 
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for result in data.get("web", {}).get("results", []):
            title = result.get("title", "")
            description = result.get("description", "")
            results.append(f"- {title}: {description}")
            
        return "\n".join(results) if results else "No social media discussions found."
    except Exception as e:
        return f"Brave Search API error: {e}"

# ==============================================================================
# 【修改 2】修改 Analyst 节点逻辑
# ==============================================================================
def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]

        # 保持原样！不要把 Brave 加进这里，防止底层图执行器报错
        tools = [
            get_news,
        ]

        # 🔥 【核心魔法】：在构建大模型请求前，Python 自动执行 Brave 搜索
        brave_query = f"{ticker} stock social media sentiment Reddit Twitter opinion"
        brave_search_results = perform_brave_search(brave_query)

        # 🔥 【核心魔法】：将搜到的数据直接“硬塞”给系统提示词
        system_message = (
            "You are a social media and company specific news researcher/analyst tasked with analyzing social media posts, recent company news, and public sentiment for a specific company over the past week. "
            "You will be given a company's name. Your objective is to write a comprehensive long report detailing your analysis, insights, and implications for traders and investors. "
            "Use the get_news(query, start_date, end_date) tool to search for company-specific news. "
            "Do not simply state the trends are mixed, provide detailed and finegrained analysis and insights that may help traders make decisions. "
            "Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read.\n\n"
            "==========================================================\n"
            "🚨 [CRITICAL: PRE-FETCHED SOCIAL MEDIA DATA] 🚨\n"
            "I have already used Brave Search to pull the latest alternative web and social media discussions for you. "
            f"Please strongly incorporate the following sentiment data into your report for {ticker}:\n\n"
            f"{brave_search_results}\n"
            "==========================================================\n"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. The current company we want to analyze is {ticker}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "sentiment_report": report,
        }

    return social_media_analyst_node
